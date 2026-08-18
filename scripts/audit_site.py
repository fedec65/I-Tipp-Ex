#!/usr/bin/env python3
"""i-tipp-ex Layer D: batch website audit via sitemap crawl.

This is the ONLY script in the skill permitted to perform network I/O
(stdlib urllib only). Everything is fetched into memory or a temporary
directory; nothing persists except the report written by -o.

Usage:
    python3 audit_site.py <url-or-host> --i-am-authorized [flags]

The --i-am-authorized flag is mandatory: crawling touches third-party-visible
infrastructure, and the operator must confirm they own or are authorized to
audit the target site.
"""

from __future__ import annotations

import io
import json
import os
import re
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
import xml.etree.ElementTree as ET
from html import unescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from report import (
    DEFAULT_MAX_BYTES,
    Finding,
    Report,
    SEVERITIES,
    STATISTICAL_WATERMARK_NOTE,
    build_base_parser,
    emit_report,
)
from audit_file import audit_file, parse_html
import audit_text

UA_STRING = "i-tipp-ex/1.0 (+https://example.invalid/i-tipp-ex; audit bot)"

REFUSAL = (
    "Refusing to crawl: audit_site.py makes HTTP requests against "
    "infrastructure that may belong to third parties. Re-run with "
    "--i-am-authorized to confirm that you own the target site or are "
    "otherwise authorized to audit it."
)

_ASSET_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff",
               ".svg", ".pdf", ".docx", ".epub")

_SITEMAP_CANDIDATES = ("sitemap.xml",)  # robots + index names handled below
_SITEMAP_FALLBACKS = ("sitemap_index.xml", "sitemap-index.xml")


# ---------------------------------------------------------------------------
# Hardened fetching (politeness + SSRF guards)
# ---------------------------------------------------------------------------

