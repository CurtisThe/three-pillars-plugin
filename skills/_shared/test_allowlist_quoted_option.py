"""A quoted or split option must match no allow rule: git log and git diff ship as exact shapes."""
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import allowlist_rules  # noqa: E402
import allowlist_settings  # noqa: E402

SKILLS = Path(allowlist_settings.__file__).resolve().parents[1]

LOG_SHAPES = [
    "git log", "git log --oneline", "git log --oneline -5", "git log --oneline -10",
    "git log -1", "git log -5",
]
DIFF_SHAPES = [
    "git diff", "git diff --stat", "git diff --name-only", "git diff --shortstat",
    "git diff --cached", "git diff --cached --stat", "git diff --cached --name-only",
]
QUOTED = [
    'git log -1 --format=x "--output=/x"',
    "git log -1 --format=x '--output=/x'",
    'git diff "--output=/x"',
    'git -C /r log -1 "--output=/x"',
    'git log --out""put=/x',
]


def _rules():
    entries = allowlist_settings.entries_for(allowlist_settings.load(), "github", SKILLS.parent)
    return allowlist_settings.expand(entries, roots=['"$TP_ROOT"/'])


def _hit(rules, text):
    return [r for r in rules if allowlist_rules.rule_matches(r, text)]


def test_quoted_options_match_no_allow_rule():
    rules = _rules()
    for text in QUOTED:
        assert _hit(rules, text) == [], text


def test_quoted_options_slip_past_deny_globs_so_allow_must_not_match():
    deny = allowlist_settings.deny_rules(allowlist_settings.load())
    for text in QUOTED:
        assert not _hit(deny, text), text


def test_no_wildcard_rule_for_log_or_diff():
    for r in _rules():
        words = r[len("Bash("):-1].split()
        if words[:1] == ["git"] and ("log" in words or "diff" in words):
            assert "*" not in r, r


def test_enumerated_shapes_still_match():
    rules = _rules()
    for shape in LOG_SHAPES + DIFF_SHAPES:
        assert _hit(rules, shape), shape


def test_enumerated_shapes_are_safe():
    for shape in LOG_SHAPES + DIFF_SHAPES:
        assert allowlist_rules.screen(shlex.split(shape)) is None, shape
        assert not any(bad in shape for bad in ("--output", "--ext-diff", " -O", "..", '"', "'", "$")), shape
        allowlist_rules.validate_rule(f"Bash({shape})")
