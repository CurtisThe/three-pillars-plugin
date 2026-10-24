"""Tests for review_loop_forge.py — the Gitea cause line for the loop and gate.

design: review-convergence (Task 11.3, detailed-design-gates §E3)

`gitea_cause(repo_root)` names the one cause the review loop and the merge gate
refuse Gitea for, so a Gitea repo degrades VISIBLY instead of silently:
gitea origin -> the exact cause text, github / no origin / any forge.resolve
error -> None (the helper is total and never raises). The gate's null-head
INDETERMINATE names the cause; `round_plan.plan` refuses with it up front.

Hermetic: fixture repos are `git init` + `git remote add origin` + a committed
`.three-pillars/config.json` (forge.resolve reads the committed config, so the
commit is what makes the fixture resolve without probing). No network.
Run with: python3 -m pytest skills/_shared/test_review_loop_forge.py -q -n0
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
RPLAN_DIR = HERE.parent / "tp-pr-iterate" / "scripts"
sys.path.insert(0, str(RPLAN_DIR))

import forge  # noqa: E402
import review_loop_forge  # noqa: E402

GITEA_CAUSE = "gate: forge gitea not supported by review loop (gitea-forge-adapter)"
NULL_SHA_DETAIL = "null or empty head SHA — cannot prove any predicate"


def _fixture_repo(tmp_path: Path, *, origin: str | None,
                  forge_cfg: "dict | None" = None) -> Path:
    """A committed config + an origin, so forge.resolve answers without probing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env_git = ["git", "-C", str(repo)]
    subprocess.run(env_git + ["init", "-q"], check=True, capture_output=True)
    subprocess.run(env_git + ["config", "user.email", "t@example.test"],
                   check=True, capture_output=True)
    subprocess.run(env_git + ["config", "user.name", "Test"],
                   check=True, capture_output=True)
    cfg_dir = repo / ".three-pillars"
    cfg_dir.mkdir()
    payload = {"forge": forge_cfg} if forge_cfg is not None else {}
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    subprocess.run(env_git + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(env_git + ["commit", "-q", "-m", "seed"],
                   check=True, capture_output=True)
    if origin:
        subprocess.run(env_git + ["remote", "add", "origin", origin],
                       check=True, capture_output=True)
    return repo


@pytest.fixture
def gitea_repo(tmp_path):
    return _fixture_repo(
        tmp_path, origin="https://gitea.example.test/o/r.git",
        forge_cfg={"kind": "gitea", "web_base": "https://gitea.example.test"})


@pytest.fixture
def github_repo(tmp_path):
    return _fixture_repo(tmp_path, origin="https://github.com/o/r.git")


@pytest.fixture
def no_origin_repo(tmp_path):
    return _fixture_repo(tmp_path, origin=None)


# --- gitea_cause itself ----------------------------------------------------------

def test_gitea_origin_returns_the_exact_cause(gitea_repo):
    assert review_loop_forge.gitea_cause(gitea_repo) == GITEA_CAUSE
    assert review_loop_forge.GITEA_CAUSE == GITEA_CAUSE


def test_github_origin_returns_none(github_repo):
    assert review_loop_forge.gitea_cause(github_repo) is None


def test_no_origin_returns_none(no_origin_repo):
    assert review_loop_forge.gitea_cause(no_origin_repo) is None


def test_forge_resolve_error_returns_none(gitea_repo, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("injected forge.resolve failure")

    monkeypatch.setattr(forge, "resolve", boom)
    assert review_loop_forge.gitea_cause(gitea_repo) is None


# --- the gate's null-head INDETERMINATE names the cause --------------------------

def _null_head_runners():
    return {"pr_state_fn": lambda url: {
        "mergeable": "MERGEABLE", "headRefOid": "", "statusCheckRollup": [],
    }}


def _null_head_detail(repo_root):
    from deterministic_gate import GateVerdict, evaluate_gate

    outcome = evaluate_gate("https://github.com/o/r/pull/1",
                            runners=_null_head_runners(), config={},
                            repo_root=str(repo_root))
    assert outcome.verdict == GateVerdict.INDETERMINATE
    assert outcome.blocking[0].name == "head_oid"
    return outcome.blocking[0].detail


def test_gate_null_head_detail_names_the_gitea_cause(gitea_repo):
    detail = _null_head_detail(gitea_repo)
    assert GITEA_CAUSE in detail
    assert detail.startswith(NULL_SHA_DETAIL)


def test_gate_null_head_detail_unchanged_on_github(github_repo):
    assert _null_head_detail(github_repo) == NULL_SHA_DETAIL


# --- round_plan refuses on Gitea with the cause ----------------------------------

def test_plan_refuses_on_gitea_with_the_cause(gitea_repo, tmp_path):
    import round_plan

    with pytest.raises(round_plan.PlanRefused) as exc:
        round_plan.plan({}, root=tmp_path / "rounds", pr_url="https://x/pr/1",
                        pr_base="main", head="abc123", repo=str(gitea_repo))
    assert str(exc.value) == GITEA_CAUSE


def test_plan_does_not_refuse_with_the_gitea_cause_on_github(github_repo):
    assert review_loop_forge.gitea_cause(github_repo) is None


# --- size pins for the two modified files ----------------------------------------

def test_modified_files_stay_within_their_pins():
    gate = (HERE / "deterministic_gate.py").read_text(encoding="utf-8")
    assert len(gate.splitlines()) <= 932
    rplan = RPLAN_DIR / "round_plan.py"
    assert len(rplan.read_text(encoding="utf-8").splitlines()) <= 412
