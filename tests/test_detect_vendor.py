"""Vendor-verdict detection: report model, CLI guards, mocked backends."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)

import report as report_mod  # noqa: E402
from report import Report, Verdict, VERDICT_DETECTORS  # noqa: E402


class VerdictModelTests(unittest.TestCase):
    def test_verdict_to_dict_shape(self):
        v = Verdict(detector="gemini-synthid-text", available=True,
                    is_watermarked=True, score=4.3, threshold=3.0,
                    scope_note="vendor verdict — not independently verifiable")
        d = v.to_dict()
        self.assertEqual(
            set(d),
            {"detector", "available", "is_watermarked", "score",
             "threshold", "scope_note", "error"},
        )
        self.assertIn(v.detector, VERDICT_DETECTORS)

    def test_bad_detector_rejected(self):
        with self.assertRaises(ValueError):
            Verdict(detector="openai-magic", available=True)

    def test_verdicts_omitted_when_empty(self):
        r = Report(target="x")
        self.assertNotIn("verdicts", r.to_json_dict())
        self.assertNotIn("Vendor verdicts", r.render_human())

    def test_verdicts_rendered_when_present(self):
        r = Report(target="x")
        r.add_verdict(Verdict(detector="markllm-kgw", available=False,
                              error="ITIPPEX_MARKLLM_DIR not set"))
        d = r.to_json_dict()
        self.assertEqual(len(d["verdicts"]), 1)
        self.assertEqual(d["summary"]["total"], 0)  # verdicts are not findings
        human = r.render_human()
        self.assertIn("Vendor verdicts (not independently verifiable)", human)
        self.assertIn("markllm-kgw", human)
        self.assertIn("0 findings", human)


class CliGuardTests(unittest.TestCase):
    SCRIPT = os.path.join(SCRIPTS, "detect_vendor.py")

    def run_cli(self, args, stdin_text=None, env_extra=None):
        env = dict(os.environ)
        env.pop("ITIPPEX_GEMINI_API_KEY", None)
        env.pop("ITIPPEX_MARKLLM_DIR", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, self.SCRIPT, *args],
            input=stdin_text, capture_output=True, text=True, env=env,
        )

    def test_requires_backend(self):
        proc = self.run_cli([], stdin_text="hello")
        self.assertEqual(proc.returncode, 2)

    def test_refuses_binary(self):
        png = os.path.join(SCRIPTS, "..", "assets", "fixtures", "img", "clean.png")
        proc = self.run_cli(["--backend", "gemini", png])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("audit_file.py", proc.stderr)

    def test_unconfigured_backends_are_unavailable_not_fatal(self):
        proc = self.run_cli(["--backend", "all", "-"], stdin_text="some prose " * 50)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("unavailable", proc.stdout)
        self.assertIn("Vendor verdicts", proc.stdout)

    def test_json_schema(self):
        proc = self.run_cli(["--backend", "all", "--json", "-"],
                            stdin_text="some prose " * 50)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        d = json.loads(proc.stdout)
        self.assertEqual(d["summary"]["total"], 0)
        self.assertEqual(len(d["verdicts"]), 2)
        for v in d["verdicts"]:
            self.assertEqual(
                set(v),
                {"detector", "available", "is_watermarked", "score",
                 "threshold", "scope_note", "error"},
            )

    def test_oversize_refused_without_allow_large(self):
        big = "x" * (1024 * 1024 + 10)
        proc = self.run_cli(["--backend", "gemini", "-"], stdin_text=big)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--allow-large", proc.stderr)
