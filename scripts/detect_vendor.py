#!/usr/bin/env python3
"""i-tipp-ex vendor-verdict detection for statistical text watermarks.

Opt-in, explicitly-invoked. One of two network-capable components in the
skill (the other is audit_site.py). Detection here is advisory: vendor
oracles and same-config research harnesses produce Verdicts, never
Findings. Python 3.10+ stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from report import (  # noqa: E402
    Report, Verdict, VENDOR_VERDICT_CAVEATS, STATISTICAL_WATERMARK_NOTE,
    build_base_parser, emit_report, sniff_format,
)

SIZE_CAP = 1024 * 1024  # 1 MiB of text; --allow-large overrides

VENDOR_SCOPE = "vendor verdict — not independently verifiable"
MARKLLM_SCOPE = "same-scheme/same-config check only — other schemes unchecked"


def read_input(path, max_bytes, allow_large) -> tuple[str, str]:
    """Read UTF-8 text from path (or stdin for '-'/None). Exit 2 on binary
    input or oversize without allow_large."""
    if path in (None, "-"):
        raw = sys.stdin.buffer.read(max_bytes + 1)
        target = "<stdin>"
    else:
        with open(path, "rb") as fh:
            raw = fh.read(max_bytes + 1)
        target = path
    if len(raw) > max_bytes and not allow_large:
        print(f"input exceeds {max_bytes} bytes; pass --allow-large to proceed",
              file=sys.stderr)
        raise SystemExit(2)
    if sniff_format(raw) == "binary":
        print("refusing to treat input as text: it looks like a binary "
              "container. Use audit_file.py to audit containers.",
              file=sys.stderr)
        raise SystemExit(2)
    return raw.decode("utf-8", errors="replace"), target


def run_backends(text, backend, scheme, timeout) -> list[Verdict]:
    verdicts: list[Verdict] = []
    if backend in ("gemini", "all"):
        verdicts.append(gemini_verdict(text, timeout))
    if backend in ("markllm", "all"):
        verdicts.append(markllm_verdict(text, scheme, timeout))  # Task 4
    return verdicts


GEMINI_KEY_ENV = "ITIPPEX_GEMINI_API_KEY"
GEMINI_MODEL_ENV = "ITIPPEX_GEMINI_MODEL"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
# Endpoint/payload per the Gemini API generateContent contract with the
# watermark-detection task type, as driven by the reference implementation
# (taskType DETECT_TEXT_WATERMARK inside generationConfig):
# https://github.com/guillaumemeyer/watermarks-remover/blob/main/service/scripts/text_detectors.py
# generateContent request/response shape and x-goog-api-key auth header:
# https://ai.google.dev/api/generate-content
# No official docs page for the taskType was reachable at implementation
# time; the reference repo above is the corroborating source.
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/"
              "models/{model}:generateContent")

_WATERMARKED_MARKERS = ("watermarked", "ai-generated", "ai generated",
                        "likely ai")
_VERDICT_MARKER_RES = tuple(re.compile(rf"\b{m}\b") for m in
                            _WATERMARKED_MARKERS)
_VERDICT_NEGATION_RE = re.compile(
    r"\b(?:unlikely|not|no|cannot|never|isn't|doesn't|wasn't)\b")


def _verdict_is_watermarked(verdict: str) -> bool:
    """Map a RECOGNIZED free-text verdict to a boolean; raise ValueError
    for anything unrecognized — never guess. A marker counts as affirmative
    only when no negation precedes it, so "The text is not AI-generated"
    is a recognized negative rather than an affirmative. Markers match on
    word boundaries so "likely ai" never fires inside "unlikely"."""
    low = verdict.strip().lower()
    hits = [match.start() for match in
            (r.search(low) for r in _VERDICT_MARKER_RES) if match]
    if not hits:
        raise ValueError(f"unrecognized verdict text: {verdict!r}")
    if _VERDICT_NEGATION_RE.search(low[:min(hits)]):
        return False
    return True


_SCORE_KEYS = ("watermarkScore", "watermark_score", "syntheticTextScore",
               "synthetic_text_score", "score")


def _post_json(url, payload, headers, timeout) -> dict:
    """POST JSON to *url* and return the decoded response object."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"non-object response: {type(data).__name__}")
    return data


def _numeric_score(candidate: dict, top: dict):
    """Pull a numeric watermark score from either response shape, if any."""
    for container in (candidate, top):
        for key in _SCORE_KEYS:
            value = container.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    attribution = candidate.get("attributionMetadata") or {}
    if isinstance(attribution, dict):
        for key in ("syntheticTextScore", "synthetic_text_score", "score"):
            value = attribution.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        synth = attribution.get("syntheticText")
        if isinstance(synth, dict):
            for key in ("score", "confidence"):
                value = synth.get(key)
                if isinstance(value, (int, float)):
                    return float(value)
    return None


