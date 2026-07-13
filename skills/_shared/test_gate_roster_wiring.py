"""Tests for gate roster wiring: derive_base_ref and build_predicates_and_roster.

This module covers:
  - derive_base_ref (Task 1.3): happy path + error paths via injected runner
  - build_predicates_and_roster re-rooting (Task 1.4): balloon + stamp predicates
    receive the project root, not the module-relative path; fail-closed on
    unresolvable root / base.

derive_base_ref tests live here (not in test_diff_balloon_guard.py) because:
  test_diff_balloon_guard.py is grandfathered at 604 lines (over the 500 hard
  cap) and must not be extended. New balloon/wiring tests land here instead.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path setup
# ---------------------------------------------------------------------------

import sys
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


# ---------------------------------------------------------------------------
# Task 1.3: derive_base_ref tests
# ---------------------------------------------------------------------------

def test_derive_base_ref_happy():
    """Injected runner returning valid JSON → base ref name returned."""
    from diff_balloon_guard import derive_base_ref

    def happy_runner(cmd):
        return json.dumps({"baseRefName": "main"})

    result = derive_base_ref("https://github.com/o/r/pull/1", runner=happy_runner)
    assert result == "main"


def test_derive_base_ref_runner_error():
    """Runner raising an exception → None (fail-closed)."""
    from diff_balloon_guard import derive_base_ref

    def error_runner(cmd):
        raise RuntimeError("gh not found")

    result = derive_base_ref("https://github.com/o/r/pull/1", runner=error_runner)
    assert result is None


def test_derive_base_ref_bad_json():
    """Runner returning non-JSON → None."""
    from diff_balloon_guard import derive_base_ref

    def bad_json_runner(cmd):
        return "not json at all"

    result = derive_base_ref("https://github.com/o/r/pull/1", runner=bad_json_runner)
    assert result is None


def test_derive_base_ref_empty():
    """Runner returning JSON with empty baseRefName → None."""
    from diff_balloon_guard import derive_base_ref

    def empty_runner(cmd):
        return json.dumps({"baseRefName": ""})

    result = derive_base_ref("https://github.com/o/r/pull/1", runner=empty_runner)
    assert result is None


# ---------------------------------------------------------------------------
# Task 1.4: build_predicates_and_roster wiring tests
# ---------------------------------------------------------------------------

def _make_base_runners(**extra):
    """Minimal hermetic runners for build_predicates_and_roster."""
    base = {
        "pr_state_fn": lambda url: {
            "mergeable": "MERGEABLE",
            "headRefOid": "deadbeef",
            "statusCheckRollup": [],
        },
        "threads_fn": lambda url: [],
        "labels_fn": lambda url: [],
        "timeline_fn": lambda url: [],
        "head_fn": lambda url: {},
        "commits_fn": lambda url: [],
        "self_login_fn": lambda: "bot",
    }
    base.update(extra)
    return base


_HERMETIC_CONFIG = {
    "review": {"expects_copilot": False, "require_human_approval": False},
    "ci": {"expects_github_checks": False},
}


def test_balloon_indeterminate_on_unresolvable_root(monkeypatch):
    """Live balloon path with unresolvable project root → diff_not_ballooned INDETERMINATE.

    Inject balloon_sizes=None to force the live measurement path while keeping
    other runners hermetic. Monkeypatch find_project_root in gate_roster namespace.
    """
    import gate_roster

    # Patch find_project_root at the gate_roster module-level attribute
    # (placed there by the GREEN implementation; raising=False = add if absent)
    monkeypatch.setattr(gate_roster, "find_project_root", lambda: None, raising=False)

    from deterministic_gate import evaluate_gate

    # balloon_sizes=None in runners → key present → live path, but sizes=None
    runners = _make_base_runners(balloon_sizes=None)
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
        config=_HERMETIC_CONFIG,
    )
    assert outcome.roster is not None
    balloon_entries = [e for e in outcome.roster if e.name == "diff_not_ballooned"]
    assert len(balloon_entries) == 1
    entry = balloon_entries[0]
    assert entry.status == "INDETERMINATE", (
        f"Expected INDETERMINATE for unresolvable root, got {entry.status}: {entry.detail}"
    )
    assert "project root" in entry.detail.lower(), (
        f"Expected detail to mention 'project root' specifically: {entry.detail!r}"
    )


def test_balloon_indeterminate_on_unresolvable_base(monkeypatch, tmp_path):
    """Live balloon path with unresolvable base ref → diff_not_ballooned INDETERMINATE."""
    import gate_roster

    # Return a real path for project root so we get past the root check
    monkeypatch.setattr(gate_roster, "find_project_root", lambda: tmp_path, raising=False)
    # Patch derive_base_ref to return None
    monkeypatch.setattr(gate_roster, "derive_base_ref", lambda pr_url: None, raising=False)

    from deterministic_gate import evaluate_gate

    runners = _make_base_runners(balloon_sizes=None)
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
        config=_HERMETIC_CONFIG,
    )
    assert outcome.roster is not None
    balloon_entries = [e for e in outcome.roster if e.name == "diff_not_ballooned"]
    assert len(balloon_entries) == 1
    entry = balloon_entries[0]
    assert entry.status == "INDETERMINATE", (
        f"Expected INDETERMINATE for unresolvable base, got {entry.status}: {entry.detail}"
    )
    assert "base" in entry.detail.lower() or "resolve" in entry.detail.lower(), (
        f"Expected detail to mention base resolution: {entry.detail!r}"
    )


def test_balloon_indeterminate_on_fetch_failure(monkeypatch, tmp_path):
    """Live balloon path where git fetch fails → diff_not_ballooned INDETERMINATE.

    Mutation pins:
    - assert the detail contains 'could not fetch origin/' specifically
      (dropping this assertion or the escape hatch lets a mutation survive)
    - assert the fetch command was actually attempted via the call log
      (a mutation deleting the fetch step stays green without this assertion)
    """
    import gate_roster

    fetch_calls = []

    # Inject derive_base_ref_fn seam so we don't need to mock derive_base_ref attr
    def fake_derive_base_ref(pr_url):
        return "main"

    monkeypatch.setattr(gate_roster, "find_project_root", lambda: tmp_path, raising=False)

    # Patch subprocess.run inside gate_roster module to intercept fetch
    import subprocess as _subprocess
    original_run = _subprocess.run

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "fetch" in cmd:
            fetch_calls.append(cmd)

            class FakeResult:
                returncode = 1
                stdout = ""
                stderr = "fatal: could not read Username"
            return FakeResult()
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(_subprocess, "run", fake_run)

    from deterministic_gate import evaluate_gate

    runners = _make_base_runners(
        balloon_sizes=None,
        derive_base_ref_fn=fake_derive_base_ref,
    )
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
        config=_HERMETIC_CONFIG,
    )
    assert outcome.roster is not None
    balloon_entries = [e for e in outcome.roster if e.name == "diff_not_ballooned"]
    assert len(balloon_entries) == 1
    entry = balloon_entries[0]
    assert entry.status == "INDETERMINATE", (
        f"Expected INDETERMINATE on fetch failure, got {entry.status}: {entry.detail}"
    )
    # Specific assertion — 'could not fetch origin/' pins the exact error branch
    assert "could not fetch origin/" in entry.detail, (
        f"Expected detail to contain 'could not fetch origin/': {entry.detail!r}"
    )
    # Assert the fetch was actually attempted (mutation: deleting fetch step)
    assert len(fetch_calls) >= 1, (
        "Expected at least one fetch command to be attempted, but fetch_calls is empty"
    )
    fetch_cmd = fetch_calls[0]
    assert "fetch" in fetch_cmd, f"fetch_calls[0] unexpectedly missing 'fetch': {fetch_cmd}"
    assert "origin" in fetch_cmd, f"fetch command did not target origin: {fetch_cmd}"


def test_balloon_uses_origin_base_ref(monkeypatch, tmp_path):
    """Live balloon path with resolvable root+base uses origin/<base> ref."""
    import gate_roster
    import diff_balloon_guard

    monkeypatch.setattr(gate_roster, "find_project_root", lambda: tmp_path, raising=False)
    monkeypatch.setattr(gate_roster, "derive_base_ref", lambda pr_url: "main", raising=False)

    # Track what ref was passed to pred_diff_not_ballooned
    called_with = {}

    original_pred = diff_balloon_guard.pred_diff_not_ballooned

    def capturing_pred(**kwargs):
        called_with.update(kwargs)
        from deterministic_gate import GateVerdict, PredicateResult
        return PredicateResult(
            name="diff_not_ballooned",
            verdict=GateVerdict.PASS,
            detail="captured",
        )

    monkeypatch.setattr(diff_balloon_guard, "pred_diff_not_ballooned", capturing_pred)

    # Also patch subprocess to prevent actual git fetch
    import subprocess as _subprocess
    original_run = _subprocess.run

    def fake_run(cmd, **kwargs):
        if "fetch" in cmd:
            class FakeResult:
                returncode = 0
                stdout = ""
                stderr = ""
            return FakeResult()
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(_subprocess, "run", fake_run)

    from deterministic_gate import evaluate_gate

    runners = _make_base_runners(balloon_sizes=None)
    evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
        config=_HERMETIC_CONFIG,
    )

    assert "base_ref" in called_with, "pred_diff_not_ballooned was not called"
    assert called_with["base_ref"] == "origin/main", (
        f"Expected base_ref='origin/main', got {called_with.get('base_ref')!r}"
    )


def test_stamp_receives_project_root(monkeypatch, tmp_path):
    """Hermetic stamp path: pred_ci_local_stamp receives the project root path."""
    import gate_roster
    import ci_local_stamp

    stamp_repo_roots = []

    def fake_pred_ci_local_stamp(head_oid, repo_root=None, stamp=None):
        stamp_repo_roots.append(repo_root)
        from deterministic_gate import GateVerdict, PredicateResult
        return PredicateResult(
            name="ci_local_stamp",
            verdict=GateVerdict.PASS,
            detail="fake stamp pass",
        )

    monkeypatch.setattr(gate_roster, "find_project_root", lambda: tmp_path, raising=False)
    monkeypatch.setattr(ci_local_stamp, "pred_ci_local_stamp", fake_pred_ci_local_stamp)

    from deterministic_gate import evaluate_gate

    stamp_data = {"schema": 1, "head_sha": "deadbeef", "dirty": False}
    runners = _make_base_runners(stamp=stamp_data)
    evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
        config=_HERMETIC_CONFIG,
    )

    assert len(stamp_repo_roots) == 1, "pred_ci_local_stamp not called"
    assert stamp_repo_roots[0] == str(tmp_path), (
        f"Expected project root {tmp_path!r}, got {stamp_repo_roots[0]!r}"
    )


def test_no_stamp_key_hermetic_runners_stamp_is_omitted():
    """Hermetic runners with no stamp key → ci_local_stamp is OMITTED.

    running_live = not r — since r is a non-empty dict (hermetic runners),
    running_live=False and the stamp predicate is skipped entirely (OMITTED).
    This is the hermetic baseline: no stamp key + non-empty runners → OMITTED.
    """
    from deterministic_gate import evaluate_gate

    _live_style_runners = {
        "pr_state_fn": lambda url: {
            "mergeable": "MERGEABLE",
            "headRefOid": "deadbeef",
            "statusCheckRollup": [],
        },
        "threads_fn": lambda url: [],
        "labels_fn": lambda url: [],
        "timeline_fn": lambda url: [],
        "head_fn": lambda url: {},
        "commits_fn": lambda url: [],
        "self_login_fn": lambda: "bot",
        # No stamp key → stamp is NOT in runners; running_live=False → OMITTED
    }
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=_live_style_runners,
        config=_HERMETIC_CONFIG,
    )
    assert outcome.roster is not None
    stamp_entries = [e for e in outcome.roster if e.name == "ci_local_stamp"]
    assert len(stamp_entries) == 1
    entry = stamp_entries[0]
    assert entry.status == "OMITTED", (
        f"No stamp key + hermetic runners → stamp must be OMITTED; "
        f"got {entry.status}: {entry.detail}"
    )


def test_stamp_indeterminate_on_unresolvable_root_live_path(monkeypatch):
    """Live stamp path (running_live=True) with unresolvable root → ci_local_stamp INDETERMINATE.

    Calls build_predicates_and_roster directly with running_live=True and r={}
    (no stamp key) so the live stamp branch is reached. With find_project_root
    patched to None, gate_roster.py's elif _project_root is None guard fires and
    returns INDETERMINATE with the 'could not resolve project root' detail.

    Mutation pin: replacing the elif branch with `raise` or removing it entirely
    causes this test to error/fail, proving zero-coverage is eliminated.

    The injected-stamp carve-out (stamp key present + None root → still evaluates)
    is covered by test_injected_stamp_evaluates_from_non_repo_cwd.
    """
    import gate_roster

    monkeypatch.setattr(gate_roster, "find_project_root", lambda: None, raising=False)

    from deterministic_gate import (
        FailureClass,
        GateVerdict,
    )

    # Minimal stand-ins for non-stamp predicates: threads=[], mergeable=MERGEABLE,
    # rollup=[], failure_class=INDETERMINATE (empty rollup) — only stamp branch tested.
    predicates, roster_entries = gate_roster.build_predicates_and_roster(
        pr_url="https://github.com/o/r/pull/1",
        rollup=[],
        failure_class=FailureClass.INDETERMINATE,
        threads=[],
        mergeable="MERGEABLE",
        head_oid="deadbeef",
        config=_HERMETIC_CONFIG,
        r={
            # p7's hermetic seam (review finding on PR #109): running_live=True
            # below would otherwise send the default-required proof predicate to
            # live `gh pr view` mid-test. Only the stamp path is under test here.
            "comments_fn": lambda _u: [],
        },
        copilot_runners=None,
        running_live=True,  # forces the live stamp path (not hermetic carve-out)
        shared_dir=None,
    )
    stamp_entries = [e for e in roster_entries if e.name == "ci_local_stamp"]
    assert len(stamp_entries) == 1, (
        f"Expected exactly one ci_local_stamp entry; got {stamp_entries}"
    )
    entry = stamp_entries[0]
    assert entry.status == "INDETERMINATE", (
        f"Live stamp with None project root must be INDETERMINATE; "
        f"got {entry.status}: {entry.detail}"
    )
    assert "project root" in entry.detail.lower(), (
        f"INDETERMINATE detail must mention 'project root'; got {entry.detail!r}"
    )


def test_hermetic_injected_paths_unchanged():
    """Hermetic paths (balloon_sizes injected with value) are byte-identical to pre-change.

    When balloon_sizes is in runners dict with a real (non-None) tuple,
    sizes are used directly without project-root resolution. This confirms
    hermetic test paths are not affected by the live-path changes.
    """
    from deterministic_gate import evaluate_gate

    runners = _make_base_runners(balloon_sizes=(100, 1000))
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
        config=_HERMETIC_CONFIG,
    )
    assert outcome.roster is not None
    balloon_entries = [e for e in outcome.roster if e.name == "diff_not_ballooned"]
    assert len(balloon_entries) == 1
    # With sizes=(100, 1000), factor=5.0 → 100/1000=0.1 < 5.0 → PASS
    assert balloon_entries[0].status == "PASS", (
        f"Expected PASS for hermetic balloon sizes, got {balloon_entries[0].status}"
    )


def test_injected_stamp_evaluates_from_non_repo_cwd(monkeypatch):
    """Injected stamp evaluates regardless of cwd — hermetic carve-out (p6).

    When stamp is injected, pred_ci_local_stamp uses only the injected dict
    (not the repo_root), so the predicate must evaluate (PASS or FAIL) even
    when _project_root is None (non-repo cwd). This mirrors the balloon's
    injected-sizes carve-out.

    Mutation pin: if the _stamp_key_present check is moved AFTER the
    _project_root-is-None guard, this test gets INDETERMINATE instead of a
    definitive verdict — failing the assertion.
    """
    import gate_roster
    from deterministic_gate import evaluate_gate

    # Force project root to None so without the carve-out stamp would be INDETERMINATE
    monkeypatch.setattr(gate_roster, "find_project_root", lambda: None, raising=False)

    stamp_data = {"schema": 1, "head_sha": "deadbeef", "dirty": False}
    runners = _make_base_runners(stamp=stamp_data)
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
        config=_HERMETIC_CONFIG,
    )
    assert outcome.roster is not None
    stamp_entries = [e for e in outcome.roster if e.name == "ci_local_stamp"]
    assert len(stamp_entries) == 1
    entry = stamp_entries[0]
    # Injected stamp with matching head_sha="deadbeef" and dirty=False → PASS
    # (assert == PASS, not just != INDETERMINATE, so OMITTED/FAIL mutations also fail)
    assert entry.status == "PASS", (
        f"Injected stamp (head_sha matches, dirty=False) must be PASS; "
        f"got {entry.status}: {entry.detail}. "
        "Mutation pin: reordering _stamp_key_present behind _project_root-is-None "
        "produces INDETERMINATE for injected stamps from a non-repo cwd, failing this assertion."
    )