class _SchemeGuard(urllib.request.HTTPRedirectHandler):
    """Follow redirects but refuse any non-http(s) target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urllib.parse.urlparse(newurl).scheme
        if scheme not in ("http", "https"):
            raise urllib.error.URLError(
                f"refusing redirect to non-http(s) URL: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SchemeGuard)
_last_request_at = 0.0


class FetchError(Exception):
    pass


class FetchTimeout(FetchError):
    pass


def fetch(url: str, timeout: float, cap: int, delay: float) -> tuple[bytes, str | None]:
    """Fetch url -> (body, note). Body capped at `cap` bytes after any
    gzip/deflate decompression; over-cap decompression is truncated with a
    note. Raises FetchError / FetchTimeout on failure."""
    global _last_request_at
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise FetchError(f"non-http(s) URL refused: {url}")
    wait = delay - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA_STRING,
        "Accept-Encoding": "gzip, deflate",
    })
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read(cap + 1)
            encoding = (resp.headers.get("Content-Encoding") or "").lower()
    except (socket.timeout, TimeoutError) as e:
        raise FetchTimeout(f"timeout after {timeout}s: {url}") from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (socket.timeout, TimeoutError)) or \
                "timed out" in str(reason):
            raise FetchTimeout(f"timeout after {timeout}s: {url}") from e
        raise FetchError(f"fetch failed for {url}: {reason}") from e
    finally:
        _last_request_at = time.monotonic()

    note = None
    if encoding in ("gzip", "deflate"):
        wbits = 16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS
        try:
            d = zlib.decompressobj(wbits)
        except zlib.error as e:
            raise FetchError(f"bad {encoding} payload from {url}: {e}") from e
        try:
            out = d.decompress(raw, cap + 1)
        except zlib.error:
            if encoding == "deflate":  # some servers send raw deflate
                d = zlib.decompressobj(-zlib.MAX_WBITS)
                out = d.decompress(raw, cap + 1)
            else:
                raise FetchError(f"bad gzip payload from {url}")
        if len(out) > cap:
            out = out[:cap]
            note = (f"decompressed body exceeded --max-resource-bytes "
                    f"({cap}); truncated (possible zip bomb)")
        raw = out
    elif len(raw) > cap:
        raw = raw[:cap]
        note = f"body truncated at --max-resource-bytes ({cap})"
    return raw, note


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

def robots_disallows(text: str) -> list[str]:
    """Disallow paths from groups matching '*' or our UA token."""
    disallows: list[str] = []
    agents: list[str] = []
    applies = False
    seen_rule = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if seen_rule:  # a rule already closed the previous group
                agents, applies, seen_rule = [], False, False
            agents.append(value.lower())
            applies = any(a == "*" or "i-tipp-ex" in a for a in agents)
        elif key == "disallow":
            seen_rule = True
            if applies and value:
                disallows.append(value)
    return disallows


def robots_sitemaps(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        key, _, value = raw.partition(":")
        if key.strip().lower() == "sitemap" and value.strip():
            out.append(value.strip())
    return out


# ---------------------------------------------------------------------------
# Sitemaps
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_sitemap(xml_bytes: bytes) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemap_urls)."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return [], []
    kind = _local(root.tag)
    pages, children = [], []
    if kind == "urlset":
        for url in root:
            if _local(url.tag) == "url":
                for child in url:
                    if _local(child.tag) == "loc" and child.text:
                        pages.append(child.text.strip())
    elif kind == "sitemapindex":
        for sm in root:
            if _local(sm.tag) == "sitemap":
                for child in sm:
                    if _local(child.tag) == "loc" and child.text:
                        children.append(child.text.strip())
    return pages, children


# ---------------------------------------------------------------------------
# Visible-text extraction (crude by design — for the Unicode layer only)
# ---------------------------------------------------------------------------

def visible_text(html: str) -> str:
    t = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
    t = re.sub(r"<style\b.*?</style>", " ", t, flags=re.I | re.S)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return unescape(t)


def collect_asset_urls(html: str, page_url: str, host: str) -> list[str]:
    """Extension-based asset DISCOVERY (collection only — the audit itself
    still routes by magic bytes). Same-host only."""
    out = []
    for m in re.finditer(r"""(?:src|href)\s*=\s*["']([^"']+)["']""",
                         html, re.I):
        u = urllib.parse.urljoin(page_url, m.group(1))
        p = urllib.parse.urlparse(u)
        if p.scheme in ("http", "https") and p.hostname == host and \
                p.path.lower().endswith(_ASSET_EXTS):
            out.append(u)
    return out


# ---------------------------------------------------------------------------
# Page audit
# ---------------------------------------------------------------------------

def audit_page(url: str, html: str) -> Report:
    """Audit one fetched HTML page: generator/metadata rules + Unicode layer
    on both the raw source and the stripped visible text."""
    report = Report(target=url)
    for f in parse_html(html):
        report.add_finding(f)
    for f in audit_text.scan_text(html):
        f.location = f"source: {f.location}"
        report.add_finding(f)
    for f in audit_text.scan_text(visible_text(html)):
        f.location = f"visible text: {f.location}"
        report.add_finding(f)
    report.add_note(STATISTICAL_WATERMARK_NOTE)
    return report


# ---------------------------------------------------------------------------
# Site report
# ---------------------------------------------------------------------------

class SiteReport(Report):
    def __init__(self, target: str):
        super().__init__(target=target)
        self.pages: list[Report] = []
        self.assets: list[Report] = []
        self.coverage = {"discovered": 0, "audited": 0, "capped": 0,
                         "timeouts": 0, "skipped": 0}

    def coverage_line(self) -> str:
        c = self.coverage
        return (f"Audited {c['audited']} of {c['discovered']} sitemap URLs "
                f"(capped: {c['capped']}, timeouts: {c['timeouts']}, "
                f"skipped: {c['skipped']})")

    def to_json_dict(self) -> dict:
        d = super().to_json_dict()
        d["coverage"] = dict(self.coverage)
        d["pages"] = [r.to_json_dict() for r in self.pages]
        d["assets"] = [r.to_json_dict() for r in self.assets]
        return d

    def render_human(self) -> str:
        base = super().render_human()
        lines = ["", "Pages:"]
        def key(r: Report):
            return (-(r.severity_counts()["high"] > 0), -len(r.findings),
                    r.target)
        for r in sorted(self.pages, key=key):
            c = r.severity_counts()
            lines.append(
                f"- {r.target}: {len(r.findings)} findings "
                f"({c['high']} high, {c['medium']} medium, {c['low']} low, "
                f"{c['informational']} informational)")
        if self.assets:
            lines.append("")
            lines.append("Assets:")
            for r in sorted(self.assets, key=key):
                c = r.severity_counts()
                lines.append(
                    f"- {r.target}: {len(r.findings)} findings "
                    f"({c['high']} high, {c['medium']} medium, {c['low']} low, "
                    f"{c['informational']} informational)")
        lines.append("")
        lines.append(self.coverage_line())
        return base + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

def normalize_base(raw: str) -> str:
    raw = raw.strip()
    if "://" not in raw:
        raw = "https://" + raw
    p = urllib.parse.urlparse(raw)
    if p.scheme not in ("http", "https"):
        raise FetchError(f"non-http(s) scheme refused: {p.scheme}")
    return f"{p.scheme}://{p.netloc}"


def audit_site(base: str, *, max_pages: int, max_assets: int,
               include_assets: bool, delay: float, timeout: float,
               max_resource_bytes: int,
               max_bytes: int = DEFAULT_MAX_BYTES) -> SiteReport:
    report = SiteReport(target=base)
    host = urllib.parse.urlparse(base).hostname

    # robots.txt (needed for Disallow regardless of sitemap discovery)
    disallows: list[str] = []
    robots_map_urls: list[str] = []
    try:
        body, _ = fetch(f"{base}/robots.txt", timeout, max_resource_bytes, delay)
        robots = body.decode("utf-8", "replace")
        disallows = robots_disallows(robots)
        robots_map_urls = robots_sitemaps(robots)
    except FetchError as e:
        report.add_note(f"robots.txt unavailable: {e}; proceeding without "
                        "robots rules")

    # Sitemap discovery: /sitemap.xml -> robots Sitemap: -> common fallbacks
    seen_sitemaps: set[str] = set()
    discovered: list[str] = []
    dropped_cross_host = 0

    def walk_sitemap(url: str, depth: int) -> None:
        nonlocal dropped_cross_host
        if url in seen_sitemaps or depth > 3:
            return
        seen_sitemaps.add(url)
        try:
            body, _ = fetch(url, timeout, max_resource_bytes, delay)
        except FetchError as e:
            report.add_note(f"sitemap fetch failed: {e}")
            return
        pages, children = parse_sitemap(body)
        for u in pages:
            p = urllib.parse.urlparse(u)
            if p.scheme not in ("http", "https"):
                continue
            if p.hostname != host:
                dropped_cross_host += 1
                continue
            if u not in discovered:
                discovered.append(u)
        for child in children:
            if urllib.parse.urlparse(child).hostname != host:
                dropped_cross_host += 1
                continue
            walk_sitemap(child, depth + 1)

    candidates = [f"{base}/sitemap.xml"]
    candidates += robots_map_urls
    candidates += [f"{base}/{n}" for n in _SITEMAP_FALLBACKS]
    for cand in candidates:
        walk_sitemap(cand, 0)
        if discovered:
            break
    if dropped_cross_host:
        report.add_note(f"dropped {dropped_cross_host} cross-host sitemap "
                        "entr(ies); only same-host URLs are audited")
    if not discovered:
        report.add_note("no sitemap URLs discovered; auditing the base URL only")
        discovered = [base + "/"]

    report.coverage["discovered"] = len(discovered)

    asset_urls: list[str] = []
    for url in discovered:
        path = urllib.parse.urlparse(url).path
        if any(path.startswith(rule) for rule in disallows):
            report.coverage["skipped"] += 1
            continue
        if report.coverage["audited"] >= max_pages:
            report.coverage["capped"] += 1
            continue
        try:
            body, note = fetch(url, timeout, max_resource_bytes, delay)
        except FetchTimeout as e:
            report.coverage["timeouts"] += 1
            report.add_note(str(e))
            continue
        except FetchError as e:
            report.coverage["skipped"] += 1
            report.add_note(str(e))
            continue
        if note:
            report.add_note(f"{url}: {note}")
        html = body.decode("utf-8", "replace")
        page = audit_page(url, html)
        report.pages.append(page)
        report.coverage["audited"] += 1
        for f in page.findings:
            report.add_finding(Finding(
                severity=f.severity, confidence=f.confidence,
                category=f.category, location=url,
                evidence=f.evidence, context=f.context,
                note=f"at {f.location}" + (f". {f.note}" if f.note else ""),
            ))
        for a in collect_asset_urls(html, url, host):
            if a not in asset_urls:
                asset_urls.append(a)

    if any(r.findings for r in report.pages):
        report.add_note(STATISTICAL_WATERMARK_NOTE)

    if include_assets:
        with tempfile.TemporaryDirectory(prefix="i-tipp-ex-") as tmp:
            for i, aurl in enumerate(asset_urls[:max_assets]):
                try:
                    body, note = fetch(aurl, timeout, max_resource_bytes, delay)
                except FetchTimeout as e:
                    report.coverage["timeouts"] += 1
                    report.add_note(str(e))
                    continue
                except FetchError as e:
                    report.add_note(str(e))
                    continue
                if note:
                    report.add_note(f"{aurl}: {note}")
                tmp_path = os.path.join(tmp, f"asset-{i}")
                with open(tmp_path, "wb") as fh:
                    fh.write(body)
                sub = audit_file(tmp_path, max_bytes=max_bytes)
                sub.target = aurl
                report.assets.append(sub)
                for f in sub.findings:
                    report.add_finding(Finding(
                        severity=f.severity, confidence=f.confidence,
                        category=f.category, location=aurl,
                        evidence=f.evidence, context=f.context,
                        note=f"at {f.location}" + (f". {f.note}" if f.note else ""),
                    ))
        if len(asset_urls) > max_assets:
            report.add_note(f"{len(asset_urls) - max_assets} discovered asset "
                            "URL(s) not fetched (--max-assets)")
    elif asset_urls:
        report.add_note(f"{len(asset_urls)} asset URL(s) discovered but not "
                        "fetched (use --include-assets to audit them)")

    return report


def main(argv=None) -> int:
    parser = build_base_parser(
        description="i-tipp-ex Layer D: website audit via sitemap crawl. "
                    "The only network-capable script in this skill."
    )
    parser.add_argument("site", help="base URL or bare host to audit")
    parser.add_argument("--i-am-authorized", action="store_true",
                        help="confirm you own or are authorized to audit "
                             "the target site (required)")
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--max-assets", type=int, default=100)
    parser.add_argument("--include-assets", action="store_true",
                        help="download and audit linked image/document assets")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="seconds between requests (default: %(default)s)")
    parser.add_argument("--timeout", type=float, default=20,
                        help="per-request timeout in seconds (default: %(default)s)")
    parser.add_argument("--max-resource-bytes", type=int,
                        default=50 * 1024 * 1024,
                        help="per-resource wire/decompressed cap "
                             "(default: %(default)s)")
    args = parser.parse_args(argv)

    if not args.i_am_authorized:
        print(REFUSAL, file=sys.stderr)
        return 2

    try:
        base = normalize_base(args.site)
    except FetchError as e:
        print(str(e), file=sys.stderr)
        return 2

    report = audit_site(
        base,
        max_pages=args.max_pages,
        max_assets=args.max_assets,
        include_assets=args.include_assets,
        delay=args.delay,
        timeout=args.timeout,
        max_resource_bytes=args.max_resource_bytes,
        max_bytes=args.max_bytes,
    )
    emit_report(report, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
