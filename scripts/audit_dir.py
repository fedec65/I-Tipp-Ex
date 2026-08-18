#!/usr/bin/env python3
"""i-tipp-ex directory audit: recursively audit every file with audit_file.

Read-only, offline. Usage:

    python3 audit_dir.py <dir> [--json] [-o out] [--max-bytes N] [--include-hidden]
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from report import (
    DEFAULT_MAX_BYTES,
    Finding,
    Report,
    SEVERITIES,
    CONFIDENCES,
    build_base_parser,
    emit_report,
)
from audit_file import audit_file


class DirReport(Report):
    """Report with per-file sub-reports attached."""

    def __init__(self, target: str):
        super().__init__(target=target)
        self.files: list[tuple[str, Report | None]] = []  # (relpath, sub-report)
        self.skipped: list[str] = []

    def to_json_dict(self) -> dict:
        d = super().to_json_dict()
        d["summary"]["by_confidence"] = {
            c: sum(1 for f in self.findings if f.confidence == c)
            for c in CONFIDENCES
        }
        d["files"] = [
            {"path": rel, **(sub.to_json_dict() if sub else {"skipped": True})}
            for rel, sub in self.files
        ]
        return d

    def render_human(self) -> str:
        base = super().render_human()
        lines = ["", "Files:"]
        # Files with high-severity findings first, then by total count.
        def sort_key(item):
            rel, sub = item
            if sub is None:
                return (0, 0, rel)
            c = sub.severity_counts()
            return (-(c["high"] > 0), -len(sub.findings), rel)
        for rel, sub in sorted(self.files, key=sort_key):
            if sub is None:
                lines.append(f"- {rel}: skipped")
                continue
            c = sub.severity_counts()
            lines.append(
                f"- {rel}: {len(sub.findings)} findings "
                f"({c['high']} high, {c['medium']} medium, {c['low']} low, "
                f"{c['informational']} informational)")
        return base + "\n" + "\n".join(lines)


def audit_dir(path: str, max_bytes: int = DEFAULT_MAX_BYTES,
              include_hidden: bool = False) -> DirReport:
    """Recursively audit a directory. Returns a DirReport."""
    report = DirReport(target=path)
    for root, dirs, files in os.walk(path):
        if not include_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files = [f for f in files if not f.startswith(".")]
        for name in sorted(files):
            fpath = os.path.join(root, name)
            rel = os.path.relpath(fpath, path)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                report.add_note(f"skipped (unreadable): {rel}")
                report.files.append((rel, None))
                continue
            if size > max_bytes:
                report.add_note(f"skipped (over --max-bytes): {rel}")
                report.skipped.append(rel)
                report.files.append((rel, None))
                continue
            sub = audit_file(fpath, max_bytes=max_bytes)
            report.files.append((rel, sub))
            for f in sub.findings:
                note = f"at {f.location}"
                if f.note:
                    note += ". " + f.note
                report.add_finding(Finding(
                    severity=f.severity, confidence=f.confidence,
                    category=f.category, location=rel,
                    evidence=f.evidence, context=f.context, note=note,
                ))
    return report


def main(argv=None) -> int:
    parser = build_base_parser(
        description="i-tipp-ex: recursively audit a directory. Read-only, offline."
    )
    parser.add_argument("directory", help="directory to audit")
    parser.add_argument("--include-hidden", action="store_true",
                        help="include dotfiles/dot-directories (default: skip)")
    args = parser.parse_args(argv)
    report = audit_dir(args.directory, max_bytes=args.max_bytes,
                       include_hidden=args.include_hidden)
    emit_report(report, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
