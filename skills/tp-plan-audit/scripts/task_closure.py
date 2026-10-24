#!/usr/bin/env python3
"""task_closure.py — plan-audit check: importer tests of a modified File.

design: local-sized-tasks 1.3. `closure_findings(task, root, test_files=None)`
returns one message per modified (non-`(new)`, non-test `.py`) File whose
importer tests are neither in Targets nor named in the task text.
"""
from __future__ import annotations

import configparser
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parents[2] / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import plan_files  # noqa: E402
import task_scope  # noqa: E402
import task_targets  # noqa: E402

_CACHE: dict = {}


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _CACHE:
        _CACHE[key] = path.read_text(encoding="utf-8", errors="replace")
    return _CACHE[key]


def _cfg_value(path: Path, section: str):
    try:
        cp = configparser.ConfigParser(interpolation=None)
        cp.read_string(path.read_text(encoding="utf-8"))
        return cp.get(section, "python_files", fallback=None)
    except (OSError, configparser.Error, UnicodeError):
        return None


def _toml_value(path: Path):
    try:
        import tomllib
        d = tomllib.loads(path.read_text(encoding="utf-8"))
    except (ImportError, OSError, ValueError):
        return None
    return d.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("python_files")


def discovery_globs(root) -> tuple[str, ...]:
    """Test-file globs from the repo's pytest config, else `test_*.py`."""
    root = Path(root)
    for val in (_cfg_value(root / "pytest.ini", "pytest"),
                _toml_value(root / "pyproject.toml"),
                _cfg_value(root / "tox.ini", "pytest"),
                _cfg_value(root / "setup.cfg", "tool:pytest")):
        if isinstance(val, (list, tuple)):
            val = " ".join(map(str, val))
        if isinstance(val, str) and val.split():
            return tuple(val.split())
    return ("test_*.py",)


def _git_tests(root: Path) -> list[str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--",
             *["*" + g for g in discovery_globs(root)]],
            capture_output=True, text=True, env=task_scope._git_env())
    except OSError:
        return []
    if r.returncode != 0:
        return []
    return [p for p in r.stdout.split("\0") if p]


def _binds(text: str, repo_path: str) -> bool:
    s = re.escape(Path(repo_path).stem)
    p = r"(?:[\w.]+\.)?"
    pats = (rf"^[ \t]*(?:from\s+{p}{s}\s+import\b|import\s+{p}{s}\b)",
            rf"importorskip\(\s*[\"']{p}{s}[\"']", rf"\b{s}\.py\b")
    return (repo_path in text
            or any(re.search(x, text, re.M) for x in pats))


def _named(text: str, path: str) -> bool:
    parts = path.split("/")
    return any(re.search(rf"(?<![\w/.-]){re.escape('/'.join(parts[i:]))}(?!\w)", text)
               for i in range(len(parts)))


_TARGETS_FIELD = re.compile(
    r"^[^\n]*\*\*Targets\*\*:[^\n]*"
    r"(?:\n(?![ \t]*$)(?![ \t]*(?:[-*][ \t]+)?\*\*[^*\n]+\*\*:)[^\n]*)*", re.M)


def closure_findings(task: dict, root, test_files=None) -> list[str]:
    root = Path(root)
    fields = task.get("fields", {})
    items = plan_files.parse_file_field(fields.get("File"))["items"]
    specs = task_targets.parse_targets(fields.get("Targets"))["specs"]
    targets = {x for x in specs if "::" not in x}
    globs = discovery_globs(root)
    cands = [i["path"] for i in items
             if i["marker"] != "new" and i["path"].endswith(".py")
             and not any(fnmatch.fnmatch(Path(i["path"]).name, g) for g in globs)
             and (root / i["path"]).is_file()]
    if not cands:
        return []
    tests = _git_tests(root) if test_files is None else list(test_files)
    raw = _TARGETS_FIELD.sub("", task.get("raw", ""))
    text = raw + "\n".join(str(v) for k, v in fields.items() if k != "Targets")
    out = []
    for f in cands:
        hits = [t for t in tests if t not in targets
                and not _named(text, t)
                and _binds(_read(root / t), f)]
        if hits:
            out.append(f"tests that import `{f}` are not in Targets: "
                       f"{', '.join(hits)} — add them to Targets or name "
                       f"them must stay green, untouched")
    return out
