"""Removal-mode acceptance tests (clean_text / clean_file)."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fixtures")
sys.path.insert(0, SCRIPTS)

import audit_text  # noqa: E402
import audit_file  # noqa: E402
import clean_text  # noqa: E402
import clean_file  # noqa: E402

ZERO_WIDTH = os.path.join(FIXTURES, "text", "zero_width.md")
C2PA_PNG = os.path.join(FIXTURES, "img", "c2pa.png")
DOCX = os.path.join(FIXTURES, "doc", "ai_props.docx")
HTML = os.path.join(FIXTURES, "web", "generator.html")
LEGIT = os.path.join(FIXTURES, "text", "legit_emoji.md")


def md5(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


class CleanTextTests(unittest.TestCase):
    def test_clean_text(self):
        with open(ZERO_WIDTH, encoding="utf-8") as fh:
            original = fh.read()
        cleaned, removed = clean_text.clean_text_content(original)
        # NBSP -> regular space (not deleted)
        self.assertIn("nbsp here", cleaned)
        self.assertIn("nbsp too", cleaned)
        self.assertNotIn("\u00a0", cleaned)
        # everything else flagged is deleted
        for cp in ("\u200b", "\u00ad", "\u202e", "\u202c", "\ufeff"):
            self.assertNotIn(cp, cleaned)
        # re-audit: zero high/medium/low (informational allowed)
        after = [f for f in audit_text.scan_text(cleaned)
                 if f.severity != "informational"]
        self.assertEqual(after, [])
        # input untouched is asserted at CLI level below
        self.assertEqual(removed.get(0x00A0), 2)
        self.assertEqual(removed.get(0x200B), 3)

    def test_clean_text_cli_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "zw.md")
            shutil.copy(ZERO_WIDTH, src)
            before = md5(src)
            out = os.path.join(tmp, "zw.cleaned.md")
            # non-interactive without --yes -> abort
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_text.py"),
                 src, "-o", out], stdin=subprocess.DEVNULL,
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertFalse(os.path.exists(out))
            # --yes writes; original untouched
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_text.py"),
                 src, "-o", out, "--yes"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(md5(src), before)
            # existing output refused without --force
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_text.py"),
                 src, "-o", out, "--yes"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("already exists", p.stderr)
            # no temp files left behind
            leftovers = [n for n in os.listdir(tmp) if n.startswith(".i-tipp-ex-")]
            self.assertEqual(leftovers, [])
            # emoji fixture round-trip: ZWJ sequences byte-preserved
            leg_src = os.path.join(tmp, "legit.md")
            shutil.copy(LEGIT, leg_src)
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_text.py"),
                 leg_src, "--yes"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(os.path.join(tmp, "legit.cleaned.md"),
                      encoding="utf-8") as fh:
                cleaned = fh.read()
            with open(LEGIT, encoding="utf-8") as fh:
                original = fh.read()
            self.assertEqual(cleaned, original)  # nothing legitimately removable


class CleanFileTests(unittest.TestCase):
    def test_clean_file_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "c2pa.png")
            shutil.copy(C2PA_PNG, src)
            before = md5(src)
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_file.py"),
                 src, "--yes"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            out = os.path.join(tmp, "c2pa.cleaned.png")
            self.assertTrue(os.path.exists(out))
            self.assertEqual(md5(src), before)
            after = audit_file.audit_file(out)
            self.assertEqual([f for f in after.findings
                              if f.category == "c2pa-manifest"], [])

    def test_clean_file_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "ai.docx")
            shutil.copy(DOCX, src)
            before = md5(src)
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_file.py"),
                 src, "--yes"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(md5(src), before)
            after = audit_file.audit_file(os.path.join(tmp, "ai.cleaned.docx"))
            self.assertEqual(after.findings, [])  # core/app/custom all neutral

    def test_clean_file_html_preserves_visible_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "page.html")
            shutil.copy(HTML, src)
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_file.py"),
                 src, "--yes"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            out = os.path.join(tmp, "page.cleaned.html")
            with open(out, encoding="utf-8") as fh:
                cleaned = fh.read()
            self.assertIn("Hello world", cleaned)
            self.assertIn("tagged", cleaned)
            self.assertNotIn("data-ai", cleaned)
            self.assertNotIn("generator", cleaned)

    def test_clean_file_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "c2pa.png")
            shutil.copy(C2PA_PNG, src)
            # symlink destination refused
            link = os.path.join(tmp, "link.png")
            os.symlink(os.path.join(tmp, "elsewhere.png"), link)
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_file.py"),
                 src, "-o", link, "--yes"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("symlink", p.stderr)
            # in-place refused
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_file.py"),
                 src, "-o", src, "--yes"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("in-place", p.stderr.lower())
            # ownership reminder always printed (even with --yes)
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "clean_file.py"),
                 src, "--yes"], capture_output=True, text=True)
            self.assertTrue(p.stderr.startswith(
                "Intended for content you own"), p.stderr[:80])


if __name__ == "__main__":
    unittest.main()
