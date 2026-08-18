#!/usr/bin/env python3
"""Shared safety machinery for the i-tipp-ex removal mode (clean_*.py).

Removal mode is opt-in only: audit scripts never import or call this module.
Everything here enforces spec §10: never in-place, atomic writes, per-run
confirmation, and the always-printed ownership reminder.
"""

from __future__ import annotations

import os
import sys
import tempfile

OWNERSHIP_REMINDER = (
    "Intended for content you own or are authorized to process; stripping "
    "required transparency marking may have legal implications in some "
    "jurisdictions (e.g. EU AI Act deployer obligations)."
)

_reminder_printed = False


def print_ownership_reminder() -> None:
    """Print the ownership reminder to stderr — ALWAYS, once per process."""
    global _reminder_printed
    if not _reminder_printed:
        print(OWNERSHIP_REMINDER, file=sys.stderr)
        _reminder_printed = True


def confirm_or_abort(plan_lines: list[str], assume_yes: bool) -> None:
    """Show the plan; without --yes require an interactive y/yes.

    Non-interactive stdin without --yes aborts with guidance.
    """
    for line in plan_lines:
        print(line, file=sys.stderr)
    if assume_yes:
        return
    if not sys.stdin.isatty():
        print("Non-interactive stdin: review the plan above and re-run with "
              "--yes to proceed.", file=sys.stderr)
        raise SystemExit(1)
    try:
        reply = input("Proceed? [y/N] ")
    except EOFError:
        reply = ""
    if reply.strip().lower() not in ("y", "yes"):
        print("Aborted; nothing was written.", file=sys.stderr)
        raise SystemExit(1)


def resolve_output(input_path: str | None, output_arg: str | None,
                   force: bool) -> str | None:
    """Resolve the cleaned-output path. Returns None for stdout.

    Rules: never in-place; default suffix `.cleaned.<ext>`; refuse existing
    paths without --force; refuse symlink destinations; refuse output that
    resolves to the input.
    """
    if output_arg is None:
        if input_path is None:
            return None  # stdout
        base, ext = os.path.splitext(input_path)
        output = f"{base}.cleaned{ext}"
    else:
        output = output_arg
    if input_path is not None and os.path.realpath(output) == os.path.realpath(input_path):
        raise SystemExit("Refusing: output path resolves to the input file "
                         "(in-place cleaning is never performed).")
    if os.path.islink(output):
        raise SystemExit(f"Refusing: output path is a symlink: {output}")
    if os.path.exists(output) and not force:
        raise SystemExit(f"Refusing: output path already exists: {output} "
                         "(pass --force to overwrite)")
    return output


def atomic_write(path: str, data: bytes) -> None:
    """Write data to path atomically: temp file in the destination dir,
    then os.replace. Cleans the temp file up on any failure."""
    dest_dir = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".i-tipp-ex-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
