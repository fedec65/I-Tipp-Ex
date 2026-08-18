"""Layer D acceptance tests: local threaded server, coverage, gate."""

from __future__ import annotations

import functools
import http.server
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fixtures")
sys.path.insert(0, SCRIPTS)

import audit_site  # noqa: E402

SITE_SRC = os.path.join(FIXTURES, "site")


class _LoggedHandler(http.server.SimpleHTTPRequestHandler):
    """Records requested paths so tests can prove /private/ was never asked."""

    seen: list[str] = []

    def log_message(self, fmt, *args):  # silence
        pass

    def do_GET(self):
        type(self).seen.append(self.path)
        super().do_GET()

    @classmethod
    def reset(cls):
        cls.seen = []


class SiteServer:
    def __init__(self, directory: str):
        handler = functools.partial(
            _LoggedHandler, directory=directory)
        self.httpd = None
        last_err = None
        for _ in range(10):  # retry port binding on ephemeral ports
            try:
                self.httpd = http.server.ThreadingHTTPServer(
                    ("127.0.0.1", 0), handler)
                break
            except OSError as e:
                last_err = e
        if self.httpd is None:
            raise RuntimeError(f"could not bind a local port: {last_err}")
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _materialize_site(tmp: str) -> str:
    """Copy the committed site into tmp; the caller rewrites the sitemap port
    once the server port is known."""
    dst = os.path.join(tmp, "site")
    shutil.copytree(SITE_SRC, dst)
    return dst


class SiteAuditTests(unittest.TestCase):
    def setUp(self):
        _LoggedHandler.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.site = _materialize_site(self.tmp.name)
        self.server = SiteServer(self.site)
        self.server.start()
        # Rewrite the sitemap placeholder port now that the real one is known.
        path = os.path.join(self.site, "sitemap.xml")
        with open(path, encoding="utf-8") as fh:
            data = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data.replace("127.0.0.1:8471", f"127.0.0.1:{self.server.port}"))
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()
        self.tmp.cleanup()

    def _audit(self, **overrides):
        kwargs = dict(max_pages=200, max_assets=100, include_assets=False,
                      delay=0, timeout=10, max_resource_bytes=1 << 20)
        kwargs.update(overrides)
        return audit_site.audit_site(self.base, **kwargs)

    def test_site_audit(self):
        report = self._audit()
        self.assertEqual(report.coverage["audited"], 3)
        self.assertEqual(report.coverage["skipped"], 1)  # robots: /private/
        self.assertEqual(report.coverage["discovered"], 4)
        self.assertEqual(report.coverage_line(),
                         "Audited 3 of 4 sitemap URLs "
                         "(capped: 0, timeouts: 0, skipped: 1)")
        # /private/secret.html was never requested
        self.assertNotIn("/private/secret.html", _LoggedHandler.seen)
        # findings: index (U+200B x2 layers + data-ai), page3 (CMS)
        idx = [r for r in report.pages if r.target.endswith("/index.html")]
        self.assertEqual(len(idx), 1)
        self.assertTrue(any(f.category == "ai-metadata" and "data-ai" in f.evidence
                            for f in idx[0].findings))
        self.assertTrue(any(f.evidence.startswith("U+200B")
                            for f in idx[0].findings))
        page3 = [r for r in report.pages if r.target.endswith("/page3.html")]
        self.assertTrue(any(f.category == "generator-meta"
                            for f in page3[0].findings))
        page2 = [r for r in report.pages if r.target.endswith("/page2.html")]
        self.assertEqual(page2[0].findings, [])
        # watermark note appears on site-level report (text was scanned)
        self.assertIn("SynthID", " ".join(report.notes))

        # --max-pages 2 equivalent: honest capping
        capped = self._audit(max_pages=2)
        self.assertEqual(capped.coverage["audited"], 2)
        self.assertEqual(capped.coverage["capped"], 1)
        self.assertEqual(capped.coverage["skipped"], 1)

    def test_site_include_assets(self):
        report = self._audit(include_assets=True)
        assets = {a.target.rsplit("/", 1)[-1]: a for a in report.assets}
        self.assertIn("ai.png", assets)
        self.assertTrue(any(f.category == "generator-meta"
                            for f in assets["ai.png"].findings))

    def test_gate_requires_authorization(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "audit_site.py"), self.base],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--i-am-authorized", proc.stderr)

    def test_robots_sitemap_directive_discovery(self):
        # Rebuild the copy so ONLY the robots directive reveals the sitemap.
        with open(os.path.join(SITE_SRC, "sitemap.xml"), encoding="utf-8") as fh:
            data = fh.read()
        port = self.server.port
        with open(os.path.join(self.site, "sitemap.xml"), "w",
                  encoding="utf-8") as fh:
            fh.write(data.replace("127.0.0.1:8471", f"127.0.0.1:{port}"))
        robots = os.path.join(self.site, "robots.txt")
        with open(robots, "w") as fh:
            fh.write(f"User-agent: *\nDisallow: /private/\n\n"
                     f"Sitemap: http://127.0.0.1:{port}/other-map.xml\n")
        with open(os.path.join(self.site, "other-map.xml"), "w",
                  encoding="utf-8") as fh:
            fh.write(data.replace("127.0.0.1:8471", f"127.0.0.1:{port}"))
        os.remove(os.path.join(self.site, "sitemap.xml"))
        report = self._audit()
        self.assertEqual(report.coverage["audited"], 3)


if __name__ == "__main__":
    unittest.main()
