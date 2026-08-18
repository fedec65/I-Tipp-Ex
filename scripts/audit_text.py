#!/usr/bin/env python3
"""i-tipp-ex Layer A: text/Unicode scanner.

Detects invisible Unicode and homoglyph signals in text: zero-width
characters, C1/Cf format controls, bidi overrides, tag characters, space
homoglyphs, Private Use Area codepoints, and mixed-script confusables.

Read-only: never modifies the input, performs no network I/O.
Python 3.10+ standard library only.

Usage:
    python3 audit_text.py [file]           # '-' or no file reads stdin
    python3 audit_text.py file --json -o report.json
"""

from __future__ import annotations

import bisect
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from report import (
    Finding,
    Report,
    STATISTICAL_WATERMARK_NOTE,
    build_base_parser,
    emit_report,
    sniff_format,
)

# ---------------------------------------------------------------------------
# Detection tables
# ---------------------------------------------------------------------------

ZERO_WIDTH = {
    0x200B: "ZERO WIDTH SPACE",
    0x200C: "ZERO WIDTH NON-JOINER",
    0x200D: "ZERO WIDTH JOINER",
    0xFEFF: "ZERO WIDTH NO-BREAK SPACE (BOM)",
}

FORMAT_CONTROLS = {
    0x00AD: "SOFT HYPHEN",
    0x180E: "MONGOLIAN VOWEL SEPARATOR",
    0x2060: "WORD JOINER",
    0x2061: "FUNCTION APPLICATION",
    0x2062: "INVISIBLE TIMES",
    0x2063: "INVISIBLE SEPARATOR",
    0x2064: "INVISIBLE PLUS",
}

BIDI_CONTROLS = {
    0x202A: "LEFT-TO-RIGHT EMBEDDING",
    0x202B: "RIGHT-TO-LEFT EMBEDDING",
    0x202C: "POP DIRECTIONAL FORMATTING",
    0x202D: "LEFT-TO-RIGHT OVERRIDE",
    0x202E: "RIGHT-TO-LEFT OVERRIDE",
    0x2066: "LEFT-TO-RIGHT ISOLATE",
    0x2067: "RIGHT-TO-LEFT ISOLATE",
    0x2068: "FIRST STRONG ISOLATE",
    0x2069: "POP DIRECTIONAL ISOLATE",
}

SPACE_HOMOGLYPHS = {
    0x00A0: "NO-BREAK SPACE",
    0x2000: "EN QUAD",
    0x2001: "EM QUAD",
    0x2002: "EN SPACE",
    0x2003: "EM SPACE",
    0x2004: "THREE-PER-EM SPACE",
    0x2005: "FOUR-PER-EM SPACE",
    0x2006: "SIX-PER-EM SPACE",
    0x2007: "FIGURE SPACE",
    0x2008: "PUNCTUATION SPACE",
    0x2009: "THIN SPACE",
    0x200A: "HAIR SPACE",
    0x202F: "NARROW NO-BREAK SPACE",
    0x205F: "MEDIUM MATHEMATICAL SPACE",
    0x3000: "IDEOGRAPHIC SPACE",
}

# Variation selectors: legitimate after emoji bases; not findings by default.
def _is_variation_selector(cp: int) -> bool:
    return (0xFE00 <= cp <= 0xFE0F) or (0xE0100 <= cp <= 0xE01EF)

# Tag characters U+E0000..U+E007F.
def _is_tag_char(cp: int) -> bool:
    return 0xE0000 <= cp <= 0xE007F

def _is_pua(cp: int) -> bool:
    return (
        0xE000 <= cp <= 0xF8FF
        or 0xF0000 <= cp <= 0xFFFFD
        or 0x100000 <= cp <= 0x10FFFD
    )

# ---------------------------------------------------------------------------
# False-positive context detection for ZWJ (U+200D) / ZWNJ (U+200C)
# ---------------------------------------------------------------------------

# Emoji and emoji-adjacent ranges. A ZWJ/ZWNJ sitting next to any of these is
# almost certainly part of an emoji ZWJ sequence (family glyphs, professions,
# skin tones, keycaps, flags) rather than a hidden-watermark signal.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),   # emoticons, pictographs, symbols, transport, supplemental
    (0x2600, 0x27BF),     # misc symbols + dingbats
    (0x2B00, 0x2BFF),     # arrows/stars used as emoji
    (0xFE00, 0xFE0F),     # variation selectors
    (0x1F1E6, 0x1F1FF),   # regional indicators (flags)
    (0xE0020, 0xE007F),   # tag chars used in subdivision flags
)
_EMOJI_SINGLES = {
    0x200D, 0x200C,       # chained joiners
    0x20E3,               # combining keycap
    0x2640, 0x2642,       # female/male sign
    0x2695,               # staff of aesculapius
    0x2764,               # heavy black heart
}

