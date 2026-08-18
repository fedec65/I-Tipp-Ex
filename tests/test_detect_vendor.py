"""Vendor-verdict detection: report model, CLI guards, mocked backends."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)

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

    def test_caveats_travel_with_verdicts_in_json(self):
        """The fixed caveats must appear in machine-readable output too —
        vendor-verdicts.md promises them with every run."""
        from report import VENDOR_VERDICT_CAVEATS
        r = Report(target="x")
        r.add_verdict(Verdict(detector="markllm-kgw", available=False,
                              error="ITIPPEX_MARKLLM_DIR not set"))
        self.assertEqual(r.to_json_dict()["caveats"],
                         list(VENDOR_VERDICT_CAVEATS))
        self.assertNotIn("caveats", Report(target="x").to_json_dict())

    def test_score_only_verdict_renders_score(self):
        """A verdict with a score but no is_watermarked must still show the
        score next to 'no verdict'."""
        r = Report(target="x")
        r.add_verdict(Verdict(detector="gemini-synthid-text", available=True,
                              is_watermarked=None, score=0.51,
                              scope_note="vendor verdict"))
        human = r.render_human()
        self.assertIn("no verdict (score 0.51)", human)

    def test_scoreless_no_verdict_line_unchanged(self):
        r = Report(target="x")
        r.add_verdict(Verdict(detector="gemini-synthid-text", available=True,
                              is_watermarked=None))
        self.assertIn("- gemini-synthid-text: no verdict\n",
                      r.render_human())


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

    def test_allow_large_truncation_is_noted(self):
        """Input beyond --max-bytes with --allow-large is cut to the cap and
        the report must say the verdict covers only part of the input."""
        proc = self.run_cli(
            ["--backend", "gemini", "--json", "--max-bytes", "100",
             "--allow-large", "-"], stdin_text="y" * 200)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        d = json.loads(proc.stdout)
        self.assertTrue(any("truncated" in n.lower() for n in d["notes"]))


class GeminiBackendTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ITIPPEX_GEMINI_API_KEY", None)

    def tearDown(self):
        os.environ.pop("ITIPPEX_GEMINI_API_KEY", None)

    def test_unconfigured(self):
        import detect_vendor
        v = detect_vendor.gemini_verdict("hello", 5)
        self.assertFalse(v.available)
        self.assertIn("ITIPPEX_GEMINI_API_KEY", v.error)

    def test_detected(self):
        import detect_vendor
        os.environ["ITIPPEX_GEMINI_API_KEY"] = "fake-key"
        def fake_post(url, payload, headers, timeout):
            self.assertNotIn("fake-key", url)  # key goes in headers, not URL
            return {"watermarkDetected": True}
        v = detect_vendor.gemini_verdict("hello", 5, _post=fake_post)
        self.assertTrue(v.available)
        self.assertTrue(v.is_watermarked)

    def test_http_error_fail_soft(self):
        import detect_vendor
        os.environ["ITIPPEX_GEMINI_API_KEY"] = "fake-key"
        def boom(url, payload, headers, timeout):
            raise OSError("connection refused")
        v = detect_vendor.gemini_verdict("hello", 5, _post=boom)
        self.assertFalse(v.available)
        self.assertIn("connection refused", v.error)

    def test_malformed_response_fail_soft(self):
        import detect_vendor
        os.environ["ITIPPEX_GEMINI_API_KEY"] = "fake-key"
        v = detect_vendor.gemini_verdict("hello", 5,
                                         _post=lambda *a: {"unexpected": 1})
        self.assertFalse(v.available)
        self.assertIsNotNone(v.error)

    @staticmethod
    def _verdict_post(text):
        def _post(url, payload, headers, timeout):
            return {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        return _post

    def test_unrecognized_verdict_text_fail_soft(self):
        import detect_vendor
        os.environ["ITIPPEX_GEMINI_API_KEY"] = "fake-key"
        for text in ("Cannot determine", "Analysis unavailable"):
            with self.subTest(text=text):
                v = detect_vendor.gemini_verdict(
                    "hello", 5, _post=self._verdict_post(text))
                self.assertFalse(v.available, text)
                self.assertIsNotNone(v.error)

    def test_negated_sentence_verdict_is_recognized_negative(self):
        import detect_vendor
        os.environ["ITIPPEX_GEMINI_API_KEY"] = "fake-key"
        v = detect_vendor.gemini_verdict(
            "hello", 5, _post=self._verdict_post("The text is not AI-generated"))
        self.assertTrue(v.available)
        self.assertFalse(v.is_watermarked)

    def test_prior_sentence_negation_does_not_flip_affirmative(self):
        """Negation in an earlier sentence must not negate the marker's own
        clause (Devin review #1)."""
        import detect_vendor
        os.environ["ITIPPEX_GEMINI_API_KEY"] = "fake-key"
        v = detect_vendor.gemini_verdict(
            "hello", 5, _post=self._verdict_post(
                "The text shows no unusual formatting. It is watermarked."))
        self.assertTrue(v.available)
        self.assertTrue(v.is_watermarked)

    def test_uncertain_reply_is_unavailable_not_negative(self):
        """"I cannot determine..." must fail soft to unavailable (ValueError
        path), never render as a confident negative (Devin review #1)."""
        import detect_vendor
        os.environ["ITIPPEX_GEMINI_API_KEY"] = "fake-key"
        v = detect_vendor.gemini_verdict(
            "hello", 5, _post=self._verdict_post(
                "I cannot determine whether this text is AI-generated"))
        self.assertFalse(v.available)
        self.assertIsNotNone(v.error)

    def test_invalid_model_env_fail_soft(self):
        """A model name with path characters must be rejected before it
        reaches the request URL (Devin review #4)."""
        import detect_vendor
        os.environ["ITIPPEX_GEMINI_API_KEY"] = "fake-key"
        os.environ["ITIPPEX_GEMINI_MODEL"] = "../other-path"
        try:
            def _post(url, payload, headers, timeout):
                raise AssertionError(f"request went out to {url}")
            v = detect_vendor.gemini_verdict("hello", 5, _post=_post)
        finally:
            os.environ.pop("ITIPPEX_GEMINI_MODEL", None)
        self.assertFalse(v.available)
        self.assertIn("invalid", v.error)

    def test_score_without_verdict_text_is_no_guess(self):
        """A numeric score with no verdict text must not be thresholded into
        a boolean — Google's score scale is undocumented, so is_watermarked
        stays None while the score is reported."""
        import detect_vendor
        os.environ["ITIPPEX_GEMINI_API_KEY"] = "fake-key"
        def _post(url, payload, headers, timeout):
            return {"candidates": [
                {"content": {"parts": [{"text": ""}]}, "score": 0.51}]}
        v = detect_vendor.gemini_verdict("hello", 5, _post=_post)
        self.assertTrue(v.available)
        self.assertIsNone(v.is_watermarked)
        self.assertEqual(v.score, 0.51)


class MarkLLMBackendTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ITIPPEX_MARKLLM_DIR", None)

    def tearDown(self):
        os.environ.pop("ITIPPEX_MARKLLM_DIR", None)

    def _make_stub_dir(self, payload: str, exit_code: int = 0) -> str:
        import tempfile, stat
        d = tempfile.mkdtemp()
        bindir = os.path.join(d, ".venv", "bin")
        os.makedirs(bindir)
        adapter_target = os.path.join(d, "fake_adapter.py")
        with open(adapter_target, "w") as fh:
            fh.write(f"import sys; print({payload!r}); sys.exit({exit_code})\n")
        # detect_vendor calls <dir>/.venv/bin/python <adapter> ... — make a
        # wrapper that routes to the real interpreter and our fake adapter.
        wrapper = os.path.join(bindir, "python")
        with open(wrapper, "w") as fh:
            fh.write(f"#!/bin/sh\nexec {sys.executable} {adapter_target}\n")
        os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IEXEC)
        return d

    def test_unconfigured(self):
        import detect_vendor
        v = detect_vendor.markllm_verdict("hello", "kgw", 5)
        self.assertFalse(v.available)
        self.assertIn("ITIPPEX_MARKLLM_DIR", v.error)

    def test_detected_true(self):
        import detect_vendor, json as _json
        payload = _json.dumps({"score": 4.3, "threshold": 3.0,
                               "is_watermarked": True})
        os.environ["ITIPPEX_MARKLLM_DIR"] = self._make_stub_dir(payload)
        v = detect_vendor.markllm_verdict("hello", "kgw", 5)
        self.assertTrue(v.available)
        self.assertTrue(v.is_watermarked)
        self.assertEqual(v.score, 4.3)
        self.assertEqual(v.detector, "markllm-kgw")

    def test_crash_fail_soft(self):
        import detect_vendor
        os.environ["ITIPPEX_MARKLLM_DIR"] = self._make_stub_dir("boom", exit_code=1)
        v = detect_vendor.markllm_verdict("hello", "synthid", 5)
        self.assertFalse(v.available)
        self.assertIsNotNone(v.error)
        self.assertEqual(v.detector, "markllm-synthid")

    def test_non_executable_venv_python_fail_soft(self):
        """Corrupted venv: .venv/bin/python exists but is not executable ->
        PermissionError (OSError) from subprocess.run must be fail-soft, and
        the CLI must not crash (exit 0)."""
        import detect_vendor, stat, tempfile
        d = tempfile.mkdtemp()
        bindir = os.path.join(d, ".venv", "bin")
        os.makedirs(bindir)
        wrapper = os.path.join(bindir, "python")
        with open(wrapper, "w") as fh:
            fh.write(f"#!/bin/sh\nexec {sys.executable}\n")
        os.chmod(wrapper, 0o644)  # exists, but not executable
        os.environ["ITIPPEX_MARKLLM_DIR"] = d
        v = detect_vendor.markllm_verdict("hello", "kgw", 5)
        self.assertFalse(v.available)
        self.assertIsNotNone(v.error)
        # end-to-end: the CLI itself must not traceback / exit nonzero
        env = dict(os.environ)
        env.pop("ITIPPEX_GEMINI_API_KEY", None)
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "detect_vendor.py"),
             "--backend", "markllm", "-"],
            input="some prose " * 50, capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_missing_keys_in_adapter_success_fail_soft(self):
        """Adapter exits 0 with parseable JSON missing required keys ->
        KeyError must be fail-soft, error naming the missing key."""
        import detect_vendor, json as _json
        payload = _json.dumps({"score": 1.0})  # no is_watermarked/threshold
        os.environ["ITIPPEX_MARKLLM_DIR"] = self._make_stub_dir(payload)
        v = detect_vendor.markllm_verdict("hello", "kgw", 5)
        self.assertFalse(v.available)
        self.assertIn("is_watermarked", v.error)

    def test_non_dict_adapter_output_fail_soft(self):
        """Adapter exits 0 emitting a bare JSON scalar (`42`) -> the
        TypeError from `"error" in data` must be fail-soft, and the CLI must
        not crash."""
        import detect_vendor
        os.environ["ITIPPEX_MARKLLM_DIR"] = self._make_stub_dir("42")
        v = detect_vendor.markllm_verdict("hello", "kgw", 5)
        self.assertFalse(v.available)
        self.assertIsNotNone(v.error)
        env = dict(os.environ)
        env.pop("ITIPPEX_GEMINI_API_KEY", None)
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "detect_vendor.py"),
             "--backend", "markllm", "-"],
            input="some prose " * 50, capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_null_score_adapter_output_fail_soft(self):
        """Adapter exits 0 with {"score": null, ...} -> the TypeError from
        float(None) must be fail-soft."""
        import detect_vendor, json as _json
        payload = _json.dumps({"score": None, "threshold": 3.0,
                               "is_watermarked": True})
        os.environ["ITIPPEX_MARKLLM_DIR"] = self._make_stub_dir(payload)
        v = detect_vendor.markllm_verdict("hello", "kgw", 5)
        self.assertFalse(v.available)
        self.assertIsNotNone(v.error)
