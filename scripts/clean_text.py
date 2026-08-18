#!/usr/bin/env python3
"""i-tipp-ex removal mode, Layer A: scrub flagged Unicode from text.

Opt-in only — audit scripts never call this. Never in-place. See spec §10.

The cleaning decision reuses audit_text's detection tables and its
false-positive function (joiner_fp_reason) directly, so audit and clean can
never disagree: codepoints that audit_text downgrades to informational
(emoji ZWJ sequences, Indic/Arabic shaping joiners) are preserved; variation
selectors are preserved; a document-initial BOM is preserved. Space
homoglyphs are REPLACED with U+0020 (not deleted). Mixed-script confusable
words are NOT addressable — this tool never rewrites wording.

Usage:
    python3 clean_text.py [file|-] [-o out] [--force] [--yes] [--json] [--max-bytes N]
Input from stdin (- or omitted) cleans to stdout unless -o is given.
"""

from __future__ import annotations

import argparse
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from report import DEFAULT_MAX_BYTES, Finding, Report, STATISTICAL_WATERMARK_NOTE
import audit_text
from clean_common import (
    atomic_write,
    confirm_or_abort,
    print_ownership_reminder,
    resolve_output,
)

UNADDRESSABLE_CAVEAT = (
    "Statistical (token-choice) watermarks such as SynthID-Text cannot be "
    "detected or verifiably removed; this tool does not rewrite content."
)


def _action(text: str, i: int) -> str:
    """Return 'keep', 'drop', or 'space' for the character at index i.

    Mirrors audit_text.scan_text's classification exactly, using the same
    tables and the same false-positive function.
    """
    cp = ord(text[i])
    if audit_text._is_variation_selector(cp):
        return "keep"
    if cp in (0x200C, 0x200D):
        # Keep precisely what audit_text downgrades to informational.
        return "keep" if audit_text.joiner_fp_reason(text, i) else "drop"
    if cp == 0x200B:
        return "drop"
    if cp == 0xFEFF:
        return "keep" if i == 0 else "drop"  # document-initial BOM is fine
    if cp in audit_text.FORMAT_CONTROLS:
        return "drop"
    if cp in audit_text.BIDI_CONTROLS:
        return "drop"
    if audit_text._is_tag_char(cp):
        return "drop"
    if audit_text._is_pua(cp):
        return "drop"
    if cp in audit_text.SPACE_HOMOGLYPHS:
        return "space"
    return "keep"


def clean_text_content(text: str) -> tuple[str, dict[int, int]]:
    """Return (cleaned_text, {codepoint: removed_count})."""
    out: list[str] = []
    removed: dict[int, int] = {}
    for i, ch in enumerate(text):
        act = _action(text, i)
        if act == "keep":
            out.append(ch)
        else:
            removed[ord(ch)] = removed.get(ord(ch), 0) + 1
            if act == "space":
                out.append(" ")
    return "".join(out), removed


def _cp_label(cp: int) -> str:
    return f"U+{cp:04X} {unicodedata.name(chr(cp), '<unnamed/PUA>')}"


def run(input_path: str | None, output_arg: str | None, *, force: bool,
        assume_yes: bool, as_json: bool, max_bytes: int) -> int:
    print_ownership_reminder()

    if input_path is None:
        raw = sys.stdin.buffer.read(max_bytes + 1)
        target = "<stdin>"
    else:
        with open(input_path, "rb") as fh:
            raw = fh.read(max_bytes + 1)
        target = input_path
    if len(raw) > max_bytes:
        print(f"Refusing: input exceeds --max-bytes ({max_bytes}); cleaning a "
              "truncated file would be lossy. Raise the cap to proceed.",
              file=sys.stderr)
        return 1
    text = raw.decode("utf-8", "replace")

    before = audit_text.scan_text(text)
    confusables = [f for f in before
                   if f.category == "homoglyph"
                   and f.evidence.startswith("mixed-script word")]

    plan = [f"Plan for {target}:"]
    plan.append(f"  audit findings before cleaning: {len(before)}")
    for f in before:
        plan.append(f"    - [{f.severity}] {f.evidence} @ {f.location}")
    if confusables:
        plan.append(f"  NOT addressable (no rewriting is ever performed): "
                    f"{len(confusables)} mixed-script word(s)")
    plan.append(f"  caveat: {UNADDRESSABLE_CAVEAT}")
    confirm_or_abort(plan, assume_yes)

    cleaned, removed = clean_text_content(text)
    out_path = resolve_output(input_path, output_arg, force)

    if out_path is None:
        sys.stdout.write(cleaned)
        sys.stdout.flush()
    else:
        atomic_write(out_path, cleaned.encode("utf-8"))

    # Post-clean re-audit.
    after = audit_text.scan_text(cleaned)
    verified_gone = [
        f for f in after
        if not (f.severity == "informational" or
                (f.category == "homoglyph" and
                 f.evidence.startswith("mixed-script word")))
    ]
    verified = not verified_gone

    report = Report(target=f"{target} -> {out_path or '<stdout>'}")
    for cp, n in sorted(removed.items()):
        label = "replaced with U+0020" if cp in audit_text.SPACE_HOMOGLYPHS \
            else "removed"
        report.add_note(f"[verifiable] {_cp_label(cp)}: {label} ×{n}")
    for f in after:
        report.add_finding(f)
    if confusables:
        report.add_note("[not addressable] mixed-script confusable words: "
                        f"{len(confusables)} (this tool does not rewrite content)")
    report.add_note(UNADDRESSABLE_CAVEAT)
    report.add_note(STATISTICAL_WATERMARK_NOTE)
    removed_total = sum(removed.values())
    label = "verified" if verified else "best-effort"
    report.add_note(f"removed: {removed_total} ({label}); "
                    f"remaining: {len(after)}; "
                    f"not addressable: {len(confusables)}.")

    rendered = report.render_json() if as_json else report.render_human()
    # When the cleaned text went to stdout, the report goes to stderr so the
    # two streams never mix.
    print(rendered, file=sys.stderr if out_path is None else sys.stdout)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="i-tipp-ex removal mode: scrub flagged Unicode from text. "
                    "Never in-place; audit scripts never call this.")
    parser.add_argument("file", nargs="?", default="-",
                        help="text file to clean; '-' or omitted reads stdin")
    parser.add_argument("-o", "--output", metavar="PATH",
                        help="cleaned output path (default: stdout for stdin, "
                             "<name>.cleaned.<ext> for files)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing output path")
    parser.add_argument("--yes", action="store_true",
                        help="skip the interactive confirmation")
    parser.add_argument("--json", action="store_true",
                        help="emit the removal report as JSON")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)

    input_path = None if args.file in ("-", None) else args.file
    return run(input_path, args.output, force=args.force, assume_yes=args.yes,
               as_json=args.json, max_bytes=args.max_bytes)


if __name__ == "__main__":
    sys.exit(main())
