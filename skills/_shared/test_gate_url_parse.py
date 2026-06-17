"""Tests for _parse_github_owner_repo URL form coverage and binding edge cases.

Split from test_gate_config_root.py to stay under the 500-line file-size cap.
Covers:
- URL parsing happy path and reject cases (including ssh:// false-positive regression)
- Binding check except-Exception branch (unexpected error → roster note)
- Null-head-SHA early return (Step 2) preserves config_root_binding note
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest as _pytest


# ---------------------------------------------------------------------------
# Helpers (shared with test_gate_config_root.py by inline definition)
# ---------------------------------------------------------------------------

def _init_repo_with_config(path: Path, config: dict) -> None:
    """Create a git repo at path with a committed .three-pillars/config.json."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    cfg_dir = path / ".three-pillars"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps(config))
    subprocess.run(
        ["git", "-C", str(path), "add", ".three-pillars/config.json"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init config"],
        check=True, capture_output=True,
    )


_HERMETIC_RUNNERS_BASE = {
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

_RELAXED_CONFIG = {
    "ci": {"expects_github_checks": False},
    "review": {"expects_copilot": False, "require_human_approval": False},
}


# ---------------------------------------------------------------------------
# _parse_github_owner_repo URL form coverage
# ---------------------------------------------------------------------------

@_pytest.mark.parametrize("url,expected", [
    # Standard HTTPS
    ("https://github.com/Owner/Repo", ("owner", "repo")),
    ("https://github.com/Owner/Repo.git", ("owner", "repo")),
    ("https://github.com/o/r/pull/1", ("o", "r")),
    # HTTP
    ("http://github.com/o/r.git", ("o", "r")),
    # Credentialed HTTPS (x-access-token, gh CLI style)
    ("https://x-access-token:tok@github.com/o/r.git", ("o", "r")),
    ("https://user:pass@github.com/o/r", ("o", "r")),
    # Trailing slashes
    ("https://github.com/o/r/", ("o", "r")),
    ("https://github.com/o/r.git/", ("o", "r")),
    # SSH scp-shorthand
    ("git@github.com:o/r.git", ("o", "r")),
    ("git@github.com:o/r", ("o", "r")),
    # ssh:// scheme
    ("ssh://git@github.com/o/r.git", ("o", "r")),
    ("ssh://git@github.com/o/r", ("o", "r")),
    # ssh:// with port (ssh.github.com:443 form)
    ("ssh://git@ssh.github.com:443/o/r.git", ("o", "r")),
    ("ssh://git@github.com:22/o/r.git", ("o", "r")),
    # Case insensitivity
    ("https://GITHUB.COM/MyOrg/MyRepo", ("myorg", "myrepo")),
])
def test_parse_github_owner_repo_happy(url, expected):
    """All supported URL forms parse to lower-cased (owner, repo)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import _parse_github_owner_repo
    assert _parse_github_owner_repo(url) == expected, (
        f"URL {url!r} should parse to {expected}, got {_parse_github_owner_repo(url)!r}"
    )


@_pytest.mark.parametrize("url", [
    "https://gitlab.com/o/r.git",
    "https://bitbucket.org/o/r.git",
    "git@gitlab.com:o/r.git",
    "not-a-url",
    "",
    "https://github.com",
    "https://github.com/onlyowner",
    # ssh:// false-positive regression pins — non-GitHub hosts must not parse
    "ssh://evilgithub.com/o/r",
    "ssh://foo.github.com/o/r",
    "ssh://evil.com/github.com/o/r",
    "ssh://notgithub.com:22/o/r.git",
])
def test_parse_github_owner_repo_reject_non_github(url):
    """Non-github hosts and malformed URLs return None (never a false positive)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import _parse_github_owner_repo
    assert _parse_github_owner_repo(url) is None, (
        f"URL {url!r} should return None (non-github or malformed)"
    )


# ---------------------------------------------------------------------------
# Binding except-Exception branch: unexpected error → roster note, no silent discard
# ---------------------------------------------------------------------------

def test_binding_exception_records_roster_note(tmp_path, monkeypatch):
    """Binding check except-Exception branch records an informational roster note.

    An unexpected error in the binding check must NOT silently discard the config
    with zero trace. The except branch must set _config_root_mismatch_note so the
    operator sees it in the roster output.

    Mutation pin: the assertion checks the *unexpected-error* wording — not the
    ordinary mismatch wording — so deleting `config = {}` in the except branch
    (or collapsing it into the mismatch branch) will fail this test.

    Implementation: monkeypatch project_root.find_project_root so that the FIRST
    call (inside _load_repo_config) succeeds to return the project root (non-empty
    config → binding check runs), and the SECOND call (inside the binding-check try
    block) raises ValueError — which propagates to except-Exception rather than being
    swallowed inside _config_repo_owner_repo (which has its own guard).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import project_root as _project_root_mod
    from deterministic_gate import evaluate_gate

    project = tmp_path / "project"
    _init_repo_with_config(project, _RELAXED_CONFIG)
    monkeypatch.chdir(project)

    # Call-count strategy: calls to find_project_root:
    #   call 1 — _load_repo_config: return real root so config is non-empty
    #   call 2 — binding try block in evaluate_gate: raise to trigger the inner
    #             except-Exception branch and set _config_root_mismatch_note
    #   call 3+ — gate_roster.build_predicates_and_roster: return real root
    #              so the rest of the gate evaluation completes without cascade error
    _real_find_root = _project_root_mod.find_project_root
    _call_count = [0]

    def _find_root_raise_on_second_call():
        _call_count[0] += 1
        if _call_count[0] == 2:
            raise ValueError("unexpected internal error in binding find_project_root")
        return _real_find_root()

    monkeypatch.setattr(
        _project_root_mod, "find_project_root", _find_root_raise_on_second_call
    )

    runners = dict(_HERMETIC_RUNNERS_BASE)
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
    )
    binding_entries = [e for e in (outcome.roster or ()) if e.name == "config_root_binding"]
    assert len(binding_entries) == 1, (
        f"except-Exception branch must record a roster note (not silently discard); "
        f"got {binding_entries}"
    )
    assert binding_entries[0].status == "INDETERMINATE"
    # The detail must contain the unexpected-error wording, NOT the mismatch wording.
    # This distinguishes the except branch from the ordinary mismatch branch.
    detail = binding_entries[0].detail
    assert "unexpected error" in detail.lower(), (
        f"except-Exception branch detail must contain 'unexpected error'; got: {detail!r}. "
        "Mutation pin: if the except branch were removed, the ordinary mismatch wording "
        "would appear instead, failing this assertion."
    )
    assert "does not match" not in detail.lower(), (
        f"except-Exception branch must NOT produce mismatch wording; got: {detail!r}"
    )
    # NON-BLOCKING: must not fold into blocking predicates
    blocking_names = [p.name for p in (outcome.blocking or [])]
    assert "config_root_binding" not in blocking_names, (
        f"config_root_binding must not fold into blocking predicates: {blocking_names}"
    )

    # EFFECT assertion: except branch must set config={} (strict defaults), NOT keep
    # the loaded relaxed config. The project's .three-pillars/config.json has
    # review.expects_copilot=false (relaxed). Strict defaults → expects_copilot=True.
    # Effect: copilot_on_head must appear as a real entry (PASS/FAIL/INDETERMINATE),
    # NOT as OMITTED (which would happen if the relaxed config survived the except branch).
    #
    # Mutation pin: deleting `config = {}` in the except branch leaves the relaxed
    # config in place → expects_copilot=false → copilot_on_head is OMITTED → this
    # assertion fails, proving the fail-closed effect is pinned.
    copilot_entries = [e for e in (outcome.roster or ()) if e.name == "copilot_on_head"]
    assert copilot_entries, (
        f"copilot_on_head must appear in roster; got {[e.name for e in (outcome.roster or ())]}"
    )
    assert copilot_entries[0].status != "OMITTED", (
        f"copilot_on_head must not be OMITTED under strict defaults; "
        f"got status={copilot_entries[0].status!r}. "
        "Mutation pin: keeping the relaxed config (not resetting to {{}}) produces OMITTED."
    )


# ---------------------------------------------------------------------------
# null-head-SHA early return (Step 2) preserves config_root_binding note
# ---------------------------------------------------------------------------

def test_null_head_sha_early_return_includes_binding_note(tmp_path, monkeypatch):
    """config_root_binding note must appear in the Step-2 null-head-SHA roster.

    When the binding check fires (mismatch or unreadable) AND the PR-state fetch
    returns an empty head SHA, the early-return roster must include the binding note
    so it is visible to the operator. Previously the note was silently dropped.

    Mutation pin: if the early-return roster stops including the binding note,
    this test fails (the entry count drops to 1 and the name check fails).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import evaluate_gate, GateVerdict

    project = tmp_path / "project"
    _init_repo_with_config(project, _RELAXED_CONFIG)
    monkeypatch.chdir(project)

    # PR-state returns null head SHA to trigger the Step-2 early return
    def null_sha_pr_state(url):
        return {"mergeable": "MERGEABLE", "headRefOid": "", "statusCheckRollup": []}

    # remote_url_fn returns a mismatched remote so the binding note is set
    def mismatched_remote(_cmd):
        return "https://github.com/other-owner/other-repo.git"

    runners = dict(
        _HERMETIC_RUNNERS_BASE,
        pr_state_fn=null_sha_pr_state,
        remote_url_fn=mismatched_remote,
    )
    outcome = evaluate_gate("https://github.com/o/r/pull/1", runners=runners)

    # Step-2 early return → INDETERMINATE verdict
    assert outcome.verdict == GateVerdict.INDETERMINATE

    roster_names = [e.name for e in (outcome.roster or ())]
    assert "head_oid" in roster_names, (
        f"null-SHA roster must include head_oid entry; got {roster_names}"
    )
    assert "config_root_binding" in roster_names, (
        f"null-SHA early-return roster must include config_root_binding note; "
        f"got {roster_names}. Mutation pin: deleting the note inclusion in Step 2 "
        "silently drops the binding note."
    )
