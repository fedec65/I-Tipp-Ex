"""Layer A/B/C acceptance tests: detection, routing, schema, watermarks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fixtures")
sys.path.insert(0, SCRIPTS)

import audit_text  # noqa: E402
import audit_file  # noqa: E402
from report import STATISTICAL_WATERMARK_NOTE  # noqa: E402

ZERO_WIDTH = os.path.join(FIXTURES, "text", "zero_width.md")
LEGIT = os.path.join(FIXTURES, "text", "legit_emoji.md")
C2PA_PNG = os.path.join(FIXTURES, "img", "c2pa.png")
CLEAN_PNG = os.path.join(FIXTURES, "img", "clean.png")
DOCX = os.path.join(FIXTURES, "doc", "ai_props.docx")
HTML = os.path.join(FIXTURES, "web", "generator.html")


class ZeroWidthTests(unittest.TestCase):
    def test_zero_width_counts(self):
        """Seeded codepoints appear with exact counts and line:col."""
        with open(ZERO_WIDTH, encoding="utf-8") as fh:
            text = fh.read()
        findings = audit_text.scan_text(text)

        def agg(evidence_prefix):
            return [f for f in findings
                    if f.evidence.startswith(evidence_prefix)]

        zwsp = agg("U+200B")
        self.assertEqual(len(zwsp), 1)
        self.assertEqual(zwsp[0].severity, "medium")
        self.assertIn("×3", zwsp[0].evidence)
        locs = zwsp[0].note
        self.assertIn("line 2, col 5", locs)
        self.assertIn("line 2, col 11", locs)
        self.assertIn("line 2, col 16", locs)

        shy = agg("U+00AD")
        self.assertEqual(len(shy), 1)
        self.assertEqual(shy[0].severity, "low")  # soft hyphen never above low
        self.assertIn("×2", shy[0].evidence)
        self.assertIn("line 3, col 5", shy[0].note)
        self.assertIn("line 3, col 8", shy[0].note)

        rlo = [f for f in findings if f.evidence.startswith("U+202E")]
        self.assertEqual(len(rlo), 1)
        self.assertEqual(rlo[0].severity, "high")
        self.assertEqual(rlo[0].category, "bidi-override")
        self.assertEqual(rlo[0].location, "line 4, col 7")
        pdf = [f for f in findings if f.evidence.startswith("U+202C")]
        self.assertEqual(pdf[0].location, "line 4, col 16")

        nbsp = agg("U+00A0")
        self.assertEqual(len(nbsp), 1)
        self.assertEqual(nbsp[0].severity, "low")
        self.assertIn("line 5, col 5", nbsp[0].note)
        self.assertIn("line 5, col 15", nbsp[0].note)

        bom = agg("U+FEFF")
        self.assertEqual(len(bom), 1)
        self.assertEqual(bom[0].location, "line 6, col 10")

    def test_legit_emoji_no_findings(self):
        """Emoji/Indic/Arabic contexts downgrade to informational at most."""
        with open(LEGIT, encoding="utf-8") as fh:
            text = fh.read()
        findings = audit_text.scan_text(text)
        bad = [(f.severity, f.evidence) for f in findings
               if f.severity in ("high", "medium", "low")]
        self.assertEqual(bad, [], "legitimate typography must not be flagged")


class RoutingTests(unittest.TestCase):
    def test_magic_byte_routing(self):
        """A PNG renamed to .txt still audits as PNG with caBX finding."""
        with tempfile.TemporaryDirectory() as tmp:
            mystery = os.path.join(tmp, "mystery.txt")
            with open(C2PA_PNG, "rb") as src, open(mystery, "wb") as dst:
                dst.write(src.read())
            self.assertEqual(audit_file.detect_container(mystery), "png")
            report = audit_file.audit_file(mystery)
            self.assertTrue(any(f.category == "c2pa-manifest"
                                for f in report.findings))


class C2PATests(unittest.TestCase):
    def test_c2pa_detection(self):
        """caBX chunk -> c2pa-manifest + absent-tool note; clean.png quiet."""
        report = audit_file.audit_file(C2PA_PNG)
        c2pa = [f for f in report.findings if f.category == "c2pa-manifest"]
        self.assertEqual(len(c2pa), 1)
        self.assertTrue(any("c2patool not found" in n for n in report.notes))

        clean = audit_file.audit_file(CLEAN_PNG)
        self.assertEqual(clean.findings, [])

    def test_c2patool_error_means_absent(self):
        """A fake failing c2patool must REMOVE the finding, never confirm."""
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "c2patool")
            with open(fake, "w") as fh:
                fh.write('#!/bin/sh\necho "Error: No claim found"\nexit 1\n')
            os.chmod(fake, 0o755)
            env = dict(os.environ)
            env["PATH"] = tmp + os.pathsep + env.get("PATH", "")
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, %r);" % SCRIPTS +
                 "from audit_file import audit_file;"
                 "import json;"
                 "r = audit_file(%r);"
                 "print(json.dumps({'cats': [f.category for f in r.findings],"
                 "'notes': r.notes}))" % C2PA_PNG],
                capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertNotIn("c2pa-manifest", out["cats"])
            self.assertTrue(any("c2patool reported no claim" in n
                                for n in out["notes"]))


class SchemaTests(unittest.TestCase):
    ENVELOPE_KEYS = {"tool", "version", "target", "notes", "summary", "findings"}
    FINDING_KEYS = {"severity", "confidence", "category", "location",
                    "evidence", "context", "note"}
    SEVS = {"high", "medium", "low", "informational"}
    CONFS = {"confirmed", "probable", "informational", "likely_false_positive"}
    CATS = {"invisible-unicode", "bidi-override", "c2pa-manifest",
            "ai-metadata", "generator-meta", "homoglyph"}

    def _check(self, doc):
        # Envelope keys are a required subset; container reports (e.g. the
        # directory report) legitimately add keys like "files".
        self.assertTrue(self.ENVELOPE_KEYS <= set(doc),
                        f"missing envelope keys: {self.ENVELOPE_KEYS - set(doc)}")
        self.assertEqual(doc["tool"], "i-tipp-ex")
        self.assertEqual(doc["version"], "1.1.0")
        self.assertIn("total", doc["summary"])
        for f in doc["findings"]:
            self.assertEqual(set(f), self.FINDING_KEYS)
            self.assertIn(f["severity"], self.SEVS)
            self.assertIn(f["confidence"], self.CONFS)
            self.assertIn(f["category"], self.CATS)

    def _cli_json(self, script, *args):
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, script), "--json", *args],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_json_schema(self):
        self._check(self._cli_json("audit_text.py", ZERO_WIDTH))
        self._check(self._cli_json("audit_file.py", C2PA_PNG))
        self._check(self._cli_json("audit_file.py", DOCX))
        self._check(self._cli_json("audit_dir.py", FIXTURES))
        # audit_site schema (CLI is gated; validate via the importable API
        # against a locally served copy in test_site.py — here the envelope).
        from report import Report
        self._check(Report(target="x").to_json_dict())

    def test_audit_reports_have_no_verdicts(self):
        """Audit scripts never emit vendor verdicts in their JSON."""
        for script, target in (("audit_text.py", ZERO_WIDTH),
                               ("audit_file.py", C2PA_PNG),
                               ("audit_file.py", DOCX),
                               ("audit_file.py", HTML)):
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, script),
                 "--json", target], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr[:300])
            self.assertNotIn("verdicts", json.loads(proc.stdout))

    def test_watermark_note(self):
        """Text-scanning reports carry the SynthID standing note."""
        out = self._cli_json("audit_text.py", ZERO_WIDTH)
        self.assertIn(STATISTICAL_WATERMARK_NOTE, out["notes"])
        html = self._cli_json("audit_file.py", HTML)
        self.assertIn(STATISTICAL_WATERMARK_NOTE, html["notes"])
        png = self._cli_json("audit_file.py", C2PA_PNG)  # no text scanned
        self.assertNotIn(STATISTICAL_WATERMARK_NOTE, png["notes"])


if __name__ == "__main__":
    unittest.main()
