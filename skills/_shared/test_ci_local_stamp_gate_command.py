"""test_ci_local_stamp_gate_command.py — Task 2.1: refusal text names the gate command.

`pred_ci_local_stamp(..., gate_command=)` must render the declared command (or the
`ci_gate_run.py` wrapper) in its FAIL detail, and the `StampError` refusal texts must
say "the gate command" — never the dev-repo script name `ci-local.sh`.

Red pins (consumer-repo-parity 2.1):
  * `gate_command="make ci"` -> the no-stamp / stale-stamp / dirty-stamp FAIL details
    each contain the declared command (`make ci`) AND the wrapper (`ci_gate_run.py`);
  * `gate_command=None`    -> the same details contain `ci.gate_command` (declare it);
  * no FAIL detail and no `StampError` message contains the token `ci-local.sh`;
  * the no-stamp detail keeps its leading `no ci-local stamp` words (the parity smoke
    A6 halves grep `[ci_local_stamp] no ci-local stamp` until 2.2 rewrites them).

Git-backed tests build a real repo in `tmp_path` and scrub inherited `GIT_*` env
(same pattern as `skills/_shared/fixtures/foreign_repo.py` / `test_repo_config_load.py`).
Stdlib only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# GIT_* scrubbed so the fixture repo's own identity wins over any inherited
# GIT_CONFIG_* (same pattern as fixtures/foreign_repo.py / test_repo_config_load.py).
_CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True, env=_CLEAN_ENV,
    )
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    """A scratch git repo with one commit; return (root, head_sha)."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "x.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t21@test.local")
    _git(root, "config", "user.name", "T21 Fixture")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root, _git(root, "rev-parse", "HEAD")


def _stale_stamp() -> dict:
    return {"schema": 1, "head_sha": "oldsha", "dirty": False}


def _dirty_stamp(head_sha: str) -> dict:
    return {"schema": 1, "head_sha": head_sha, "dirty": True}


def _no_stamp_detail(gate_command: "str | None") -> str:
    import ci_local_stamp
    return ci_local_stamp.pred_ci_local_stamp(
        "abc123", repo_root="unused", stamp=None, gate_command=gate_command
    ).detail


def _stale_detail(gate_command: "str | None") -> str:
    import ci_local_stamp
    return ci_local_stamp.pred_ci_local_stamp(
        "newsha", repo_root="unused", stamp=_stale_stamp(), gate_command=gate_command
    ).detail


def _dirty_detail(gate_command: "str | None") -> str:
    import ci_local_stamp
    head = "abc123"
    return ci_local_stamp.pred_ci_local_stamp(
        head, repo_root="unused", stamp=_dirty_stamp(head), gate_command=gate_command
    ).detail


class TestPredGateCommandText:
    """pred_ci_local_stamp FAIL details name the declared gate command (or the wrapper)."""

    # --- gate_command="make ci" -------------------------------------------

    def test_declared_command_in_no_stamp_detail(self):
        detail = _no_stamp_detail("make ci")
        assert "make ci" in detail
        assert "ci_gate_run.py" in detail

    def test_declared_command_in_stale_detail(self):
        detail = _stale_detail("make ci")
        assert "make ci" in detail
        assert "ci_gate_run.py" in detail

    def test_declared_command_in_dirty_detail(self):
        detail = _dirty_detail("make ci")
        assert "make ci" in detail
        assert "ci_gate_run.py" in detail

    # --- gate_command=None (declared: explicit require: true only) --------

    def test_none_names_ci_gate_command_in_no_stamp_detail(self):
        assert "ci.gate_command" in _no_stamp_detail(None)

    def test_none_names_ci_gate_command_in_stale_detail(self):
        assert "ci.gate_command" in _stale_detail(None)

    def test_none_names_ci_gate_command_in_dirty_detail(self):
        assert "ci.gate_command" in _dirty_detail(None)

    # --- never the dev-repo script name -----------------------------------

    @pytest.mark.parametrize("gate_command", ["make ci", None])
    @pytest.mark.parametrize("name", ["no_stamp", "stale", "dirty"])
    def test_detail_never_names_dev_script(self, gate_command, name):
        detail = {
            "no_stamp": _no_stamp_detail,
            "stale": _stale_detail,
            "dirty": _dirty_detail,
        }[name](gate_command)
        assert "ci-local.sh" not in detail, (
            f"{name} detail must not name the dev-repo script: {detail!r}"
        )

    def test_no_stamp_detail_keeps_leading_words(self):
        """The parity smoke A6 halves grep `[ci_local_stamp] no ci-local stamp`."""
        assert _no_stamp_detail("make ci").startswith("no ci-local stamp")
        assert _no_stamp_detail(None).startswith("no ci-local stamp")


class TestStampErrorText:
    """write_stamp StampError refusal texts say 'the gate command', not the dev script."""

    def test_head_drift_names_gate_command(self, tmp_path):
        import ci_local_stamp
        root, _head = _make_repo(tmp_path)
        with pytest.raises(ci_local_stamp.StampError) as exc:
            ci_local_stamp.write_stamp(root, expect_head="0" * 40)
        assert "the gate command" in str(exc.value)
        assert "ci-local.sh" not in str(exc.value)

    def test_started_dirty_names_gate_command(self, tmp_path):
        import ci_local_stamp
        root, _head = _make_repo(tmp_path)
        with pytest.raises(ci_local_stamp.StampError) as exc:
            ci_local_stamp.write_stamp(root, expect_start_dirty=True)
        assert "the gate command" in str(exc.value)
        assert "ci-local.sh" not in str(exc.value)

    def test_dirty_state_changed_names_gate_command(self, tmp_path, monkeypatch):
        import ci_local_stamp
        root, _head = _make_repo(tmp_path)
        monkeypatch.setattr(ci_local_stamp, "_is_dirty", lambda _root: True)
        with pytest.raises(ci_local_stamp.StampError) as exc:
            ci_local_stamp.write_stamp(root, expect_start_dirty=False)
        assert "the gate command" in str(exc.value)
        assert "ci-local.sh" not in str(exc.value)
