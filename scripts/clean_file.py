#!/usr/bin/env python3
"""i-tipp-ex removal mode: format-aware metadata strip for container files.

Opt-in only — audit scripts never call this. Never in-place; atomic writes.
See spec §10 for the removal-mode contract.

Removal honesty: every strip result is labelled verifiable (post-clean
re-audit confirms), best-effort (bytes neutralized but container quirks may
leave recoverable traces), or refused. EPUB is audit-only in v1. PDF without
qpdf+exiftool on PATH is best-effort byte neutralization, labelled as such.
Statistical/pixel-domain watermarks are not addressable — stated, never
offered as a rewrite.

Usage:
    python3 clean_file.py <file> [-o out] [--force] [--yes] [--json] [--max-bytes N]
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from report import DEFAULT_MAX_BYTES, Finding, Report
from audit_file import (
    AI_MARKERS,
    audit_file,
    detect_container,
    find_ai_markers,
)
import clean_text
from clean_common import (
    atomic_write,
    confirm_or_abort,
    print_ownership_reminder,
    resolve_output,
)

PDF_TOOLS_NOTE = (
    "qpdf/exiftool not found; incremental-edit leftover metadata bytes may "
    "remain recoverable — install qpdf+exiftool for a verifiable strip"
)

NOT_ADDRESSABLE_NOTE = (
    "Pixel-domain watermarks and statistical (token-choice) watermarks are "
    "NOT addressable by any metadata strip; this tool does not rewrite "
    "content."
)

EPUB_REFUSAL = ("EPUB cleaning not supported in v1 (container rewriting "
                "fragile); audit-only format")


def _has_ai_marker(value: str) -> bool:
    return bool(find_ai_markers(value))


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------

_PNG_DROP_KEYWORDS = {"parameters", "prompt", "software", "comment",
                      "xml:com.adobe.xmp"}


def _png_chunk_kv(ctype: bytes, cdata: bytes) -> tuple[str, str] | None:
    try:
        if ctype == b"tEXt":
            kw, _, val = cdata.partition(b"\x00")
            return kw.decode("latin-1"), val.decode("latin-1", "replace")
        if ctype == b"zTXt":
            kw, _, rest = cdata.partition(b"\x00")
            return kw.decode("latin-1"), zlib.decompress(rest[1:]).decode(
                "utf-8", "replace")
        if ctype == b"iTXt":
            end = cdata.index(b"\x00")
            kw, rest = cdata[:end].decode("utf-8"), cdata[end + 1:]
            flag, rest = rest[0], rest[2:]
            rest = rest[rest.index(b"\x00") + 1:]
            val = rest[rest.index(b"\x00") + 1:]
            if flag == 1:
                val = zlib.decompress(val)
            return kw, val.decode("utf-8", "replace")
    except (ValueError, IndexError, zlib.error):
        return None
    return None


def strip_png(data: bytes) -> tuple[bytes, list[str]]:
    """Drop C2PA chunks and AI-carrying text chunks; kept chunks are copied
    verbatim, so no CRC recomputation is needed (nothing is modified in
    place — chunks are either kept byte-for-byte or dropped whole)."""
    out = bytearray(data[:8])
    dropped: list[str] = []
    pos = 8
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos:pos + 8 + length + 4]
        if len(chunk) < 8 + length + 4:
            break
        drop = False
        if ctype == b"caBX" or ctype.lower() == b"c2pa":
            dropped.append(ctype.decode("latin-1"))
            drop = True
        elif ctype in (b"tEXt", b"zTXt", b"iTXt"):
            kv = _png_chunk_kv(ctype, data[pos + 8:pos + 8 + length])
            if kv and (kv[0].lower() in _PNG_DROP_KEYWORDS or
                       _has_ai_marker(kv[1])):
                dropped.append(f"{ctype.decode()}:{kv[0]}")
                drop = True
        if not drop:
            out += chunk
        pos += 8 + length + 4
        if ctype == b"IEND":
            out += data[pos:]
            break
    return bytes(out), dropped


# ---------------------------------------------------------------------------
# JPEG
# ---------------------------------------------------------------------------

def strip_jpeg(data: bytes) -> tuple[bytes, list[str]]:
    """Drop APP1 (Exif+XMP), APP11 (JUMBF/C2PA), APP13, COM. Everything else,
    including everything after SOS begins, is copied verbatim."""
    out = bytearray(data[:2])
    dropped: list[str] = []
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[pos:pos + 2]
            pos += 2
            continue
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        if length < 2:
            out += data[pos:]
            break
        if marker == 0xDA:  # SOS — copy the rest verbatim (entropy data)
            out += data[pos:]
            break
        if marker == 0xE1:
            dropped.append("APP1 (Exif/XMP)")
        elif marker == 0xEB:
            dropped.append("APP11 (JUMBF/C2PA)")
        elif marker == 0xED:
            dropped.append("APP13 (Photoshop/IPTC)")
        elif marker == 0xFE:
            dropped.append("COM")
        else:
            out += data[pos:pos + 2 + length]
        pos += 2 + length
    return bytes(out), dropped


# ---------------------------------------------------------------------------
# WebP
# ---------------------------------------------------------------------------

def strip_webp(data: bytes) -> tuple[bytes, list[str]]:
    dropped: list[str] = []
    body = bytearray(b"WEBP")
    pos = 12
    while pos + 8 <= len(data):
        fourcc = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        chunk = data[pos:pos + 8 + size + (size & 1)]
        if fourcc in (b"C2PA", b"XMP ", b"EXIF"):
            dropped.append(fourcc.decode("latin-1").strip())
        else:
            body += chunk
        pos += 8 + size + (size & 1)
    if pos < len(data):
        body += data[pos:]
    out = b"RIFF" + len(body).to_bytes(4, "little") + bytes(body)
    return out, dropped


# ---------------------------------------------------------------------------
# GIF
# ---------------------------------------------------------------------------

def _gif_skip_subblocks(data: bytes, pos: int) -> int:
    while pos < len(data):
        n = data[pos]
        pos += 1
        if n == 0:
            break
        pos += n
    return pos


def strip_gif(data: bytes) -> tuple[bytes, list[str]]:
    """Drop comment extensions and XMP application extensions; everything
    else copied verbatim."""
    out = bytearray(data[:13])
    dropped: list[str] = []
    pos = 13
    if data[10] & 0x80:
        pos += 3 * (2 ** ((data[10] & 0x07) + 1))
        out = bytearray(data[:pos])
    while pos < len(data):
        b = data[pos]
        if b == 0x3B:
            out += data[pos:]
            break
        if b == 0x2C:  # image descriptor + LZW data: copy through
            start = pos
            pos += 10
            if data[start + 9] & 0x80:
                pos += 3 * (2 ** ((data[start + 9] & 0x07) + 1))
            pos = _gif_skip_subblocks(data, pos + 1)
            out += data[start:pos]
            continue
        if b == 0x21 and pos + 1 < len(data):
            label = data[pos + 1]
            end = _gif_skip_subblocks(data, pos + 2)
            if label == 0xFE:
                dropped.append("comment extension")
            elif label == 0xFF and b"XMP" in data[pos + 2:pos + 13]:
                dropped.append("XMP application extension")
            else:
                out += data[pos:end]
            pos = end
            continue
        out += data[pos:pos + 1]
        pos += 1
    return bytes(out), dropped


# ---------------------------------------------------------------------------
# TIFF — best-effort in-place zeroing
# ---------------------------------------------------------------------------

# Full TIFF IFD rewriting is fragile (offset chains, BigTIFF variants), so
# this implementation deliberately does a same-length byte neutralization
# instead: target-tag value bytes (and the data they point at) are zeroed in
# place. Structure and every other tag stay intact; the report labels this
# best-effort, not verifiable.
_TIFF_DROP_TAGS = {0x0131, 0x010E, 0x02BC, 0x8769, 0x8825}


def strip_tiff(data: bytes) -> tuple[bytes, list[str]]:
    buf = bytearray(data)
    dropped: list[str] = []
    if len(buf) < 8 or buf[:2] not in (b"II", b"MM"):
        return data, dropped
    endian = "little" if buf[:2] == b"II" else "big"
    magic = int.from_bytes(buf[2:4], endian)
    big = magic == 43
    if not big and magic != 42:
        return data, dropped
    ifd_off = int.from_bytes(buf[8:16] if big else buf[4:8], endian)
    if ifd_off + (8 if big else 2) > len(buf):
        return data, dropped
    n = int.from_bytes(buf[ifd_off:ifd_off + (8 if big else 2)], endian)
    entry_size, count_len = (20, 8) if big else (12, 4)
    entries_at = ifd_off + (8 if big else 2)
    for i in range(min(n, 512)):
        off = entries_at + i * entry_size
        if off + entry_size > len(buf):
            break
        tag = int.from_bytes(buf[off:off + 2], endian)
        if tag not in _TIFF_DROP_TAGS:
            continue
        count = int.from_bytes(buf[off + 4:off + 4 + count_len], endian)
        inline = 8 if big else 4
        val_field = off + 4 + count_len
        dropped.append(f"tag 0x{tag:04X}")
        if count <= inline:
            for k in range(val_field, val_field + count):
                if k < len(buf):
                    buf[k] = 0
        else:
            voff = int.from_bytes(buf[val_field:val_field + inline], endian)
            for k in range(voff, min(voff + count, len(buf))):
                buf[k] = 0
            for k in range(val_field, val_field + inline):
                if k < len(buf):
                    buf[k] = 0
    return bytes(buf), dropped


# ---------------------------------------------------------------------------
# SVG (targeted string surgery — visible content byte-identical)
# ---------------------------------------------------------------------------

def strip_svg(text: str) -> tuple[str, list[str]]:
    dropped: list[str] = []
    out, n = re.subn(r"<metadata\b.*?</metadata\s*>", "", text,
                     flags=re.I | re.S)
    if n:
        dropped.append(f"<metadata> ×{n}")
    out, n = re.subn(r"\s+[A-Za-z0-9_:.-]*generator\s*=\s*(\"[^\"]*\"|'[^']*')",
                     "", out, flags=re.I)
    if n:
        dropped.append(f"generator attribute ×{n}")
    return out, dropped


# ---------------------------------------------------------------------------
# DOCX / ODT (zip repack; untouched entries byte-for-byte)
# ---------------------------------------------------------------------------

_NEUTRAL_CORE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/'
    '2006/metadata/core-properties"/>'
)
_NEUTRAL_APP_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
    'extended-properties"/>'
)

_ODT_DROP_ELEMENTS = ("meta:generator", "meta:initial-creator", "dc:creator",
                      "meta:creation-date", "meta:printed-by")


def _repack_zip(data: bytes, drop_names: set[str], replacements: dict[str, bytes],
                drop_prefixes: tuple[str, ...] = ()) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            name = info.filename
            if name in drop_names or name.startswith(drop_prefixes):
                continue
            if name in replacements:
                out.writestr(info, replacements[name])
            else:
                out.writestr(info, src.read(name))
    return buf.getvalue()


def strip_docx(data: bytes) -> tuple[bytes, list[str]]:
    dropped = []
    replacements = {}
    names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    if "docProps/core.xml" in names:
        replacements["docProps/core.xml"] = _NEUTRAL_CORE_XML.encode()
        dropped.append("docProps/core.xml (neutralized)")
    if "docProps/app.xml" in names:
        replacements["docProps/app.xml"] = _NEUTRAL_APP_XML.encode()
        dropped.append("docProps/app.xml (neutralized)")
    drop = {"docProps/custom.xml"}
    if "docProps/custom.xml" in names:
        dropped.append("docProps/custom.xml")
    if any(n.startswith("customXml/") for n in names):
        dropped.append("customXml/*")
    out = _repack_zip(data, drop, replacements, ("customXml/",))
    return out, dropped


def strip_odt(data: bytes) -> tuple[bytes, list[str]]:
    src = zipfile.ZipFile(io.BytesIO(data))
    if "meta.xml" not in src.namelist():
        return data, []
    meta = src.read("meta.xml").decode("utf-8", "replace")
    dropped = []
    for el in _ODT_DROP_ELEMENTS:
        meta, n1 = re.subn(rf"<{el}\b[^>]*/>", "", meta)
        meta, n2 = re.subn(rf"<{el}\b[^>]*>.*?</{el}\s*>", "", meta,
                           flags=re.S)
        if n1 + n2:
            dropped.append(f"{el} ×{n1 + n2}")
    replacements = {"meta.xml": meta.encode("utf-8")} if dropped else {}
    out = _repack_zip(data, set(), replacements)
    return out, dropped


# ---------------------------------------------------------------------------
# PDF — exiftool+qpdf when available, else best-effort byte neutralization
# ---------------------------------------------------------------------------

_PDF_INFO_VALUE_RE = re.compile(
    rb"/(Producer|Creator|Title|Author|CreationDate|ModDate)\s*\(")


def strip_pdf(path: str, data: bytes, tmp_dir: str) -> tuple[bytes, list[str], str]:
    """Return (pdf_bytes, dropped, mode) where mode is verifiable|best-effort."""
    exiftool = shutil.which("exiftool")
    qpdf = shutil.which("qpdf")
    if exiftool and qpdf:
        tmp_in = os.path.join(tmp_dir, "in.pdf")
        with open(tmp_in, "wb") as fh:
            fh.write(data)
        subprocess.run([exiftool, "-all=", "-overwrite_original_in_place", tmp_in],
                       check=True, capture_output=True, timeout=60)
        tmp_out = os.path.join(tmp_dir, "out.pdf")
        subprocess.run([qpdf, "--linearize", tmp_in, tmp_out],
                       check=True, capture_output=True, timeout=120)
        with open(tmp_out, "rb") as fh:
            return fh.read(), ["all metadata (exiftool -all= + qpdf)"], "verifiable"

    # Best-effort: neutralize /Info literal-string values in place (same
    # length keeps all xref offsets valid) and blank XMP packet payloads.
    buf = bytearray(data)
    dropped: list[str] = []
    for m in _PDF_INFO_VALUE_RE.finditer(bytes(buf)):
        start = m.end()
        depth = 1
        i = start
        while i < len(buf) and depth:
            if buf[i] == 0x28 and buf[i - 1] != 0x5C:
                depth += 1
            elif buf[i] == 0x29 and buf[i - 1] != 0x5C:
                depth -= 1
                if depth == 0:
                    break
            i += 1
        for k in range(start, min(i, len(buf))):
            if buf[k] not in (0x5C,):
                buf[k] = 0x20  # space, same length
        dropped.append(f"/{m.group(1).decode()} (value blanked in place)")
    xs = data.find(b"<?xpacket")
    if xs != -1:
        xe = data.find(b"<?xpacket end", xs)
        end = xe if xe != -1 else min(xs + 65536, len(buf))
        for k in range(xs, end):
            if 0x20 <= buf[k] < 0x7F:
                buf[k] = 0x20
        dropped.append("XMP packet (blanked)")
    return bytes(buf), dropped, "best-effort"


# ---------------------------------------------------------------------------
# HTML / markdown (string surgery — visible content byte-identical)
# ---------------------------------------------------------------------------

def strip_html(text: str) -> tuple[str, list[str]]:
    dropped: list[str] = []
    out, n = re.subn(
        r"<meta\b[^>]*name\s*=\s*[\"']generator[\"'][^>]*>", "", text,
        flags=re.I)
    if n:
        dropped.append(f"<meta generator> ×{n}")
    out, n = re.subn(r"\s+data-ai[\w-]*\s*=\s*(\"[^\"]*\"|'[^']*')", "", out,
                     flags=re.I)
    if n:
        dropped.append(f"data-ai* attribute ×{n}")
    return out, dropped


_FRONTMATTER_KEYS = ("generator", "model", "ai", "claude", "gpt", "llm")


def strip_markdown(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, []
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return text, []
    dropped: list[str] = []
    kept: list[str] = []
    for i in range(1, end):
        line = lines[i]
        key = re.match(r"^([A-Za-z0-9_.-]+)\s*:", line)
        if key:
            k = key.group(1).lower()
            if any(k == f or k.startswith(f + "-") or k.startswith(f + "_")
                   for f in _FRONTMATTER_KEYS):
                dropped.append(k)
                continue
        kept.append(line)
    # Body lines are appended byte-for-byte from the original list.
    out = lines[0] + "".join(kept) + lines[end] + "".join(lines[end + 1:])
    return out, dropped


# ---------------------------------------------------------------------------
# Core removal driver
# ---------------------------------------------------------------------------

def _plan_lines(before: Report, target: str, container: str,
                will_drop: list[str], mode: str) -> list[str]:
    plan = [f"Plan for {target} (detected container: {container}):"]
    plan.append(f"  audit findings before cleaning: {len(before.findings)}")
    for f in before.findings:
        plan.append(f"    - [{f.severity}] {f.evidence} @ {f.location}")
    if will_drop:
        plan.append("  will remove: " + "; ".join(will_drop))
    else:
        plan.append("  nothing removable detected for this format")
    plan.append(f"  removal mode: {mode}")
    plan.append(f"  caveat: {NOT_ADDRESSABLE_NOTE}")
    return plan


def run(input_path: str, output_arg: str | None, *, force: bool,
        assume_yes: bool, as_json: bool, max_bytes: int) -> int:
    print_ownership_reminder()

    with open(input_path, "rb") as fh:
        raw = fh.read(max_bytes + 1)
    if len(raw) > max_bytes:
        print(f"Refusing: input exceeds --max-bytes ({max_bytes}); cleaning a "
              "truncated file could corrupt the container. Raise the cap.",
              file=sys.stderr)
        return 1
    data = raw[:max_bytes]

    container = detect_container(data)
    if container == "epub":
        print(f"{input_path}: {EPUB_REFUSAL}", file=sys.stderr)
        return 1
    if container == "unknown-binary":
        print(f"Refusing: unrecognized binary format: {input_path}",
              file=sys.stderr)
        return 1
    if container == "pdf" and not (shutil.which("exiftool") and shutil.which("qpdf")):
        mode = "best-effort (qpdf/exiftool absent)"
    elif container == "tiff":
        mode = "best-effort (in-place tag-value zeroing)"
    else:
        mode = "verifiable"

    before = audit_file(input_path, max_bytes=max_bytes)

    import tempfile
    with tempfile.TemporaryDirectory(prefix="i-tipp-ex-clean-") as tmp:
        new_bytes: bytes | str
        dropped: list[str]
        if container == "png":
            new_bytes, dropped = strip_png(data)
        elif container == "jpeg":
            new_bytes, dropped = strip_jpeg(data)
        elif container == "webp":
            new_bytes, dropped = strip_webp(data)
        elif container == "gif":
            new_bytes, dropped = strip_gif(data)
        elif container == "tiff":
            new_bytes, dropped = strip_tiff(data)
        elif container == "svg":
            new_bytes, dropped = strip_svg(
                data.decode("utf-8", "replace"))
        elif container == "docx":
            new_bytes, dropped = strip_docx(data)
        elif container == "odt":
            new_bytes, dropped = strip_odt(data)
        elif container == "pdf":
            new_bytes, dropped, mode = strip_pdf(input_path, data, tmp)
        elif container == "html":
            new_bytes, dropped = strip_html(data.decode("utf-8", "replace"))
        elif container == "markdown":
            new_bytes, dropped = strip_markdown(
                data.decode("utf-8", "replace"))
        elif container == "text":
            cleaned, counts = clean_text.clean_text_content(
                data.decode("utf-8", "replace"))
            new_bytes = cleaned
            dropped = [f"U+{cp:04X} ×{n}" for cp, n in sorted(counts.items())]
        else:
            print(f"Refusing: unsupported container {container}: {input_path}",
                  file=sys.stderr)
            return 1

        confirm_or_abort(_plan_lines(before, input_path, container, dropped,
                                     mode), assume_yes)

        out_path = resolve_output(input_path, output_arg, force)
        if out_path is None:
            print("Refusing: clean_file requires a file output path "
                  "(stdin/stdout mode is not supported).", file=sys.stderr)
            return 1
        payload = new_bytes.encode("utf-8") if isinstance(new_bytes, str) \
            else new_bytes
        atomic_write(out_path, payload)

        after = audit_file(out_path, max_bytes=max_bytes)

    report = Report(target=f"{input_path} -> {out_path}")
    for d in dropped:
        report.add_note(f"[{mode}] removed: {d}")
    for f in after.findings:
        report.add_finding(f)
    report.add_note(NOT_ADDRESSABLE_NOTE)
    if container == "pdf" and mode.startswith("best-effort"):
        report.add_note(PDF_TOOLS_NOTE)
    # before/after summary: removed = findings that disappeared; remaining =
    # findings still present in the output; not addressable = watermark classes.
    before_keys = {(f.category, f.evidence) for f in before.findings}
    after_keys = {(f.category, f.evidence) for f in after.findings}
    removed_n = len(before_keys - after_keys)
    remaining_n = len(after_keys)
    report.add_note(f"removed: {removed_n} ({mode.split(' ')[0]}); "
                    f"remaining: {remaining_n}; "
                    "not addressable: pixel-domain and statistical "
                    "watermark classes (never addressable by stripping).")
    print(report.render_json() if as_json else report.render_human())
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="i-tipp-ex removal mode: strip provenance metadata from a "
                    "container file. Never in-place; audit scripts never call this.")
    parser.add_argument("file", help="file to clean")
    parser.add_argument("-o", "--output", metavar="PATH",
                        help="cleaned output path (default: "
                             "<name>.cleaned.<ext>)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing output path")
    parser.add_argument("--yes", action="store_true",
                        help="skip the interactive confirmation")
    parser.add_argument("--json", action="store_true",
                        help="emit the removal report as JSON")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)
    return run(args.file, args.output, force=args.force, assume_yes=args.yes,
               as_json=args.json, max_bytes=args.max_bytes)


if __name__ == "__main__":
    sys.exit(main())
