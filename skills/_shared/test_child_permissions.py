"""Tests for child_permissions.py — the shipped allow/deny lists and per-repo additions.

strata-classifier-cost-followups task 1.1: design §A1 pins the exact `--allowedTools` /
`--disallowedTools` values a Strata child receives (a closed spec set), §A2 the per-repo
`strata_spawn.permissions` additions. The tests below restate those examples: the deny
list element by element in order, the worktree-scoped `Edit` allow rule with the `//`
absolute prefix (task 2.5: a `Write(<path>)` allow rule is never honoured by the CLI, so
there is exactly one such rule and no allow rule is a `Write(...)` rule at all), appended
extras, invalid-entry warnings, the shipped deny
list never shrinking via config, and the `argv_flags` rendering with one argv element
per rule. Nothing here runs a subprocess.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_permissions as cp  # noqa: E402

# design §A1: the exact shipped deny list, in order.
# tp-allow-fragile: design §A1 ships this exact list as the CLI --disallowedTools policy (closed spec set, not a filter over open input)
EXPECTED_DENY = [
    "Bash(rm -r*)", "Bash(rm -fr*)", "Bash(rm -rf*)", "Bash(rm -Rf*)",
    "Bash(kill*)", "Bash(pkill*)", "Bash(killall*)",
    "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push --delete*)",
    "Bash(git branch -D*)", "Bash(git push origin :*)",
    "Bash(gh pr merge*)", "Bash(gh repo delete*)",
    "Bash(tea pr merge*)", "Bash(tea repo delete*)",
    "Bash(curl * | sh*)", "Bash(curl * | bash*)", "Bash(wget * | sh*)",
    "Edit(.claude/settings.json)", "Write(.claude/settings.json)",
    "Edit(.claude/settings.local.json)", "Write(.claude/settings.local.json)",
    "Edit(.claude/agents/**)", "Write(.claude/agents/**)",
    "Edit(.claude/commands/**)", "Write(.claude/commands/**)",
    "Edit(.claude/hooks/**)", "Write(.claude/hooks/**)",
    "Edit(.claude/skills/**)", "Write(.claude/skills/**)",
    "Edit(**/.git/hooks/**)", "Write(**/.git/hooks/**)",
    "Edit(**/.git/config)", "Write(**/.git/config)",
]


def test_default_deny_is_the_design_A1_list_in_order():
    assert cp.DEFAULT_DENY == EXPECTED_DENY, \
        "shipped deny list drifted from the A1 spec list (same entries, same order)"


def test_no_broad_dot_claude_deny_rule():
    # §A1: not all of `.claude/**` — S2 Strata drafters wrote scratch under the legacy
    # `.claude/worktrees/<slot>-<id>/`, and under dontAsk a deny beats the worktree allow.
    broad = {"Edit(.claude/**)", "Write(.claude/**)"}
    assert not [rule for rule in cp.DEFAULT_DENY if rule in broad]


def test_allow_rule_covers_the_scratch_paths_and_no_deny_names_them(tmp_path):
    # launch-role-precedence task 3.5: the prompt copy and the smoke file live under
    # `<cwd>/.tp-scratch/child-spawn/`, inside the cwd the one `Edit(//<cwd>/**)` rule covers
    # (an `Edit` path rule covers `Write` too). No shipped deny entry may name that scratch
    # base: under dontAsk a deny beats the allow, and the deny list itself stays unchanged.
    allow, deny, _ = cp.rules(str(tmp_path), {})
    assert deny == EXPECTED_DENY
    assert not [rule for rule in deny if ".tp-scratch" in rule]
    (rule,) = [r for r in allow if r.startswith("Edit(//")]
    covered = rule[len("Edit(//"):-len("/**)")]
    for name in ("ab12cd34.prompt.md", "smoke-0123456789abcdef.txt"):
        target = (tmp_path / ".tp-scratch" / "child-spawn" / name).resolve().as_posix().lstrip("/")
        assert target.startswith(covered + "/"), (target, covered)


def _wt_rules(path):
    """The worktree-scoped allow rule §A1 adds for `path` — `Edit` only (task 2.5)."""
    scoped = path.as_posix().lstrip("/") + "/**"
    return [f"Edit(//{scoped})"]


def test_rules_default_allow_and_deny():
    # §A1's example verbatim: a child whose cwd is /w/att.
    allow, deny, warnings = cp.rules("/w/att", {})
    assert allow == ["Agent", "Read", "Grep", "Glob", "Bash(*)", "Edit(//w/att/**)"]
    assert deny == cp.DEFAULT_DENY
    assert warnings == []


def test_no_allow_rule_is_a_write_path_rule():
    # Task 2.5 live proof (child e2a87eda, CLI 2.1.296, dontAsk): `Write(//<dir>/**)` is
    # refused; `Edit(//<dir>/**)` lets the child Write in `<dir>`. An allow rule that starts
    # with `Write(` is therefore dead weight — and a misleading one.
    allow, _, _ = cp.rules("/w/att", {})
    assert not [rule for rule in allow if rule.startswith("Write(")]


def test_rules_resolves_relative_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allow, _, _ = cp.rules("att", {})
    # The relative cwd becomes absolute first: `//` + the path with its leading `/` stripped.
    wt = Path("att").resolve().as_posix().lstrip("/")
    assert f"Edit(//{wt}/**)" in allow
    assert not [r for r in allow if r.startswith("Write(")]


def test_nested_worktree_cwd_gets_one_edit_rule_and_full_deny(tmp_path):
    # Task 2.5's measured case: a cwd nested at `<repo>/.claude/worktrees/x`. The one
    # worktree rule is the `Edit(//…)` that binds for every file-editing tool, and the
    # shipped deny still carries the settings-file entries (their `Write(...)` pair stays
    # as no-op belt-and-braces beside the `Edit(...)` entry that binds).
    wt = tmp_path / "repo" / ".claude" / "worktrees" / "x"
    wt.mkdir(parents=True)
    allow, deny, warnings = cp.rules(str(wt), {})
    assert allow == cp.DEFAULT_ALLOW_TOOLS + _wt_rules(wt)
    assert deny == cp.DEFAULT_DENY
    assert warnings == []
    for path in (".claude/settings.json", ".claude/settings.local.json"):
        assert f"Edit({path})" in deny and f"Write({path})" in deny


def test_rules_appends_per_repo_extras(tmp_path):
    config = {"strata_spawn": {"permissions": {
        "allow_extra": ["WebFetch"], "deny_extra": ["Bash(npm publish*)"]}}}
    allow, deny, warnings = cp.rules(str(tmp_path), config)
    assert allow == cp.DEFAULT_ALLOW_TOOLS + _wt_rules(tmp_path) + ["WebFetch"]
    assert deny == cp.DEFAULT_DENY + ["Bash(npm publish*)"]
    assert warnings == []


def test_rules_duplicate_extra_added_once(tmp_path):
    config = {"strata_spawn": {"permissions": {
        "allow_extra": ["WebFetch", "WebFetch"],
        "deny_extra": ["Bash(npm publish*)", "Bash(npm publish*)"]}}}
    allow, deny, warnings = cp.rules(str(tmp_path), config)
    assert allow.count("WebFetch") == 1
    assert deny.count("Bash(npm publish*)") == 1
    assert warnings == []


def test_rules_skips_invalid_entries_with_one_warning_each(tmp_path):
    config = {"strata_spawn": {"permissions": {
        "allow_extra": ["", 42, "rm -rf", "Bash("],
        "deny_extra": ["Bash(npm publish*)", "bad("]}}}
    allow, deny, warnings = cp.rules(str(tmp_path), config)
    assert allow == cp.DEFAULT_ALLOW_TOOLS + _wt_rules(tmp_path)
    assert deny == cp.DEFAULT_DENY + ["Bash(npm publish*)"]
    assert len(warnings) == 5
    for w in warnings:
        assert w.startswith("W: strata_spawn.permissions: skipped invalid rule ")


def test_rules_valid_shape_covers_mcp_tool_names(tmp_path):
    config = {"strata_spawn": {"permissions": {
        "allow_extra": ["mcp__x__y", "mcp__x__y(a:b)", "Read"],
        "deny_extra": []}}}
    allow, _, warnings = cp.rules(str(tmp_path), config)
    # "Read" repeats a shipped entry, so it is not added twice.
    assert allow == cp.DEFAULT_ALLOW_TOOLS + _wt_rules(tmp_path) + ["mcp__x__y", "mcp__x__y(a:b)"]
    assert warnings == []


def test_rules_unknown_key_warns_and_shipped_deny_unchanged(tmp_path):
    config = {"strata_spawn": {"permissions": {"deny": [], "allow_extra": ["WebFetch"]}}}
    allow, deny, warnings = cp.rules(str(tmp_path), config)
    assert deny == cp.DEFAULT_DENY
    assert allow == cp.DEFAULT_ALLOW_TOOLS + _wt_rules(tmp_path) + ["WebFetch"]
    assert len(warnings) == 1
    assert warnings[0].startswith("W: strata_spawn.permissions: skipped invalid rule ")


def test_config_cannot_remove_a_shipped_deny_entry(tmp_path):
    config = {"strata_spawn": {"permissions": {"deny_extra": [], "allow_extra": [
        "Bash(rm -rf*)", "Bash(pkill*)"]}}}
    _, deny, _ = cp.rules(str(tmp_path), config)
    assert cp.DEFAULT_DENY == deny[:len(cp.DEFAULT_DENY)]
    assert "Bash(pkill*)" in deny  # an allow extra never removes the shipped deny


def test_argv_flags_renders_one_element_per_rule():
    assert cp.argv_flags("dontAsk", ["Read", "Bash(*)"], ["Bash(kill*)"]) == [
        "--permission-mode", "dontAsk",
        "--allowedTools", "Read", "Bash(*)",
        "--disallowedTools", "Bash(kill*)",
    ]


def test_argv_flags_rejects_modes_outside_modes_constant():
    for mode in ("bypassPermissions", "default", ""):
        try:
            cp.argv_flags(mode, ["Read"], [])
        except ValueError:
            continue
        raise AssertionError(f"argv_flags accepted {mode!r}")


def test_modes_constant():
    assert cp.MODES == ("dontAsk", "auto")


def test_load_config_returns_raw_json(tmp_path):
    cfg_dir = tmp_path / "repo"
    (cfg_dir / ".three-pillars").mkdir(parents=True)
    (cfg_dir / ".three-pillars" / "config.json").write_text(
        json.dumps({"strata_spawn": {"permissions": {"allow_extra": ["WebFetch"]}}}),
        encoding="utf-8")
    assert cp.load_config(str(cfg_dir)) == {
        "strata_spawn": {"permissions": {"allow_extra": ["WebFetch"]}}}


def test_load_config_absent_or_unparsable_is_empty_dict(tmp_path):
    assert cp.load_config(str(tmp_path)) == {}
    bad = tmp_path / "bad"
    (bad / ".three-pillars").mkdir(parents=True)
    (bad / ".three-pillars" / "config.json").write_text("{not json", encoding="utf-8")
    assert cp.load_config(str(bad)) == {}
