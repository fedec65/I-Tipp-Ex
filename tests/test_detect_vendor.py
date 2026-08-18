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
