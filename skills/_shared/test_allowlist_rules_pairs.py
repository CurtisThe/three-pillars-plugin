"""Tests for allowlist rule shapes: bare + ' *' pairs, no other wildcard."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from allowlist_rules import RuleError, rule_matches, rule_pair, validate_rule  # noqa: E402

TP = 'python3 "$TP_ROOT"/skills/_shared/ruling_cli.py'


def test_rule_pair_bare_and_star():
    assert rule_pair(TP) == [f"Bash({TP})", f"Bash({TP} *)"]


def test_rule_pair_git_c_exact_path():
    assert rule_pair("git -C /r-wt/a status") == [
        "Bash(git -C /r-wt/a status)",
        "Bash(git -C /r-wt/a status *)",
    ]


@pytest.mark.parametrize("cmd", ["python3 */skills/_shared/x.py", "git -C /r-wt/* status"])
def test_rule_pair_refuses_wildcard_in_prefix(cmd):
    with pytest.raises(RuleError):
        rule_pair(cmd)


@pytest.mark.parametrize("rule", [
    "Bash(*)", "Bash(python3 *)", "Bash(python3:*)", "Bash(git *)", "Bash(bash *)",
    "Bash(gh *)", "Bash(tea *)", "Bash(gh pr *)", "Bash(tea pr *)", "Bash(python3 -c *)",
    "Bash(python3 */skills/_shared/x.py *)", "Bash(git -C */x status)",
    "Bash(git -C /r-wt/../x status)", "Write(/var/x)",
])
def test_validate_rule_refuses_broad(rule):
    with pytest.raises(RuleError):
        validate_rule(rule)


def test_validate_rule_accepts_pairs():
    for cmd in (TP, "git -C /r-wt/a status"):
        for r in rule_pair(cmd):
            assert validate_rule(r) is None


def test_rule_matches_documented_semantics():
    assert rule_matches("Bash(git status)", "git status")
    assert not rule_matches("Bash(git status)", "git status -s")
    assert rule_matches("Bash(git log *)", "git log")
    assert rule_matches("Bash(git log *)", "git log -5")
    assert not rule_matches("Bash(git log *)", "git logs")
    assert rule_matches("Bash(git log * --outp*)", "git log -5 --outp=/x")
    assert not rule_matches("Bash(git log * --outp*)", "git log --outp=/x")
