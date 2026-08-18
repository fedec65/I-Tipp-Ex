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


NETWORK_ROOTS = {"socket", "ssl", "http", "urllib.request",
                 "urllib.error", "ftplib", "smtplib", "asyncio"}
# Pure string-handling / advisory helpers: exempt everywhere.
NETWORK_EXEMPT_PREFIXES = ("urllib.parse", "urllib.robotparser")
NETWORK_ALLOWED_SCRIPTS = {"audit_site.py", "detect_vendor.py"}


def _network_offenders(scripts_dir: str) -> list[str]:
    """Return "file: module" hits for network imports outside the allowlist."""
    offenders = []
    for name in sorted(os.listdir(scripts_dir)):
        if not name.endswith(".py"):
            continue
        if name in NETWORK_ALLOWED_SCRIPTS:
            continue
        with open(os.path.join(scripts_dir, name), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        hits = set()
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module or ""]
            for mod in mods:
                if mod.startswith(NETWORK_EXEMPT_PREFIXES):
                    continue
                if mod in NETWORK_ROOTS or \
                        mod.split(".")[0] in {"http", "socket", "ssl"}:
                    hits.add(mod)
        for h in sorted(hits):
            offenders.append(f"{name}: {h}")
    return offenders


class OfflineContractTests(unittest.TestCase):
    def test_network_imports_only_in_network_scripts(self):
        """Only audit_site.py and detect_vendor.py may import network modules."""
        self.assertEqual(_network_offenders(SCRIPTS), [])

    def test_contract_test_actually_catches_violations(self):
        """The scanner must flag a new network import in any other script."""
        poison = os.path.join(SCRIPTS, "poison_offline_contract_check.py")
        with open(poison, "w", encoding="utf-8") as fh:
            fh.write("import socket\n")
        try:
            offenders = _network_offenders(SCRIPTS)
        finally:
            os.unlink(poison)
        self.assertIn("poison_offline_contract_check.py: socket", offenders)


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
