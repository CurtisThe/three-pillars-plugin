"""test_gate_stamp_trust.py — the ci_local_stamp is tighten-only under an
untrusted config (impl-audit finding F1, consumer-repo-parity).

The W4 origin binding discards a committed config whose origin does not match
the PR repo (or whose check raised) to `{}`. Since Task 2.2 made the stamp
default-OFF, `{}` would OMIT the stamp — a fail-closed regression. The rule:

  * untrusted config declaring a non-blank `ci.gate_command` → stamp REQUIRED
    (an untrusted `review.require_ci_local_stamp: false` is IGNORED — untrusted
    config may only turn the stamp ON);
  * untrusted config with an explicit `review.require_ci_local_stamp: true`
    → stamp REQUIRED even with no command (an opt-in only tightens — impl-audit
    attempt 2, A2-F2); only a literal `true` counts;
  * untrusted config with no command and no `true` opt-in → OMITTED, reason
    names the untrusted binding (never the misleading "no ci.gate_command
    declared");
  * absent config → OMITTED (the default consumer);
  * present-but-fatal / unreadable config → INDETERMINATE (never OMITTED).

Live-mode cases run `evaluate_gate(pr_url, repo_root=...)` with NO runners (so
the gate is a full live gate) and every network-bound seam monkeypatched.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import deterministic_gate as dg  # noqa: E402
import gate_roster  # noqa: E402

PR_URL = "https://github.com/o/r/pull/1"
_CMD = "python3 -m pytest -q"
_QUIET = {"expects_copilot": False, "require_human_approval": False,
          "require_review_proof": False}


def _git(args, cwd) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path, origin: str, config: "dict | str | None") -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@t.test"], root)
    _git(["config", "user.name", "t"], root)
    _git(["remote", "add", "origin", origin], root)
    (root / "README").write_text("x\n")
    if config is not None:
        (root / ".three-pillars").mkdir()
        text = config if isinstance(config, str) else json.dumps(config)
        (root / ".three-pillars" / "config.json").write_text(text)
    _git(["add", "-A"], root)
    _git(["commit", "-qm", "init"], root)
    return root


@pytest.fixture
def live(monkeypatch):
    """Neutralise every network-bound live seam; the gate stays in live mode."""
    from deterministic_gate import GateVerdict, PredicateResult
    import fragility_predicate
    import proof_predicate

    def _pass(name):
        return lambda *a, **k: PredicateResult(name, GateVerdict.PASS, "stub")

    monkeypatch.setattr(dg, "_live_pr_state_fn", lambda url: {
        "mergeable": "MERGEABLE", "headRefOid": "deadbeef", "statusCheckRollup": []})
    monkeypatch.setattr(dg, "_default_threads_fn", lambda url: [])
    monkeypatch.setattr(dg, "pred_copilot_on_head", _pass("copilot_on_head"))
    monkeypatch.setattr(dg, "pred_human_approved", _pass("human_approved"))
    monkeypatch.setattr(proof_predicate, "pred_review_proof_on_head",
                        _pass("review_proof_on_head"))
    _frag = _pass("fragility_clear")()  # the synthetic deadbeef head is not in the repo
    monkeypatch.setattr(fragility_predicate, "roster_block", lambda **k: (
        [_frag], [gate_roster.RosterEntry.from_result(_frag)]))
    monkeypatch.setattr(gate_roster, "derive_base_ref", lambda url: None)


@pytest.fixture
def otherwise_pass(live, monkeypatch):
    """`live`, plus every non-stamp predicate driven to PASS (a green check
    rollup, a resolvable base ref whose fetch is faked, a PASS balloon), so
    the folded verdict is decided by `ci_local_stamp` ALONE — a stamp kept
    out of the fold (roster-only) would read PASS, not be masked."""
    from deterministic_gate import GateVerdict, PredicateResult
    import diff_balloon_guard

    monkeypatch.setattr(dg, "_live_pr_state_fn", lambda url: {
        "mergeable": "MERGEABLE", "headRefOid": "deadbeef",
        "statusCheckRollup": [{"conclusion": "SUCCESS"}]})
    monkeypatch.setattr(gate_roster, "derive_base_ref", lambda url: "main")
    real_run = subprocess.run

    def _run(cmd, *a, **k):
        if list(cmd[:1]) == ["git"] and "fetch" in cmd and "origin" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(diff_balloon_guard, "pred_diff_not_ballooned",
                        lambda **k: PredicateResult("diff_not_ballooned",
                                                    GateVerdict.PASS, "stub"))


def _decided_by_stamp(outcome, verdict, marker):
    """The verdict is `verdict` and the stamp is the ONLY blocking predicate."""
    blocking = [p.name for p in outcome.blocking]
    assert blocking == ["ci_local_stamp"], (
        f"{marker}: the stamp is not the sole folded blocker: {blocking!r}")
    assert outcome.verdict == verdict, (
        f"{marker}: verdict {outcome.verdict!r} is not {verdict!r}")


def _entry(outcome, name):
    found = [e for e in (outcome.roster or ()) if e.name == name]
    assert len(found) == 1, f"{name}: {outcome.roster!r}"
    return found[0]


def _cfg(*, command=None, review=None):
    cfg = {"schema_version": 1, "review": dict(_QUIET, **(review or {})),
           "ci": {"expects_github_checks": False}}
    if command is not None:
        cfg["ci"]["gate_command"] = command
    return cfg


def test_live_mismatch_declared_command_fails_not_omitted(tmp_path, otherwise_pass):
    root = _repo(tmp_path, "https://github.com/other/repo.git", _cfg(command=_CMD))
    outcome = dg.evaluate_gate(PR_URL, repo_root=str(root))
    mark = "STAMP-TRUST-MISMATCH"
    binding = _entry(outcome, "config_root_binding")
    assert binding.status == "INDETERMINATE", f"{mark}: binding {binding!r}"
    stamp = _entry(outcome, "ci_local_stamp")
    assert stamp.status == "FAIL", f"{mark}: stamp not FAIL: {stamp!r}"
    assert _CMD in stamp.detail, f"{mark}: FAIL detail omits the command: {stamp!r}"
    _decided_by_stamp(outcome, dg.GateVerdict.FAIL, mark)


def test_live_host_alias_origin_declared_command_still_required(tmp_path, live):
    """An SSH host-alias origin parses to None (binding untrusted) — the parser is
    NOT broadened (nor fooled by a look-alike host); the committed gate_command
    still requires the stamp."""
    mark = "STAMP-TRUST-HOST-ALIAS"
    for i, origin in enumerate(["git@github-work:o/r.git",
                                "git@github.com.evil.example:o/r.git"]):
        (tmp_path / str(i)).mkdir()
        root = _repo(tmp_path / str(i), origin, _cfg(command=_CMD))
        outcome = dg.evaluate_gate(PR_URL, repo_root=str(root))
        binding = [e for e in outcome.roster if e.name == "config_root_binding"]
        assert len(binding) == 1 and binding[0].status == "INDETERMINATE", (
            f"{mark}: {origin} did not leave the config untrusted: {binding!r}")
        stamp = _entry(outcome, "ci_local_stamp")
        assert stamp.status == "FAIL", f"{mark}: {origin} stamp not FAIL: {stamp!r}"


def test_live_trusted_declared_command_no_stamp_names_command(tmp_path, live):
    root = _repo(tmp_path, "https://github.com/o/r.git", _cfg(command=_CMD))
    outcome = dg.evaluate_gate(PR_URL, repo_root=str(root))
    assert [e for e in outcome.roster if e.name == "config_root_binding"] == []
    stamp = _entry(outcome, "ci_local_stamp")
    assert stamp.status == "FAIL"
    assert "no ci-local stamp" in stamp.detail and _CMD in stamp.detail


def test_live_trusted_declared_command_stale_stamp_names_command(tmp_path, live):
    import ci_local_stamp
    root = _repo(tmp_path, "https://github.com/o/r.git", _cfg(command=_CMD))
    ci_local_stamp.write_stamp(root)  # stamps the real HEAD, not the PR's deadbeef
    stamp = _entry(dg.evaluate_gate(PR_URL, repo_root=str(root)), "ci_local_stamp")
    assert stamp.status == "FAIL"
    assert "stale stamp" in stamp.detail and _CMD in stamp.detail


def test_untrusted_explicit_false_is_ignored(tmp_path, live):
    root = _repo(tmp_path, "https://github.com/other/repo.git",
                 _cfg(command=_CMD, review={"require_ci_local_stamp": False}))
    stamp = _entry(dg.evaluate_gate(PR_URL, repo_root=str(root)), "ci_local_stamp")
    assert stamp.status == "FAIL", "an untrusted opt-out must not relax the stamp"


def test_trusted_explicit_false_is_honoured(tmp_path, live):
    root = _repo(tmp_path, "https://github.com/o/r.git",
                 _cfg(command=_CMD, review={"require_ci_local_stamp": False}))
    stamp = _entry(dg.evaluate_gate(PR_URL, repo_root=str(root)), "ci_local_stamp")
    mark = "STAMP-TRUST-TRUSTED-FALSE"
    assert stamp.status == "OMITTED", f"{mark}: trusted opt-out not honoured: {stamp!r}"
    assert stamp.detail == "review.require_ci_local_stamp=false", (
        f"{mark}: omit reason is not the opt-out: {stamp.detail!r}")


@pytest.mark.parametrize("origin", [
    "https://github.com/other/repo.git",   # mismatched origin
    "git@github-work:o/r.git",             # host-alias origin (parses to None)
], ids=["mismatched", "host-alias"])
def test_untrusted_explicit_true_without_command_fails_not_omitted(tmp_path, live, origin):
    """A2-F2: an untrusted `require_ci_local_stamp: true` is an opt-IN — honoured."""
    root = _repo(tmp_path, origin, _cfg(review={"require_ci_local_stamp": True}))
    outcome = dg.evaluate_gate(PR_URL, repo_root=str(root))
    stamp = _entry(outcome, "ci_local_stamp")
    assert stamp.status == "FAIL", stamp
    assert outcome.verdict != dg.GateVerdict.PASS


def test_untrusted_no_command_omits_with_binding_reason(tmp_path, live):
    root = _repo(tmp_path, "https://github.com/other/repo.git", _cfg())
    stamp = _entry(dg.evaluate_gate(PR_URL, repo_root=str(root)), "ci_local_stamp")
    assert stamp.status == "OMITTED"
    assert "config untrusted by origin binding" in stamp.detail
    assert "no ci.gate_command declared" not in stamp.detail
    assert "require_ci_local_stamp" in stamp.detail


def test_binding_exception_declared_command_still_required(tmp_path, live, monkeypatch):
    root = _repo(tmp_path, "https://github.com/o/r.git", _cfg(command=_CMD))

    def _boom(_url):
        raise RuntimeError("synthetic binding failure")
    monkeypatch.setattr(dg, "_parse_github_owner_repo", _boom)
    outcome = dg.evaluate_gate(PR_URL, repo_root=str(root))
    mark = "STAMP-TRUST-BINDING-RAISED"
    binding = _entry(outcome, "config_root_binding")
    assert "unexpected error" in binding.detail, f"{mark}: no error note: {binding!r}"
    stamp = _entry(outcome, "ci_local_stamp")
    assert stamp.status == "FAIL", f"{mark}: stamp not FAIL after a raise: {stamp!r}"


def test_absent_config_omits(tmp_path, live):
    root = _repo(tmp_path, "https://github.com/o/r.git", None)
    stamp = _entry(dg.evaluate_gate(PR_URL, repo_root=str(root)), "ci_local_stamp")
    assert stamp.status == "OMITTED"
    assert stamp.detail.startswith("no ci.gate_command declared")


_BROKEN_CONFIGS = {
    "no-schema-version": {"ci": {"gate_command": _CMD}},
    "future-schema-version": {"schema_version": 99},
    "bad-json": "{not json",
    "non-object": "[1, 2]",
}


def test_fatal_or_unreadable_config_is_indeterminate(tmp_path, otherwise_pass):
    """One node over every broken shape (a mutation that breaks several fails
    this one testcase, never several): each makes the stamp INDETERMINATE and
    — every other predicate PASS — the verdict INDETERMINATE by the stamp."""
    for label, config in _BROKEN_CONFIGS.items():
        mark = f"STAMP-TRUST-BROKEN-CONFIG[{label}]"
        (tmp_path / label).mkdir()
        root = _repo(tmp_path / label, "https://github.com/o/r.git", config)
        outcome = dg.evaluate_gate(PR_URL, repo_root=str(root))
        stamp = _entry(outcome, "ci_local_stamp")
        assert stamp.status == "INDETERMINATE", f"{mark}: stamp {stamp!r}"
        assert "config" in stamp.detail, f"{mark}: detail {stamp.detail!r}"
        _decided_by_stamp(outcome, dg.GateVerdict.INDETERMINATE, mark)


def test_stamp_requirement_unit_table():
    req = gate_roster._stamp_requirement
    assert req({}, None)[0] == "omit"
    assert req({"ci": {"gate_command": "x"}}, None)[:2] == ("required", "x")
    untrusted = ("untrusted", {"ci": {"gate_command": "make ci"},
                               "review": {"require_ci_local_stamp": False}})
    assert req({}, untrusted)[:2] == ("required", "make ci")
    assert req({}, ("untrusted", {"review": {"require_ci_local_stamp": True}}))[0] == "required"
    assert req({}, ("untrusted", {"review": {"require_ci_local_stamp": "yes"}}))[0] == "omit"
    assert req({}, ("untrusted", {"review": {"require_ci_local_stamp": 1}}))[0] == "omit"
    assert req({}, ("untrusted", {"ci": {"gate_command": "  "}}))[0] == "omit"
    assert req({}, ("broken", "schema_version missing"))[0] == "indeterminate"
