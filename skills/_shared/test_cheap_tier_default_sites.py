"""test_cheap_tier_default_sites.py — the cheap-tier argument lines of the two
teardown-chain skills resolve through the shared default CLI.

design: cheap-tier-default-flag-everywhere (Task 1.5)

`tp-merge-from-main` and `tp-post-merge` each document ONE `--cheap-tier`
argument line that names `skills/_shared/cheap_tier_default.py`; running the
command it documents over a temp repo prints `on` for every input (one-cheap-engine
3.6: the flags and `cheap_tier.default_run_flag` are deprecated and add one
`deprecated:` line each on stderr) and still reports the drop warning for an
invalid block. The cheap-tier site guard stays clean and `tp-pr-iterate`/`tp-pr-fix`
remain explicit-flag-only.

Imports `test_cheap_tier_sites.py`'s helpers; that file holds the guard itself.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from test_cheap_tier_sites import ROOT, argument_hint, find_violations  # noqa: E402

import pytest  # noqa: E402

FROM_MAIN = ROOT / "skills" / "tp-merge-from-main" / "SKILL.md"
POST_MERGE = ROOT / "skills" / "tp-post-merge" / "SKILL.md"
LINE_PREFIX = "- `--cheap-tier[=ab]` | `--no-cheap-tier` (optional, deprecated)"
RESOLVER_RE = re.compile(r'"\$TP_ROOT"/(skills/_shared/cheap_tier_default\.py) --root ')

PR_ITERATE = ROOT / "skills" / "tp-pr-iterate" / "SKILL.md"
PR_FIX = ROOT / "skills" / "tp-pr-fix" / "SKILL.md"

# (config block, CLI flags, resolved mode on stdout, drop warning on stderr, `deprecated:` lines)
UNSET = ({}, [], "on", False, 0)
DEFAULT_AB = ({"cheap_tier": {"default_run_flag": "ab"}}, [], "on", False, 1)
EXPLICIT_OFF = ({"cheap_tier": {"default_run_flag": "off"}}, [], "on", False, 1)
TYPED_ON = ({"cheap_tier": {"default_run_flag": "ab"}}, ["--cheap-tier"], "on", False, 2)
TYPED_OFF = ({"cheap_tier": {"default_run_flag": "ab"}}, ["--no-cheap-tier"], "on", False, 2)
INVALID_BLOCK = ({"cheap_tier": {"default_run_flag": "AB"}}, [], "on", True, 0)
CASES = [UNSET, DEFAULT_AB, EXPLICIT_OFF, TYPED_ON, TYPED_OFF, INVALID_BLOCK]


def _argument_line(path: Path) -> str:
    """The file's single `--cheap-tier` argument line."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line.startswith(LINE_PREFIX)]
    assert len(lines) == 1, f"expected one line starting {LINE_PREFIX!r}, found {len(lines)}"
    return lines[0]


def _config(root: Path, block: dict) -> None:
    path = root / ".three-pillars" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **block}), encoding="utf-8")


@pytest.mark.parametrize("path", [FROM_MAIN, POST_MERGE],
                         ids=["tp-merge-from-main", "tp-post-merge"])
def test_one_argument_line_per_skill(path: Path):
    line = _argument_line(path)
    assert 'python3 "$TP_ROOT"/skills/_shared/cheap_tier_default.py --root ' in line
    assert "cheap_tier.default_run_flag" in line
    assert "[--cheap-tier[=ab]]" in argument_hint(path)


def test_from_main_forwards_bare_cheap_tier():
    line = _argument_line(FROM_MAIN)
    assert "step 8 forwards bare `--cheap-tier`" in line
    assert "`--no-cheap-tier` when empty" not in line


@pytest.mark.parametrize("path", [FROM_MAIN, POST_MERGE],
                         ids=["tp-merge-from-main", "tp-post-merge"])
@pytest.mark.parametrize("case", CASES,
                         ids=["unset", "default_ab", "explicit_off", "typed_on",
                              "typed_off", "invalid_block"])
def test_documented_command_resolves(path: Path, case, tmp_path: Path):
    block, flags, expected, dropped, deprecated = case
    match = RESOLVER_RE.search(_argument_line(path))
    assert match, "the argument line does not name the resolver CLI"
    _config(tmp_path, block)
    proc = subprocess.run(
        [sys.executable, str(ROOT / match.group(1)), "--root", str(tmp_path), *flags],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == expected
    assert ("dropped cheap_tier" in proc.stderr) is dropped
    assert proc.stderr.count("deprecated:") == deprecated


def test_site_guard_stays_clean():
    assert find_violations(ROOT) == []


DEFAULT_NEEDLES = ("cheap_tier_default", "default_cheap_tier", "default_run_flag")


def _default_hits(text):
    """Needles that would mean a skill applies the repo cheap-tier default."""
    return [n for n in DEFAULT_NEEDLES if n in text]


def test_default_needles_catch_resolver_references():
    assert _default_hits("via launch_design_run.default_cheap_tier") == ["default_cheap_tier"]
    assert _default_hits("the shared `cheap_tier.default_run_flag` resolver") == ["default_run_flag"]


def test_pr_skills_stay_explicit_only():
    for path in (PR_ITERATE, PR_FIX):
        for needle in _default_hits(path.read_text(encoding="utf-8")):
            rel = path.relative_to(ROOT)
            pytest.fail(f"{rel} applies the repo cheap-tier default via {needle!r}")
