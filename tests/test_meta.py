"""Cross-cutting tests: read-only guarantees and stdlib-only imports."""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
FIXTURES = os.path.join(ROOT, "assets", "fixtures")
sys.path.insert(0, SCRIPTS)


def md5(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def fixture_files():
    for dirpath, _dirs, files in os.walk(FIXTURES):
        for name in sorted(files):
            if name == "build_fixtures.py" or name == ".gitkeep":
                continue
            yield os.path.join(dirpath, name)


class ReadOnlyTests(unittest.TestCase):
    def test_readonly(self):
        """All four audit entry points leave every fixture byte-identical."""
        before = {p: md5(p) for p in fixture_files()}
        cmds = [
            [sys.executable, os.path.join(SCRIPTS, "audit_text.py"),
             os.path.join(FIXTURES, "text", "zero_width.md")],
            [sys.executable, os.path.join(SCRIPTS, "audit_file.py"),
             os.path.join(FIXTURES, "doc", "ai_props.docx")],
            [sys.executable, os.path.join(SCRIPTS, "audit_file.py"),
             os.path.join(FIXTURES, "img", "c2pa.png")],
            [sys.executable, os.path.join(SCRIPTS, "audit_file.py"),
             os.path.join(FIXTURES, "site", "sitemap.xml")],
            [sys.executable, os.path.join(SCRIPTS, "audit_dir.py"), FIXTURES],
        ]
        for cmd in cmds:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0,
                             f"{cmd[-1]}: {proc.stderr[:400]}")
        after = {p: md5(p) for p in fixture_files()}
        self.assertEqual(before, after)


class StdlibOnlyTests(unittest.TestCase):
    def test_stdlib_only(self):
        """Every script imports only standard-library modules."""
        allowed = set(sys.stdlib_module_names)  # 3.10+
        allowed.discard("__pycache__")
        # Sibling modules in scripts/ are legitimate local imports.
        allowed |= {n[:-3] for n in os.listdir(SCRIPTS) if n.endswith(".py")}
        offenders = []
        for name in sorted(os.listdir(SCRIPTS)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    mods = [node.module or ""]
                for mod in mods:
                    root = mod.split(".")[0]
                    if root and root not in allowed:
                        offenders.append(f"{name}: {mod}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
