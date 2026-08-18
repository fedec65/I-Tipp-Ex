#!/usr/bin/env python3
"""i-tipp-ex vendor-verdict detection for statistical text watermarks.

Opt-in, explicitly-invoked. One of two network-capable components in the
skill (the other is audit_site.py). Detection here is advisory: vendor
oracles and same-config research harnesses produce Verdicts, never
Findings. Python 3.10+ stdlib only.
"""

from __future__ import annotations

import os
import sys

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
        verdicts.append(gemini_verdict(text, timeout))       # Task 3
    if backend in ("markllm", "all"):
        verdicts.append(markllm_verdict(text, scheme, timeout))  # Task 4
    return verdicts


def gemini_verdict(text, timeout) -> Verdict:  # stub, replaced in Task 3
    return Verdict(detector="gemini-synthid-text", available=False,
                   scope_note=VENDOR_SCOPE, error="not configured")


def markllm_verdict(text, scheme, timeout) -> Verdict:  # stub, replaced in Task 4
    return Verdict(detector=f"markllm-{scheme}", available=False,
                   scope_note=MARKLLM_SCOPE, error="not configured")


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
