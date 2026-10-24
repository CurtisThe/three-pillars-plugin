"""Tests for the reviewed recommended allow list and its expansion into rules."""
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import allowlist_rules  # noqa: E402
import allowlist_settings  # noqa: E402

SKILLS = Path(allowlist_settings.__file__).resolve().parents[1]

CORE_SCRIPTS = {
    "design_run_send.py", "ruling_cli.py",
    "context_rollover_drive.py", "worker_root.py", "merge_driver.py",
    "sync_gate.py", "gate_cli.py", "generator_catalog.py",
    "sweep_candidates.py", "bypass_check.py",
}
PRO_SCRIPTS = set()  # the pro list ships empty: both fleet scripts reach the launcher
GIT_VERBS = ["status", "add", "commit", "merge", "worktree list"]
FETCH_EXACT = {"git fetch", "git fetch origin", "git fetch -q origin"}
LOG_DIFF_SHAPES = [
    "git log", "git log --oneline", "git log --oneline -5", "git log --oneline -10",
    "git log -1", "git log -5", "git diff", "git diff --stat", "git diff --name-only",
    "git diff --shortstat", "git diff --cached", "git diff --cached --stat",
    "git diff --cached --name-only",
]
LOG_DIFF_EXACT = set(LOG_DIFF_SHAPES)
KNOWN_UNCOVERED = {
    ("skills/tp-merge-from-main/SKILL.md", "merge_driver.py"): "$(git rev-parse) argument",
    ("skills/tp-merge-from-main/SKILL.md", "sync_gate.py"): "$(git rev-parse) argument",
    ("skills/tp-merge-from-main/SKILL.md", "gate_cli.py"): '"$TP_SEAT_ROOT" root form',
}
CALL_RE = re.compile(r'python3 "\$[A-Z_]+"/skills/\S+\.py')


def _allow():
    return allowlist_settings.load()["allow"]


def _expanded(forge="github", roots=('"$TP_ROOT"/', "/opt/tp/")):
    entries = allowlist_settings.entries_for(allowlist_settings.load(), forge, SKILLS.parent)
    return allowlist_settings.expand(entries, roots=list(roots))


def _base(rule):
    inner = rule[len("Bash("):-1]
    return inner[:-2] if inner.endswith(" *") else inner


def test_every_entry_has_comment_and_cmd():
    rec = allowlist_settings.load()
    assert rec["allow"]
    for e in rec["allow"]:
        assert e.get("cmd")
        assert e.get("comment") and "\n" not in e["comment"]
    assert rec["deny"]
    for e in rec["deny"]:
        assert e.get("rule") and e.get("comment")


def test_initial_list_present():
    allow = _allow()
    names = {Path(e["script"]).name for e in allow if "script" in e}
    assert CORE_SCRIPTS <= names
    if allowlist_settings.RECOMMENDED_PRO.exists():
        assert PRO_SCRIPTS <= names
    cmds = {e["cmd"] for e in allow}
    for v in GIT_VERBS:
        assert f"git {v}" in cmds
    assert not [c for c in cmds if c.startswith("git -C")]
    forge = {e["cmd"]: e.get("forge") for e in allow}
    for c in ("gh pr view", "gh pr list", "gh pr checks"):
        assert forge[c] == "github"
    for c in ("tea pr list", "tea pulls list"):
        assert forge[c] == "gitea"
    exact = {e["cmd"] for e in allow if e.get("exact")}
    assert exact == FETCH_EXACT | LOG_DIFF_EXACT
    assert all(e.get("exact") is True for e in allow if e["cmd"] in FETCH_EXACT | LOG_DIFF_EXACT)
    for v in ("log", "diff"):
        assert f"git {v}" in cmds
        assert sum(1 for c in LOG_DIFF_SHAPES if c.startswith(f"git {v}")) <= 8


def test_exclusions_absent():
    for e in _allow():
        # verify_merged.py: --gh-cmd runs the program it names; a trailing-` *` rule would let it through
        # launch_design_run.py: reaches the pushing launcher with a --brief FILE source
        # fleet_roster.py: reaches the pushing launcher with a --brief FILE source (add --brief)
        # fleet_churn_watch.py: reaches the pushing launcher with a --brief FILE source (claimed runs)
        for bad in ("teardown.py", "design_run_tmux.py", "tmux", "verify_merged.py",
                    "launch_design_run.py", "fleet_roster.py", "fleet_churn_watch.py"):
            assert bad not in e["cmd"]


def test_scripts_exist_or_skill_absent():
    for e in _allow():
        script = e.get("script")
        if not script:
            continue
        skill_dir = SKILLS / script.split("/")[1]
        assert (SKILLS.parent / script).is_file() or not skill_dir.exists(), script


def test_no_entry_screened():
    for forge in ("github", "gitea"):
        for rule in _expanded(forge):
            base = _base(rule)
            assert allowlist_rules.screen(shlex.split(base)) is None, rule