def _parse_gemini_response(data: dict):
    """Extract (is_watermarked, score) from a known response shape.

    Accepts both the flat boolean contract ({"watermarkDetected": bool})
    and the generateContent shape (free-text verdict in candidates[0]
    .content.parts[0].text, optional numeric score). Raises ValueError on
    anything unrecognized — never guesses.
    """
    detected = data.get("watermarkDetected")
    if isinstance(detected, bool):
        return detected, _numeric_score({}, data)
    candidates = data.get("candidates") or []
    candidate = candidates[0] if candidates and isinstance(candidates[0],
                                                           dict) else {}
    if not candidate:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise ValueError(f"Gemini blocked the request: {block}")
        raise ValueError("Gemini returned no candidates")
    verdict = None
    parts = (candidate.get("content") or {}).get("parts") or []
    if parts and isinstance(parts[0], dict):
        verdict = parts[0].get("text")
    if not isinstance(verdict, str) or not verdict.strip():
        verdict = None  # empty verdict text counts as no verdict
    score = _numeric_score(candidate, data)
    if not isinstance(verdict, str) and score is None:
        raise ValueError(f"unrecognized response: {sorted(data)}")
    if isinstance(verdict, str):
        return _verdict_is_watermarked(verdict), score
    return score >= 0.5, score


def gemini_verdict(text, timeout, _post=_post_json) -> Verdict:
    """Query Google's SynthID-Text detector through the Gemini API.

    Key comes from ITIPPEX_GEMINI_API_KEY (env only) and travels in the
    x-goog-api-key header, never the URL. Every failure — unconfigured key,
    network/HTTP/JSON error, unrecognized response — is fail-soft: an
    unavailable Verdict, never a guessed one.
    """
    def out(available: bool, **kw) -> Verdict:
        return Verdict(detector="gemini-synthid-text", available=available,
                       scope_note=VENDOR_SCOPE, **kw)

    key = os.environ.get(GEMINI_KEY_ENV)
    if not key:
        return out(False, error=f"{GEMINI_KEY_ENV} not set")
    model = os.environ.get(GEMINI_MODEL_ENV, GEMINI_DEFAULT_MODEL)
    url = GEMINI_URL.format(model=model)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {"taskType": "DETECT_TEXT_WATERMARK"},
    }
    print("note: sending text to Google's API for SynthID-Text detection",
          file=sys.stderr)
    try:
        data = _post(url, payload, {"x-goog-api-key": key}, timeout)
        is_watermarked, score = _parse_gemini_response(data)
    except Exception as exc:  # network, HTTP, JSON, parse — all fail-soft
        return out(False, error=str(exc))
    return out(True, is_watermarked=is_watermarked, score=score)


MARKLLM_DIR_ENV = "ITIPPEX_MARKLLM_DIR"


def markllm_verdict(text, scheme, timeout) -> Verdict:
    """Detect via an external MarkLLM checkout's venv (ITIPPEX_MARKLLM_DIR).

    Runs scripts/markllm_adapter.py with <dir>/.venv/bin/python as a
    subprocess; the adapter emits one JSON object on its last stdout line
    ({"score": float, "threshold": float, "is_watermarked": bool} or
    {"error": ...}). Every failure — unconfigured env, missing venv python,
    timeout, nonzero exit, unparseable stdout — is fail-soft: an unavailable
    Verdict, never a guessed one. MarkLLM is never vendored or installed.
    """
    def out(available: bool, **kw) -> Verdict:
        return Verdict(detector=f"markllm-{scheme}", available=available,
                       scope_note=MARKLLM_SCOPE, **kw)

    root = os.environ.get(MARKLLM_DIR_ENV)
    if not root:
        return out(False, error=f"{MARKLLM_DIR_ENV} not set")
    venv_py = os.path.join(root, ".venv", "bin", "python")
    if not os.path.exists(venv_py):
        return out(False, error=f"no venv python at {venv_py}")
    adapter = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "markllm_adapter.py")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                      encoding="utf-8")
    try:
        tmp.write(text)
        tmp.close()
        proc = subprocess.run(
            [venv_py, adapter, "detect", tmp.name, "--scheme", scheme,
             "--json"],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return out(False, error="timeout")
    except OSError as exc:  # e.g. venv python exists but is not executable
        return out(False, error=str(exc))
    finally:
        os.unlink(tmp.name)
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return out(False,
                   error=f"unparseable adapter output: {proc.stdout[:300]}")
    if proc.returncode != 0 or "error" in data:
        return out(False, error=data.get("error") or proc.stderr[:300])
    for key in ("is_watermarked", "score", "threshold"):
        if key not in data:
            return out(False, error=f"adapter output missing {key!r}: "
                                    f"{proc.stdout[:300]}")
    return out(True, is_watermarked=bool(data["is_watermarked"]),
               score=float(data["score"]),
               threshold=float(data["threshold"]))


def main(argv=None) -> int:
    parser = build_base_parser(
        description="Detect statistical (token-choice) text watermarks via "
                    "vendor or research detectors. Advisory only.")
    parser.add_argument("file", nargs="?", default="-",
                        help="text file to check ('-'/omitted reads stdin)")
    parser.add_argument("--backend", choices=("gemini", "markllm", "all"),
                        required=True, help="which detector to query")
    parser.add_argument("--scheme", choices=("kgw", "synthid"), default="kgw",
                        help="MarkLLM scheme (default: %(default)s)")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="per-backend timeout in seconds")
    parser.add_argument("--allow-large", action="store_true",
                        help=f"allow inputs over {SIZE_CAP} bytes")
    args = parser.parse_args(argv)

    text, target = read_input(args.file, min(args.max_bytes, SIZE_CAP)
                              if not args.allow_large else args.max_bytes,
                              args.allow_large)
    rep = Report(target=target)
    for v in run_backends(text, args.backend, args.scheme, args.timeout):
        rep.add_verdict(v)
    rep.add_note(STATISTICAL_WATERMARK_NOTE)
    emit_report(rep, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
