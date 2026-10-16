"""Task 9.4: run_round.py records each round's fragile items, keyed by BRANCH NAME.

The merge gate's fragility_predicate reads `fragility_items.open_items(root, branch)` —
the current checkout's branch, never the head SHA. A real tmp git repo (checked out on a
named branch) exercises run_round.main() end-to-end and inspects the resulting store.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RUN_ROUND_PY = SCRIPTS_DIR / "run_round.py"
_SHARED = SCRIPTS_DIR.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import fragility_items  # noqa: E402

_BRANCH = "tp/demo"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "a")
    (repo / "README.md").write_text("x", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "checkout", "-q", "-b", _BRANCH)
    return repo


def _minimal_state(last_verdict: str = "minor-only") -> dict:
    now = datetime.now(tz=timezone.utc)
    started = (now - timedelta(hours=1)).isoformat()
    return {
        "phase": "awaiting-copilot",
        "iteration": 1,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": started,
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": 100,
        "consecutive_structural_rounds": 0,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
        "last_verdict": last_verdict,
    }


def _clean_config() -> dict:
    return {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}


def _blocking_finding() -> dict:
    return {
        "blocking": True,
        "fragility_class": "open-ended",
        "path": "foo_test.py",
        "line": 1,
        "summary": "heuristic over prose",
    }


def _run(repo: Path, payload: dict):
    result = subprocess.run(
        [sys.executable, str(RUN_ROUND_PY)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        cwd=str(repo),
    )
    try:
        envelope = json.loads(result.stdout.strip())
    except Exception:
        envelope = {"_raw_stdout": result.stdout.decode(), "_stderr": result.stderr.decode()}
    return result.returncode, envelope, result.stderr.decode()


def test_round_records_one_pr_loop_item_keyed_by_branch_name(tmp_path):
    """A blocking open-ended finding at head H leaves one pr-loop item at H, keyed
    by the checkout's BRANCH NAME — never the head SHA."""
    repo = _init_repo(tmp_path)
    head_sha = "deadbeef0123456789"
    payload = {
        "state": _minimal_state(),
        "head_sha": head_sha,
        "codereview_findings": [_blocking_finding()],
        "reviewed": None,
        "unresolved_actionable": 1,  # prevent convergence
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
    }

    rc, env, stderr = _run(repo, payload)

    assert rc == 0, f"expected exit 0, got {rc}; envelope={env}; stderr={stderr}"
    assert env.get("status") == "ok"

    # Never keyed by the head SHA — open_items(repo, head_sha) must be empty.
    assert fragility_items.open_items(repo, head_sha) == []

    items = fragility_items.open_items(repo, _BRANCH)
    assert len(items) == 1
    assert items[0]["fragility_class"] == "open-ended"
    assert items[0]["source"] == "pr-loop"

    stored = fragility_items._load(repo)["branches"][_BRANCH]["sources"]["pr-loop"]
    assert stored["head"] == head_sha


def test_unwritable_store_is_logged_and_round_outcome_unchanged(tmp_path):
    """A store the round cannot write is logged to stderr; the round's own
    ok/status envelope is unchanged (fail-open)."""
    repo = _init_repo(tmp_path)
    # Block the store's parent directory: put a regular FILE where
    # fragility_items.store_path would need a directory ("three-pillars" under
    # the git dir), so `_write`'s mkdir(parents=True) cannot succeed.
    git_dir = Path(
        subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-dir"],
                       capture_output=True, text=True, check=True).stdout.strip()
    )
    git_dir = git_dir if git_dir.is_absolute() else (repo / git_dir)
    blocker = git_dir / "three-pillars"
    blocker.write_text("blocked", encoding="utf-8")

    payload = {
        "state": _minimal_state(),
        "head_sha": "deadbeef0123456789",
        "codereview_findings": [_blocking_finding()],
        "reviewed": None,
        "unresolved_actionable": 1,
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
    }

    rc, env, stderr = _run(repo, payload)

    assert rc == 0, f"expected exit 0, got {rc}; envelope={env}; stderr={stderr}"
    assert env.get("status") == "ok"
    assert stderr.strip() != "", "an unwritable store must be logged to stderr"
