"""test_carry_check_status.py — review-convergence 10.2: `carry_check.carry_status` reasons
+ the CLI's exit codes, per detailed-design-gates §E1.

Every reason string is pinned verbatim; the HEAD-vs-worktree pair pins that the carry
question reads the COMMITTED config (`git show HEAD:`), never the working tree's (the
#246 failure). There is no `--config` flag: argparse must reject it with exit 2.

Run with: pytest skills/_shared/test_carry_check_status.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "carry_check.py"

PR = "https://github.com/o/r/pull/1"
ABSENT = "carry off: no committed .three-pillars/config.json at HEAD"
NOT_TRUE = ("carry off: review.approval_survives_safe_base_sync is not true "
            "in the committed config")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for key, val in (("user.name", "t"), ("user.email", "t@example.com"),
                     ("commit.gpgsign", "false")):
        _git(root, "config", key, val)
    (root / "README.md").write_text("repo\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _commit_config(root: Path, payload) -> None:
    """Commit `.three-pillars/config.json`; a `str` payload writes the raw text."""
    cfg = root / ".three-pillars" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                   encoding="utf-8")
    _git(root, "add", "--", ".three-pillars/config.json")
    _git(root, "commit", "-q", "-m", "config")


def _write_worktree_config(root: Path, payload) -> None:
    cfg = root / ".three-pillars" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(payload), encoding="utf-8")  # left UNCOMMITTED


def _status(root: Path):
    import carry_check
    return carry_check.carry_status(str(root))


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


# --- each reason -------------------------------------------------------------


def test_no_committed_config_at_head(tmp_path):
    assert _status(_init(tmp_path)) == (False, ABSENT)


def test_unreadable_config_at_head_names_the_first_warning(tmp_path):
    root = _init(tmp_path)
    _commit_config(root, "{ not json")
    on, reason = _status(root)
    assert not on
    assert reason.startswith("carry off: config unreadable at HEAD (")
    assert reason.endswith(")")
    assert "not valid JSON" in reason


def test_key_absent_is_not_true(tmp_path):
    root = _init(tmp_path)
    _commit_config(root, {"schema_version": 1})
    assert _status(root) == (False, NOT_TRUE)


def test_key_false_is_not_true(tmp_path):
    root = _init(tmp_path)
    _commit_config(root, {"schema_version": 1,
                          "review": {"approval_survives_safe_base_sync": False}})
    assert _status(root) == (False, NOT_TRUE)


def test_key_true_is_carry_on(tmp_path):
    root = _init(tmp_path)
    _commit_config(root, {"schema_version": 1,
                          "review": {"approval_survives_safe_base_sync": True}})
    assert _status(root) == (True, "carry on")


# --- HEAD, not the worktree ----------------------------------------------------


def test_reads_head_false_even_when_worktree_edited_true(tmp_path):
    root = _init(tmp_path)
    _commit_config(root, {"schema_version": 1,
                          "review": {"approval_survives_safe_base_sync": False}})
    _write_worktree_config(root, {"schema_version": 1,
                                  "review": {"approval_survives_safe_base_sync": True}})
    assert _status(root) == (False, NOT_TRUE)


def test_reads_head_true_even_when_worktree_edited_false(tmp_path):
    root = _init(tmp_path)
    _commit_config(root, {"schema_version": 1,
                          "review": {"approval_survives_safe_base_sync": True}})
    _write_worktree_config(root, {"schema_version": 1,
                                  "review": {"approval_survives_safe_base_sync": False}})
    assert _status(root) == (True, "carry on")


# --- the CLI -------------------------------------------------------------------


def test_cli_rejects_a_config_flag_with_exit_2(tmp_path):
    root = _init(tmp_path)
    result = _run_cli("--repo", str(root), "--pr-url", PR, "--config", str(root))
    assert result.returncode == 2


def test_cli_missing_usage_exits_2(tmp_path):
    root = _init(tmp_path)
    assert _run_cli("--repo", str(root)).returncode == 2


def test_cli_bad_repo_exits_2(tmp_path):
    result = _run_cli("--repo", str(tmp_path / "nope"), "--pr-url", PR)
    assert result.returncode == 2


def test_cli_off_reason_printed_with_exit_1(tmp_path):
    root = _init(tmp_path)
    result = _run_cli("--repo", str(root), "--pr-url", PR)
    assert result.returncode == 1
    assert result.stdout.strip() == ABSENT


def test_cli_json_off_shape(tmp_path):
    root = _init(tmp_path)
    result = _run_cli("--repo", str(root), "--pr-url", PR, "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload == {"carried": False, "reason": ABSENT, "detail": ""}