# Scripts where ZWNJ/ZWJ are required for correct shaping (Indic conjuncts,
# Persian/Arabic cursive control).
_INDIC_ARABIC_RANGES = (
    (0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),   # Arabic + supplements
    (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),                     # Arabic presentation forms
    (0x0900, 0x097F),   # Devanagari
    (0x0980, 0x09FF),   # Bengali
    (0x0A00, 0x0A7F),   # Gurmukhi
    (0x0A80, 0x0AFF),   # Gujarati
    (0x0B00, 0x0B7F),   # Oriya
    (0x0B80, 0x0BFF),   # Tamil
    (0x0C00, 0x0C7F),   # Telugu
    (0x0C80, 0x0CFF),   # Kannada
    (0x0D00, 0x0D7F),   # Malayalam
    (0x0D80, 0x0DFF),   # Sinhala
)


def _in_ranges(cp: int, ranges) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def joiner_fp_reason(text: str, i: int) -> str | None:
    """Return a reason string if the joiner at index i is legitimate, else None.

    Checks the immediately adjacent characters: emoji context and
    Indic/Arabic shaping context.
    """
    for j in (i - 1, i + 1):
        if 0 <= j < len(text):
            cp = ord(text[j])
            if _in_ranges(cp, _EMOJI_RANGES) or cp in _EMOJI_SINGLES:
                return "adjacent to emoji sequence characters; legitimate ZWJ/ZWNJ use"
    for j in (i - 1, i + 1):
        if 0 <= j < len(text):
            cp = ord(text[j])
            if _in_ranges(cp, _INDIC_ARABIC_RANGES):
                return "adjacent to Indic/Arabic script characters; required for shaping"
    return None


# ---------------------------------------------------------------------------
# Mixed-script confusables
# ---------------------------------------------------------------------------

# Words of Latin + Cyrillic/Greek letters where both scripts appear.
_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ\u0370-\u03FF\u0400-\u04FF]+")


def _script_of(cp: int) -> str | None:
    if 0x0370 <= cp <= 0x03FF:
        return "Greek"
    if 0x0400 <= cp <= 0x04FF:
        return "Cyrillic"
    if (0x41 <= cp <= 0x5A) or (0x61 <= cp <= 0x7A) or (0xC0 <= cp <= 0xFF and cp != 0xD7 and cp != 0xF7):
        return "Latin"
    return None


def find_confusable_words(text: str) -> list[tuple[int, str, list[str]]]:
    """Return (char_index, word, detail_parts) for mixed-script words."""
    hits = []
    for m in _WORD_RE.finditer(text):
        word = m.group()
        scripts = {_script_of(ord(c)) for c in word}
        scripts.discard(None)
        if "Latin" not in scripts or not (scripts & {"Cyrillic", "Greek"}):
            continue
        details = []
        first_foreign = 0
        for k, c in enumerate(word):
            s = _script_of(ord(c))
            if s in ("Cyrillic", "Greek"):
                if not details:
                    first_foreign = k
                details.append(f"{s} {c} U+{ord(c):04X}")
        hits.append((m.start() + first_foreign, word, details))
    return hits


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

_MAX_NOTE_LOCS = 20
_CTX_RADIUS = 40  # ~80-char snippets


def _codepoint_name(cp: int) -> str:
    if cp in ZERO_WIDTH:
        return ZERO_WIDTH[cp]
    if cp in FORMAT_CONTROLS:
        return FORMAT_CONTROLS[cp]
    if cp in BIDI_CONTROLS:
        return BIDI_CONTROLS[cp]
    if cp in SPACE_HOMOGLYPHS:
        return SPACE_HOMOGLYPHS[cp]
    if _is_tag_char(cp):
        return "TAG CHARACTER" if cp != 0xE0001 else "LANGUAGE TAG"
    if _is_pua(cp):
        return "PRIVATE USE AREA"
    return unicodedata.name(chr(cp), "<unnamed>")


