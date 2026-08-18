#!/usr/bin/env python3
"""i-tipp-ex shared finding model and report rendering.

Every audit script (audit_text, audit_file, audit_site, ...) builds a Report
of Findings and emits it through the helpers in this module, so output shape
stays identical across layers.

Import from sibling scripts and from tests/ with:

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/
    from report import Finding, Report, ...

Honesty rule: reports describe findings, never verdicts. Do not emit
"pass"/"fail"/"clean"/"safe"/"AI-free" anywhere in audit output.

Python 3.10+ standard library only. No network I/O. Never modifies input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

TOOL_NAME = "i-tipp-ex"
TOOL_VERSION = "1.1.0"

SEVERITIES = ("high", "medium", "low", "informational")
CONFIDENCES = ("confirmed", "probable", "informational", "likely_false_positive")
CATEGORIES = (
    "invisible-unicode",
    "bidi-override",
    "c2pa-manifest",
    "ai-metadata",
    "generator-meta",
    "homoglyph",
)

DEFAULT_MAX_BYTES = 256 * 1024 * 1024

STATISTICAL_WATERMARK_NOTE = (
    "Statistical (token-choice) watermarks such as SynthID-Text cannot be "
    "detected without the vendor's private key; their absence here proves "
    "nothing either way."
)


@dataclass
class Finding:
    """One auditable observation with verifiable evidence."""

    severity: str        # high | medium | low | informational
    confidence: str      # confirmed | probable | informational | likely_false_positive
    category: str        # see CATEGORIES
    location: str        # e.g. "line 3, col 42" or "EXIF:Software"
    evidence: str        # what was found, e.g. "U+202E RIGHT-TO-LEFT OVERRIDE"
    context: str = ""    # short snippet around the evidence
    note: str = ""       # caveats, extra locations, FP rationale

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"bad severity: {self.severity!r}")
        if self.confidence not in CONFIDENCES:
            raise ValueError(f"bad confidence: {self.confidence!r}")
        if self.category not in CATEGORIES:
            raise ValueError(f"bad category: {self.category!r}")

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "confidence": self.confidence,
            "category": self.category,
            "location": self.location,
            "evidence": self.evidence,
            "context": self.context,
            "note": self.note,
        }


VERDICT_DETECTORS = ("gemini-synthid-text", "markllm-kgw", "markllm-synthid")

VENDOR_VERDICT_CAVEATS = (
    "Vendor verdicts come from a vendor-operated detector; the key stays with "
    "the vendor and the result is not independently verifiable.",
    "MarkLLM checks one scheme under one configuration; a negative result does "
    "not rule out other schemes or configs.",
    "Absence of a verdict proves nothing either way.",
)


@dataclass
class Verdict:
    """An external detector's answer about statistical watermarking.

    Never a Finding: verdicts do not enter severity counts and must always
    carry scope_note caveats.
    """

    detector: str                     # one of VERDICT_DETECTORS
    available: bool                   # False = unconfigured/errored; see error
    is_watermarked: bool | None = None
    score: float | None = None
    threshold: float | None = None
    scope_note: str = ""
    error: str | None = None

    def __post_init__(self) -> None:
        if self.detector not in VERDICT_DETECTORS:
            raise ValueError(f"bad detector: {self.detector!r}")

    def to_dict(self) -> dict:
        return {
            "detector": self.detector,
            "available": self.available,
            "is_watermarked": self.is_watermarked,
            "score": self.score,
            "threshold": self.threshold,
            "scope_note": self.scope_note,
            "error": self.error,
        }


@dataclass
class Report:
    """Aggregated findings for one audit target."""

    target: str
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    tool: str = TOOL_NAME
    version: str = TOOL_VERSION

    def add_finding(self, finding: Finding) -> None:
        self.findings.append(finding)

    def add_verdict(self, verdict: Verdict) -> None:
        self.verdicts.append(verdict)

    def add_note(self, note: str) -> None:
        if note not in self.notes:
            self.notes.append(note)

    def severity_counts(self) -> dict:
        counts = {s: 0 for s in SEVERITIES}
        for f in self.findings:
            counts[f.severity] += 1
        return counts

    def to_json_dict(self) -> dict:
        out = {
            "tool": self.tool,
            "version": self.version,
            "target": self.target,
            "notes": list(self.notes),
            "summary": {
                "total": len(self.findings),
                **self.severity_counts(),
            },
            "findings": [f.to_dict() for f in self.findings],
        }
        if self.verdicts:
            out["verdicts"] = [v.to_dict() for v in self.verdicts]
        return out

    def render_json(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2, ensure_ascii=False)

    def render_human(self) -> str:
        lines = ["I-Tipp-Ex audit findings", f"Target: {self.target}", ""]
        counts = self.severity_counts()
        for sev in SEVERITIES:  # high first
            group = [f for f in self.findings if f.severity == sev]
            if not group:
                continue
            lines.append(f"[{sev}]")
            for f in group:
                lines.append(f"- {f.location}")
                lines.append(f"  evidence: {f.evidence}")
                if f.context:
                    lines.append(f"  context: {f.context}")
                if f.note:
                    lines.append(f"  note: {f.note}")
                lines.append(f"  category: {f.category}; confidence: {f.confidence}")
            lines.append("")
        if self.notes:
            lines.append("Standing notes:")
            for n in self.notes:
                lines.append(f"- {n}")
            lines.append("")
        if self.verdicts:
            lines.append("Vendor verdicts (not independently verifiable)")
            for v in self.verdicts:
                if not v.available:
                    lines.append(f"- {v.detector}: unavailable ({v.error})")
                elif v.is_watermarked is None:
                    detail = f" (score {v.score})" if v.score is not None else ""
                    lines.append(f"- {v.detector}: no verdict{detail}")
                else:
                    state = "watermark detected" if v.is_watermarked else "not detected"
                    detail = ""
                    if v.score is not None and v.threshold is not None:
                        detail = f" (score {v.score}, threshold {v.threshold})"
                    elif v.score is not None:
                        detail = f" (score {v.score})"
                    lines.append(f"- {v.detector}: {state}{detail}")
                if v.scope_note:
                    lines.append(f"  note: {v.scope_note}")
            for caveat in VENDOR_VERDICT_CAVEATS:
                lines.append(f"  caveat: {caveat}")
            lines.append("")
        lines.append(
            f"{len(self.findings)} findings "
            f"({counts['high']} high, {counts['medium']} medium, "
            f"{counts['low']} low, {counts['informational']} informational)"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared CLI helpers
# ---------------------------------------------------------------------------

def build_base_parser(description: str | None = None) -> argparse.ArgumentParser:
    """Base parser shared by all audit scripts.

    Scripts add their own positional/flag arguments on top of this.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--json", action="store_true",
        help="emit JSON instead of the human-readable report",
    )
    parser.add_argument(
        "-o", "--output", metavar="PATH",
        help="also write the report to PATH (UTF-8)",
    )
    parser.add_argument(
        "--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
        help="maximum input bytes to read (default: %(default)s)",
    )
    return parser