def test_expand_pairs_and_roots():
    rules = _expanded()
    for want in (
        'Bash(python3 "$TP_ROOT"/skills/_shared/ruling_cli.py)',
        'Bash(python3 "$TP_ROOT"/skills/_shared/ruling_cli.py *)',
        "Bash(python3 /opt/tp/skills/_shared/ruling_cli.py *)",
        "Bash(git status)",
        "Bash(git fetch -q origin)",
    ):
        assert want in rules
    assert not any(r.startswith("Bash(tea") for r in rules)
    assert not any(r.startswith("Bash(git -C") for r in rules)
    assert not any(r.startswith("Bash(git fetch") and r.endswith(" *)") for r in rules)
    assert len(rules) == len(set(rules))
    for r in rules:
        assert allowlist_rules.validate_rule(r) is None
        assert "*" not in _base(r)


def test_expand_gitea_has_tea_not_gh():
    rules = _expanded("gitea")
    assert "Bash(tea pr list)" in rules
    assert not any(r.startswith("Bash(gh ") for r in rules)


def test_root_forms():
    assert allowlist_settings.root_forms(Path("/opt/tp"), Path("/home/u/app")) == ['"$TP_ROOT"/', "/opt/tp/"]
    assert allowlist_settings.root_forms(Path("/r"), Path("/r")) == ['"$TP_ROOT"/', "/r/"]


DENY_WANT = [
    "Bash(git fetch --upl*)", "Bash(git fetch * --upl*)",
    "Bash(git log --outp*)", "Bash(git log * --outp*)",
    "Bash(git diff --outp*)", "Bash(git diff * --outp*)",
    "Bash(git -C * fetch --upl*)", "Bash(git -C * fetch * --upl*)",
    "Bash(git -C * log --outp*)", "Bash(git -C * log * --outp*)",
    "Bash(git -C * diff --outp*)", "Bash(git -C * diff * --outp*)",
]


def test_deny_rules():
    rec = allowlist_settings.load()
    assert allowlist_settings.deny_rules(rec) == DENY_WANT
    for e in rec["deny"]:
        if e["rule"].startswith("Bash(git -C"):
            assert "over-match" in e["comment"]


def test_deny_rules_catch_abbreviations_and_spare_messages():
    deny = allowlist_settings.deny_rules(allowlist_settings.load())

    def hit(text):
        return any(allowlist_rules.rule_matches(r, text) for r in deny)

    caught = [
        "git fetch --upl=evil /p", "git log --outp=/etc/x", "git log -5 --output=/etc/x",
        "git diff --outp=/etc/x", "git -C /r log -5 --outp=/etc/x", "git -C /r log --output=/etc/x",
        "git -C /r-wt/a diff --outp=/x", "git -C /r fetch --upl=evil /p",
        'git -C /r commit -m "x log --outp y"',
    ]
    spared = ['git commit -m "feat: deny --output escapes"', 'git commit -m "note --upload-pack"', "git log -5"]
    # every verb x bare/-C form x option position (first, after one or two arguments) is refused
    caught += [
        f"{pre} {verb}{mid} {opt}"
        for pre in ("git", "git -C /r")
        for verb, opt in (
            ("fetch", "--upl=evil"), ("log", "--outp=/x"), ("log", "--output=/x"),
            ("diff", "--outp=/x"), ("diff", "--output=/x"),
        )
        for mid in ("", " origin", " -q origin", " HEAD~1")
    ]
    # one testcase and one message: a weakened rule fails it once, and the message carries every
    # command probed, so no reader has to rerun to see what the guard covers
    missed = [t for t in caught if not hit(t)]
    over = [t for t in spared if hit(t)]
    # each deny rule is the only one to catch at least one of those commands (none is redundant)
    idle = [
        rule for rule in deny
        if not any(
            allowlist_rules.rule_matches(rule, t)
            and not any(allowlist_rules.rule_matches(o, t) for o in deny if o != rule)
            for t in caught
        )
    ]
    assert not (missed or over or idle), (
        f"missed={missed} over-matched={over} redundant-rules={idle}; probed caught={caught} spared={spared}")


def _cut(line, start):
    text = line[start:]
    if line[:start].count("`") % 2 == 1:
        text = text.split("`", 1)[0]
    return text.rstrip().rstrip("\\").rstrip()


def test_skill_docs_calls_covered():
    rules = _expanded(roots=('"$TP_ROOT"/',))
    names = CORE_SCRIPTS | PRO_SCRIPTS
    misses = set()
    for md in sorted(SKILLS.rglob("*.md")):
        rel = md.relative_to(SKILLS.parent).as_posix()
        for line in md.read_text(encoding="utf-8").splitlines():
            for m in CALL_RE.finditer(line):
                name = m.group(0).rsplit("/", 1)[1]
                if name not in names:
                    continue
                text = _cut(line, m.start())
                bad = "$(" in text or "${" in text or "`" in text
                if bad or not any(allowlist_rules.rule_matches(r, text) for r in rules):
                    misses.add((rel, name))
    assert misses <= set(KNOWN_UNCOVERED), sorted(misses - set(KNOWN_UNCOVERED))
    assert set(KNOWN_UNCOVERED) <= misses, sorted(set(KNOWN_UNCOVERED) - misses)
