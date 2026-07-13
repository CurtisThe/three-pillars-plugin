"""Tests for `label_manager.ensure_pr_label`.

Three scenarios exercise the idempotent label-ensure dance (the add now goes
through the REST `gh api issues/{n}/labels` endpoint, never `gh pr edit` —
which is broken on classic-Projects repos):

1. First call on a PR without the label: `gh pr view` reports no labels,
   `gh api .../issues/{n}/labels` succeeds -> two calls.
2. Second call after the label is already present: `gh pr view` reports
   the label -> one call only, no add.
3. Label does not yet exist on the repo: `gh pr view` reports no labels,
   the REST add fails with a "not found"/422 stderr, `gh label create`
   succeeds, retry of the REST add succeeds -> four calls.

All tests stub `label_manager.subprocess.run` (the module-local binding)
so we never shell out to the real `gh`.

Run with: pytest skills/tp-pr-fix/scripts/test_label_manager.py -q
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest


PR_URL = "https://github.com/example/repo/pull/42"
LABEL = "tp:do-not-merge-yet"


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr=stderr)


def _cmd(call) -> list[str]:
    """Extract the argv list from a recorded mock call."""
    args, _kwargs = call
    return list(args[0])


def _input(call):
    """Extract the `input=` kwarg (the request body sent on stdin) from a call."""
    _args, kwargs = call
    return kwargs.get("input")


def test_first_call_creates_label_and_adds():
    from label_manager import ensure_pr_label

    side_effects = [
        _ok(stdout=json.dumps({"labels": []})),  # pr view
        _ok(),  # gh api issues/{n}/labels
    ]

    with patch("label_manager.subprocess.run", side_effect=side_effects) as run:
        ensure_pr_label(PR_URL, LABEL)

    assert run.call_count == 2, f"expected 2 calls, got {run.call_count}"

    first = _cmd(run.call_args_list[0])
    assert first[:3] == ["gh", "pr", "view"]
    assert PR_URL in first
    assert "--json" in first and "labels" in first

    # The add goes through the REST endpoint, NOT `gh pr edit`, with an explicit
    # JSON array body on stdin.
    second = _cmd(run.call_args_list[1])
    assert second[:2] == ["gh", "api"]
    assert "repos/example/repo/issues/42/labels" in second
    assert "--input" in second and "edit" not in second
    assert json.loads(_input(run.call_args_list[1])) == {"labels": [LABEL]}


def test_second_call_is_noop():
    from label_manager import ensure_pr_label

    side_effects = [
        _ok(stdout=json.dumps({"labels": [{"name": LABEL}]})),  # pr view
    ]

    with patch("label_manager.subprocess.run", side_effect=side_effects) as run:
        ensure_pr_label(PR_URL, LABEL)

    assert run.call_count == 1, f"expected 1 call, got {run.call_count}"

    only = _cmd(run.call_args_list[0])
    assert only[:3] == ["gh", "pr", "view"]


def test_ready_for_human_merge_label_constant() -> None:
    """Phase 2.1: label_manager must expose a READY_FOR_HUMAN_MERGE constant equal
    to 'tp:ready-for-human-merge', consistent with the tp:needs-human-attention
    namespace."""
    from label_manager import READY_FOR_HUMAN_MERGE

    assert READY_FOR_HUMAN_MERGE == "tp:ready-for-human-merge"
    # Must be usable by ensure_pr_label (consistent format, no whitespace, valid string).
    assert isinstance(READY_FOR_HUMAN_MERGE, str) and READY_FOR_HUMAN_MERGE.strip()


def test_creates_missing_label_via_gh_label_create():
    from label_manager import ensure_pr_label

    side_effects = [
        _ok(stdout=json.dumps({"labels": []})),  # pr view
        _fail(stderr="HTTP 422: Label does not exist (not found)"),  # first REST add
        _ok(),  # gh label create
        _ok(),  # retry REST add
    ]

    with patch("label_manager.subprocess.run", side_effect=side_effects) as run:
        ensure_pr_label(PR_URL, LABEL)

    assert run.call_count == 4, f"expected 4 calls, got {run.call_count}"

    first = _cmd(run.call_args_list[0])
    assert first[:3] == ["gh", "pr", "view"]

    second = _cmd(run.call_args_list[1])
    assert second[:2] == ["gh", "api"]
    assert "repos/example/repo/issues/42/labels" in second
    assert json.loads(_input(run.call_args_list[1])) == {"labels": [LABEL]}

    third = _cmd(run.call_args_list[2])
    assert third[:3] == ["gh", "label", "create"]
    assert LABEL in third

    fourth = _cmd(run.call_args_list[3])
    assert fourth[:2] == ["gh", "api"]
    assert "repos/example/repo/issues/42/labels" in fourth
    assert json.loads(_input(run.call_args_list[3])) == {"labels": [LABEL]}


def test_never_uses_gh_pr_edit():
    """Regression (PR #60 dogfood): the add path must NEVER shell out to
    `gh pr edit`, which fails on a classic-Projects repo with a GraphQL
    projectCards deprecation error before the label is applied."""
    from label_manager import ensure_pr_label

    side_effects = [
        _ok(stdout=json.dumps({"labels": []})),  # pr view
        _ok(),  # REST add
    ]
    with patch("label_manager.subprocess.run", side_effect=side_effects) as run:
        ensure_pr_label(PR_URL, LABEL)

    for call in run.call_args_list:
        cmd = _cmd(call)
        assert cmd[:3] != ["gh", "pr", "edit"], (
            f"ensure_pr_label must not use `gh pr edit` (classic-Projects breakage); got {cmd}"
        )


def test_parse_pr_url_extracts_owner_repo_number():
    from label_manager import _parse_pr_url

    assert _parse_pr_url("https://github.com/CurtisThe/three-pillars/pull/60") == (
        "CurtisThe", "three-pillars", "60",
    )
    # Enterprise host path is parsed the same way (owner/repo/pull/n).
    assert _parse_pr_url("https://ghe.example.com/o/r/pull/7") == ("o", "r", "7")
    for bad in (
        "https://github.com/o/r/issues/5",  # not a pull URL
        "https://github.com/o/r/pull/abc",  # non-numeric
        "https://github.com/o/r",           # too short
    ):
        with pytest.raises(ValueError):
            _parse_pr_url(bad)


def test_add_label_body_is_explicit_json_array():
    """The add sends `{"labels": [<label>]}` as an explicit JSON body — not a
    `-f labels[]=` string field — so the array shape is unambiguous."""
    from label_manager import _add_label_rest

    with patch("label_manager.subprocess.run", return_value=_ok()) as run:
        _add_label_rest("o", "r", "42", LABEL)

    argv = _cmd(run.call_args_list[0])
    assert argv[:4] == ["gh", "api", "--method", "POST"]
    assert "repos/o/r/issues/42/labels" in argv and "--input" in argv
    assert json.loads(_input(run.call_args_list[0])) == {"labels": [LABEL]}


def test_label_missing_signal_requires_label_context_for_422():
    """A bare 422 must NOT be read as a missing label; 'not found'/'does not exist'
    stand alone, and a 422 only counts when the message is about a label."""
    from label_manager import _label_missing_signal

    assert _label_missing_signal("gh: label not found") is True          # standalone "not found"
    assert _label_missing_signal("HTTP 422: Label ... does not exist") is True
    assert _label_missing_signal("HTTP 422 Validation Failed: label name invalid") is True  # 422 + label
    # Unrelated 422 (e.g. a different validation error) must NOT trigger recovery:
    assert _label_missing_signal("HTTP 422: Validation Failed (some other field)") is False
    assert _label_missing_signal("HTTP 500: server error") is False
    assert _label_missing_signal("") is False


def test_unrelated_422_does_not_trigger_spurious_create():
    """An add that 422s for a non-label reason raises immediately (no spurious
    `gh label create` + retry that would mask the true error)."""
    from label_manager import ensure_pr_label

    side_effects = [
        _ok(stdout=json.dumps({"labels": []})),  # pr view
        _fail(stderr="HTTP 422: Validation Failed (unprocessable, unrelated)"),  # add
    ]
    with patch("label_manager.subprocess.run", side_effect=side_effects) as run:
        with pytest.raises(RuntimeError):
            ensure_pr_label(PR_URL, LABEL)

    # Only the view + the failed add ran — no gh label create, no retry.
    assert run.call_count == 2, f"expected 2 calls (view + add), got {run.call_count}"
    assert ["gh", "label", "create"] not in [_cmd(c)[:3] for c in run.call_args_list]


# ---------- remove_pr_label (rounds 2-3: sticky-label hygiene, probe-first) ----------


def _view_labels(names) -> subprocess.CompletedProcess:
    return _ok(stdout=json.dumps({"labels": [{"name": n} for n in names]}))


def test_remove_pr_label_probe_then_rest_delete_with_encoded_name():
    """Present label: read probe first, then REST DELETE with the label
    URL-encoded (tp: colon) — never `gh pr edit --remove-label` (broken on
    classic-Projects repos)."""
    import label_manager

    with patch("label_manager.subprocess.run",
               side_effect=[_view_labels(["tp:needs-human-attention"]), _ok()]) as run:
        assert label_manager.remove_pr_label(PR_URL, "tp:needs-human-attention") is True

    assert run.call_count == 2
    assert _cmd(run.call_args_list[0])[:3] == ["gh", "pr", "view"]
    cmd = _cmd(run.call_args_list[1])
    assert cmd[:4] == ["gh", "api", "--method", "DELETE"]
    assert cmd[4] == "repos/example/repo/issues/42/labels/tp%3Aneeds-human-attention"


def test_remove_pr_label_absent_is_noop_zero_writes():
    """Absent label → True after the READ probe alone (round-3 pin: no
    write-METHOD gh invocation may fire when there is nothing to remove)."""
    import label_manager

    with patch("label_manager.subprocess.run",
               return_value=_view_labels(["some-other-label"])) as run:
        assert label_manager.remove_pr_label(PR_URL, LABEL) is True
    assert run.call_count == 1
    assert _cmd(run.call_args_list[0])[:3] == ["gh", "pr", "view"]


def test_remove_pr_label_probe_failure_no_write_attempt():
    """Probe failure → False with ZERO write attempts (round-3 pin,
    fail-closed-no-write: a hermetic env without working gh must never see a
    DELETE — this keeps the loop suite free of live write-method calls even at
    seams monkeypatch cannot reach, e.g. the run_round.py CLI subprocess)."""
    import label_manager

    with patch("label_manager.subprocess.run", return_value=_fail("no gh")) as run:
        assert label_manager.remove_pr_label(PR_URL, LABEL) is False
    assert run.call_count == 1


def test_remove_pr_label_delete_404_race_is_success():
    """Probe saw it, DELETE 404'd (removed concurrently) → still absent → True."""
    import label_manager

    with patch("label_manager.subprocess.run",
               side_effect=[_view_labels([LABEL]),
                            _fail("HTTP 404: Label does not exist")]):
        assert label_manager.remove_pr_label(PR_URL, LABEL) is True


def test_remove_pr_label_other_failure_false_never_raises():
    import label_manager

    with patch("label_manager.subprocess.run",
               side_effect=[_view_labels([LABEL]), _fail("HTTP 500: boom")]):
        assert label_manager.remove_pr_label(PR_URL, LABEL) is False
    # Bad inputs: False, no raise.
    assert label_manager.remove_pr_label("not-a-url", LABEL) is False
    assert label_manager.remove_pr_label(PR_URL, "") is False