# Magic-byte prefixes that unambiguously mark binary container formats.
_MAGIC_PREFIXES = (
    b"\x89PNG\r\n\x1a\n",      # PNG
    b"\xff\xd8\xff",           # JPEG
    b"GIF87a", b"GIF89a",      # GIF
    b"%PDF",                   # PDF
    b"PK\x03\x04",             # ZIP and ZIP-based (docx, xlsx, epub, jar)
    b"\x1f\x8b",               # gzip
    b"BZh",                    # bzip2
    b"\xfd7zXZ\x00",           # xz
    b"Rar!\x1a\x07",           # RAR
    b"RIFF",                   # WAV/AVI/WebP
    b"OggS",                   # Ogg
    b"fLaC",                   # FLAC
    b"ID3",                    # MP3 with tags
    b"\x7fELF",                # ELF
    b"MZ",                     # PE/COFF
    b"\xca\xfe\xba\xbe",       # Mach-O fat / Java class
    b"\xfe\xed\xfa", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",  # Mach-O
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # OLE2 (doc, xls, ppt)
    b"SQLite format 3\x00",    # SQLite
    b"\x00\x00\x01\x00",       # ICO
    b"\x00\x00\x00\x18ftyp",   # ISO BMFF (mp4/mov) variant
    b"\x00\x00\x00\x1cftyp", b"\x00\x00\x00\x20ftyp",
)

# Unicode BOMs mark the file as text (of some encoding) even though they are
# non-ASCII bytes.
_TEXT_BOMS = (
    b"\xef\xbb\xbf",           # UTF-8
    b"\xff\xfe\x00\x00",       # UTF-32 LE (before UTF-16 LE: shared prefix)
    b"\x00\x00\xfe\xff",       # UTF-32 BE
    b"\xff\xfe",               # UTF-16 LE
    b"\xfe\xff",               # UTF-16 BE
)

_SNIFF_HEAD = 8192
_BINARY_CONTROL_RATIO = 0.30


def sniff_format(source) -> str:
    """Return "binary" or "text" for a path, bytes, or binary file object.

    Routing decision, in order — never by file extension:
      1. Known binary magic bytes -> "binary".
      2. Unicode BOM -> "text".
      3. Any NUL byte in the first 8 KiB -> "binary" (real text files
         essentially never contain NUL; this is git's heuristic). Note
         this also routes BOM-less UTF-16/UTF-32 text to "binary" —
         decoders should still handle them gracefully.
      4. Control-byte ratio of the first 8 KiB: bytes outside
         {TAB, LF, FF, CR} and below 0x20, plus DEL, exceeding 30%
         -> "binary"; otherwise "text".
    Empty input is "text".
    """
    if hasattr(source, "read"):
        head = source.read(_SNIFF_HEAD)
    elif isinstance(source, (bytes, bytearray)):
        head = bytes(source[:_SNIFF_HEAD])
    else:
        with open(os.fspath(source), "rb") as fh:
            head = fh.read(_SNIFF_HEAD)
    if not head:
        return "text"
    for magic in _MAGIC_PREFIXES:
        if head.startswith(magic):
            return "binary"
    for bom in _TEXT_BOMS:
        if head.startswith(bom):
            return "text"
    if b"\x00" in head:
        return "binary"
    allowed = {0x09, 0x0A, 0x0C, 0x0D}
    control = sum(
        1 for b in head
        if (b < 0x20 and b not in allowed) or b == 0x7F
    )
    if control / len(head) > _BINARY_CONTROL_RATIO:
        return "binary"
    return "text"


def emit_report(report: Report, args: argparse.Namespace) -> None:
    """Print the report (JSON if args.json, else human) and optionally write
    it to args.output. Never writes anything but the report itself."""
    text = report.render_json() if getattr(args, "json", False) else report.render_human()
    print(text)
    out = getattr(args, "output", None)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main(argv=None) -> int:
    """Minimal self-check entry point: emit an empty report for a target."""
    parser = build_base_parser(
        description="i-tipp-ex report module self-check / empty-report emitter."
    )
    parser.add_argument("target", nargs="?", default="<none>",
                        help="target label for the report")
    args = parser.parse_args(argv)
    report = Report(target=args.target)
    report.add_note("No audit layer was run; this is the report module self-check.")
    emit_report(report, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