def scan_text(text: str) -> list[Finding]:
    """Scan decoded text and return findings (unsorted; render groups them)."""
    lines = text.split("\n")
    line_starts = [0]
    for ln in lines[:-1]:
        line_starts.append(line_starts[-1] + len(ln) + 1)

    def line_col(i: int) -> tuple[int, int]:
        ln = bisect.bisect_right(line_starts, i)  # 1-based line
        return ln, i - line_starts[ln - 1] + 1

    def context_at(i: int) -> str:
        ln, col = line_col(i)
        line_text = lines[ln - 1]
        c0 = col - 1
        snippet = line_text[max(0, c0 - _CTX_RADIUS): c0 + _CTX_RADIUS + 1]
        # Make invisible chars visible in the snippet itself.
        def vis(ch: str) -> str:
            cp = ord(ch)
            if cp < 0x20 or unicodedata.category(ch) == "Cf" or _is_pua(cp) or _is_tag_char(cp):
                return f"<U+{cp:04X}>"
            return ch
        return "".join(vis(ch) for ch in snippet)

    # Aggregate duplicate codepoints: key -> record
    agg: dict[tuple, dict] = {}

    def record(cp: int, i: int, severity: str, confidence: str,
               category: str, note: str = "") -> None:
        ln, col = line_col(i)
        key = (cp, severity, confidence, category, note)
        slot = agg.setdefault(key, {
            "locs": [], "first_i": i,
            "severity": severity, "confidence": confidence,
            "category": category, "note": note,
        })
        slot["locs"].append((ln, col))

    for i, ch in enumerate(text):
        cp = ord(ch)
        if _is_variation_selector(cp):
            continue  # VS15/VS16 etc. are not findings by default
        if cp in (0x200C, 0x200D):
            reason = joiner_fp_reason(text, i)
            if reason:
                record(cp, i, "informational", "informational",
                       "invisible-unicode", note=reason)
            else:
                record(cp, i, "medium", "confirmed", "invisible-unicode")
        elif cp == 0x200B:
            record(cp, i, "medium", "confirmed", "invisible-unicode")
        elif cp == 0xFEFF:
            if i != 0:  # a BOM as the very first character is legitimate
                record(cp, i, "medium", "confirmed", "invisible-unicode",
                       note="BOM/zero-width no-break space not at document start")
        elif cp == 0x00AD:
            # Soft hyphen is never reported above low.
            record(cp, i, "low", "confirmed", "invisible-unicode",
                   note="soft hyphen; may be legitimate hyphenation")
        elif cp in FORMAT_CONTROLS:
            record(cp, i, "medium", "confirmed", "invisible-unicode")
        elif cp in BIDI_CONTROLS:
            record(cp, i, "high", "confirmed", "bidi-override",
                   note="can visually reorder text; review surrounding content")
        elif _is_tag_char(cp):
            record(cp, i, "high", "confirmed", "invisible-unicode",
                   note="tag characters can encode hidden payloads")
        elif _is_pua(cp):
            record(cp, i, "high", "confirmed", "invisible-unicode",
                   note="private use codepoint in prose; meaning is font-defined")
        elif cp in SPACE_HOMOGLYPHS:
            record(cp, i, "low", "probable", "homoglyph",
                   note="space-like character where a regular space is expected; "
                        "may be legitimate typography")

    findings: list[Finding] = []
    for (cp, sev, conf, cat, note), slot in sorted(
            agg.items(), key=lambda kv: kv[1]["first_i"]):
        locs = slot["locs"]
        name = _codepoint_name(cp)
        count = len(locs)
        evidence = f"U+{cp:04X} {name}" + (f" ×{count}" if count > 1 else "")
        loc_strs = [f"line {ln}, col {c}" for ln, c in locs[:_MAX_NOTE_LOCS]]
        loc_note = "; ".join(loc_strs)
        if count > _MAX_NOTE_LOCS:
            loc_note += f"; +{count - _MAX_NOTE_LOCS} more"
        full_note = f"{count} occurrence(s): {loc_note}"
        if note:
            full_note = note + ". " + full_note
        findings.append(Finding(
            severity=sev, confidence=conf, category=cat,
            location=loc_strs[0],
            evidence=evidence,
            context=context_at(slot["first_i"]),
            note=full_note,
        ))

    for idx, word, details in find_confusable_words(text):
        ln, col = line_col(idx)
        findings.append(Finding(
            severity="medium", confidence="probable", category="homoglyph",
            location=f"line {ln}, col {col}",
            evidence=f"mixed-script word {word!r} ({'; '.join(details)})",
            context=context_at(idx),
            note="Latin-looking word containing Cyrillic/Greek lookalike letters; "
                 "may be legitimate in scientific notation or loanwords",
        ))

    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = build_base_parser(
        description="i-tipp-ex Layer A: scan text for invisible Unicode, "
                    "bidi overrides, and homoglyph signals. Read-only."
    )
    parser.add_argument("file", nargs="?", default="-",
                        help="text file to audit; '-' or omitted reads stdin")
    args = parser.parse_args(argv)

    limit = max(0, args.max_bytes)
    if args.file in ("-", None):
        target = "<stdin>"
        raw = sys.stdin.buffer.read(limit + 1)
    else:
        target = args.file
        with open(args.file, "rb") as fh:
            raw = fh.read(limit + 1)

    report = Report(target=target)
    report.add_note(STATISTICAL_WATERMARK_NOTE)

    truncated = len(raw) > limit
    raw = raw[:limit]
    if truncated:
        report.add_note(
            f"Input truncated at {limit} bytes (--max-bytes); "
            "findings cover only the first part of the input."
        )

    if sniff_format(raw) == "binary":
        report.add_note(
            "Input looks like a binary format (magic bytes / control-byte "
            "ratio); a text-layer scan of it may not be meaningful. "
            "Run the file-level audit instead."
        )

    text = raw.decode("utf-8", errors="replace")
    for f in scan_text(text):
        report.add_finding(f)

    emit_report(report, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
