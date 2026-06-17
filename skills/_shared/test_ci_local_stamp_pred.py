"""test_ci_local_stamp_pred.py — pred_ci_local_stamp predicate matrix + evaluate_gate seam.

Covers:
  TestPredCiLocalStamp      — predicate verdict matrix (Task 3.2)
  TestEvaluateGateStampSeam — stamp seam in evaluate_gate (Task 3.3)

See also:
  test_ci_local_stamp.py       — write_stamp/read_stamp/StampError unit tests
  test_ci_local_stamp_cli.py   — --write CLI tests
  test_ci_local_sh_wiring.py   — ci-local.sh shell-wiring tests
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


# ---------------------------------------------------------------------------
# Helpers: minimal git repo (used by TestPredCiLocalStamp)
# ---------------------------------------------------------------------------

def _git(args, cwd):
    import subprocess
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo_root: Path) -> None:
    _git(["init", "-q", str(repo_root)], ".")
    _git(["config", "user.email", "t@t.test"], repo_root)
    _git(["config", "user.name", "test"], repo_root)


def _make_commit(repo_root: Path, msg: str = "commit") -> str:
    """Create a commit in the repo; return the HEAD sha."""
    import subprocess
    (repo_root / "x.txt").write_text(msg)
    _git(["add", "-A"], repo_root)
    _git(["commit", "-qm", msg], repo_root)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Task 3.2: TestPredCiLocalStamp
# ---------------------------------------------------------------------------

class TestPredCiLocalStamp:
    """pred_ci_local_stamp predicate matrix."""

    def _pass_stamp(self, head_sha: str) -> dict:
        return {"schema": 1, "head_sha": head_sha, "dirty": False}

    def test_matching_head_clean_returns_pass(self, tmp_path):
        """stamp matches head_oid and dirty=False -> PASS."""
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        head_oid = "abc123def456"
        stamp = self._pass_stamp(head_oid)
        repo_root = tmp_path / "repo"

        result = ci_local_stamp.pred_ci_local_stamp(
            head_oid, repo_root=str(repo_root), stamp=stamp
        )
        assert result.verdict == GateVerdict.PASS

    def test_absent_stamp_returns_fail(self, tmp_path):
        """stamp=None -> FAIL with detail pointing to ci-local.sh."""
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        result = ci_local_stamp.pred_ci_local_stamp(
            "abc123", repo_root=str(tmp_path), stamp=None
        )
        assert result.verdict == GateVerdict.FAIL
        assert "ci-local" in result.detail.lower() or "stamp" in result.detail.lower()

    def test_stale_head_sha_returns_fail(self, tmp_path):
        """stamp.head_sha != head_oid -> FAIL (drift)."""
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        stamp = {"schema": 1, "head_sha": "oldsha", "dirty": False}
        result = ci_local_stamp.pred_ci_local_stamp(
            "newsha", repo_root=str(tmp_path), stamp=stamp
        )
        assert result.verdict == GateVerdict.FAIL
        assert "stale" in result.detail.lower() or "drift" in result.detail.lower() or "mismatch" in result.detail.lower()

    def test_dirty_stamp_returns_fail(self, tmp_path):
        """stamp with dirty=True -> FAIL (uncommitted state)."""
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        head_oid = "abc123"
        stamp = {"schema": 1, "head_sha": head_oid, "dirty": True}
        result = ci_local_stamp.pred_ci_local_stamp(
            head_oid, repo_root=str(tmp_path), stamp=stamp
        )
        assert result.verdict == GateVerdict.FAIL
        assert "dirty" in result.detail.lower() or "uncommitted" in result.detail.lower()

    def test_stamp_error_returns_indeterminate(self, tmp_path, monkeypatch):
        """StampError from read_stamp -> INDETERMINATE."""
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        def bad_read(repo_root):
            raise ci_local_stamp.StampError("broken stamp")

        monkeypatch.setattr(ci_local_stamp, "read_stamp", bad_read)

        result = ci_local_stamp.pred_ci_local_stamp(
            "abc123", repo_root=str(tmp_path)
        )
        assert result.verdict == GateVerdict.INDETERMINATE

    def test_predicate_name_is_ci_local_stamp(self, tmp_path):
        """Predicate name is 'ci_local_stamp'."""
        import ci_local_stamp

        stamp = {"schema": 1, "head_sha": "abc", "dirty": False}
        result = ci_local_stamp.pred_ci_local_stamp(
            "abc", repo_root=str(tmp_path), stamp=stamp
        )
        assert result.name == "ci_local_stamp"

    def test_unset_reads_via_read_stamp(self, tmp_path):
        """When stamp is _UNSET, the predicate calls read_stamp to resolve it."""
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        head_sha = _make_commit(repo_root)
        ci_local_stamp.write_stamp(repo_root)

        # With no stamp= kwarg, the predicate should read the stamp from disk
        result = ci_local_stamp.pred_ci_local_stamp(head_sha, repo_root=str(repo_root))
        assert result.verdict == GateVerdict.PASS

    # --- Minor a: empty head_oid guard ---

    def test_empty_head_oid_returns_indeterminate(self, tmp_path):
        """pred_ci_local_stamp returns INDETERMINATE when head_oid is empty/falsy."""
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        stamp = {"schema": 1, "head_sha": "abc123", "dirty": False}
        for empty in ("", None, 0):
            result = ci_local_stamp.pred_ci_local_stamp(
                empty, repo_root=str(tmp_path), stamp=stamp
            )
            assert result.verdict == GateVerdict.INDETERMINATE, (
                f"Expected INDETERMINATE for head_oid={empty!r}, got {result.verdict}"
            )

    # --- Minor b: schema validation and dirty is-False semantics ---

    @pytest.mark.parametrize("bad_schema", [0, 2, None, "1", ""])
    def test_wrong_schema_returns_indeterminate(self, tmp_path, bad_schema):
        """pred_ci_local_stamp returns INDETERMINATE when stamp.schema != STAMP_SCHEMA."""
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        head_oid = "abc123"
        stamp = {"schema": bad_schema, "head_sha": head_oid, "dirty": False}
        result = ci_local_stamp.pred_ci_local_stamp(
            head_oid, repo_root=str(tmp_path), stamp=stamp
        )
        assert result.verdict == GateVerdict.INDETERMINATE, (
            f"Expected INDETERMINATE for schema={bad_schema!r}, got {result.verdict}"
        )

    @pytest.mark.parametrize("non_bool_falsy", [0, "", [], None, {}])
    def test_dirty_non_bool_falsy_returns_fail(self, tmp_path, non_bool_falsy):
        """pred_ci_local_stamp returns FAIL for non-bool falsy dirty values (not is False).

        dirty=0 / '' / [] / None / {} are NOT False — the stamp is considered dirty
        (or unknown) rather than clean.  Only dirty=False (exact boolean False)
        passes the clean check.
        """
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        head_oid = "abc123"
        stamp = {"schema": 1, "head_sha": head_oid, "dirty": non_bool_falsy}
        result = ci_local_stamp.pred_ci_local_stamp(
            head_oid, repo_root=str(tmp_path), stamp=stamp
        )
        assert result.verdict == GateVerdict.FAIL, (
            f"Expected FAIL for dirty={non_bool_falsy!r} (not exactly False), "
            f"got {result.verdict}"
        )


# ---------------------------------------------------------------------------
# Task 3.3: TestEvaluateGateStampSeam
# ---------------------------------------------------------------------------

class TestEvaluateGateStampSeam:
    """The stamp seam in evaluate_gate wires correctly."""

    # Minimal runners for an otherwise-all-PASS evaluation
    PASS_RUNNERS = {
        "pr_state_fn": lambda url: {
            "mergeable": "MERGEABLE",
            "headRefOid": "deadbeefcafe",
            "statusCheckRollup": [],
        },
        "threads_fn": lambda url: [],
        "balloon_sizes": (100, 1000),
        "labels_fn": lambda url: [],
        "timeline_fn": lambda url: [],
        "head_fn": lambda url: {},
        "commits_fn": lambda url: [],
        "self_login_fn": lambda: "bot",
    }

    PASS_CONFIG = {
        "review": {"expects_copilot": False, "require_human_approval": False},
        "ci": {"expects_github_checks": False},
    }

    def test_stamp_absent_causes_fail(self):
        """runners with stamp=None -> verdict FAIL, ci_local_stamp in blocking."""
        from deterministic_gate import evaluate_gate, GateVerdict

        runners = dict(self.PASS_RUNNERS)
        runners["stamp"] = None

        outcome = evaluate_gate("https://example.com/pr/1",
                                runners=runners, config=self.PASS_CONFIG)
        assert outcome.verdict == GateVerdict.FAIL
        blocking_names = [p.name for p in outcome.blocking]
        assert "ci_local_stamp" in blocking_names

    def test_matching_stamp_preserves_pass(self):
        """runners with matching stamp -> PASS preserved."""
        from deterministic_gate import evaluate_gate, GateVerdict

        runners = dict(self.PASS_RUNNERS)
        runners["stamp"] = {
            "schema": 1,
            "head_sha": "deadbeefcafe",
            "dirty": False,
        }

        outcome = evaluate_gate("https://example.com/pr/1",
                                runners=runners, config=self.PASS_CONFIG)
        assert outcome.verdict == GateVerdict.PASS

    def test_no_stamp_key_backward_compat(self):
        """runners WITHOUT stamp key -> predicate not appended; outcome unchanged from today."""
        from deterministic_gate import evaluate_gate, GateVerdict

        # Without the stamp key, the behavior should be identical to pre-stamp runs
        outcome = evaluate_gate("https://example.com/pr/1",
                                runners=self.PASS_RUNNERS, config=self.PASS_CONFIG)
        # Should PASS (no stamp predicate added)
        assert outcome.verdict == GateVerdict.PASS
        blocking_names = [p.name for p in outcome.blocking]
        assert "ci_local_stamp" not in blocking_names

    def test_key_present_activates_predicate(self, monkeypatch):
        """Stamp key present in runners activates pred_ci_local_stamp (key-present path)."""
        import ci_local_stamp
        from deterministic_gate import evaluate_gate, GateVerdict, PredicateResult
        from ci_local_stamp import _UNSET as _STAMP_UNSET

        observed = []

        # fake_pred needs a stamp default (_UNSET) so it doesn't TypeError when
        # called on the live path (which omits the stamp kwarg).
        def fake_pred(head_oid, *, repo_root, stamp=_STAMP_UNSET):
            observed.append({"head_oid": head_oid, "stamp": stamp})
            return PredicateResult(
                name="ci_local_stamp",
                verdict=GateVerdict.PASS,
                detail="mocked",
            )

        monkeypatch.setattr(ci_local_stamp, "pred_ci_local_stamp", fake_pred)

        # key-present path: stamp kwarg is in runners → predicate called with that value
        runners = dict(self.PASS_RUNNERS)
        runners["stamp"] = {"schema": 1, "head_sha": "deadbeefcafe", "dirty": False}

        outcome = evaluate_gate("https://example.com/pr/1",
                                runners=runners, config=self.PASS_CONFIG)
        assert len(observed) == 1
        assert observed[0]["head_oid"] == "deadbeefcafe"
        # Key-present path passes the stamp value directly (not _UNSET)
        assert observed[0]["stamp"] == {"schema": 1, "head_sha": "deadbeefcafe", "dirty": False}

    def test_pure_live_mode_activates_predicate(self, monkeypatch):
        """Pure live mode (no runners at all) activates pred_ci_local_stamp without stamp kwarg.

        Verifies the _running_live = not r branch: when runners is falsy (empty/None),
        pred_ci_local_stamp is called WITHOUT the stamp kwarg (live disk-read path).
        All other live callouts are monkeypatched to keep the test hermetic — no real
        gh, no real git diff, no real thread/label/review API calls.
        """
        import ci_local_stamp
        import diff_balloon_guard
        import deterministic_gate
        import gate_roster
        from deterministic_gate import evaluate_gate, GateVerdict, PredicateResult
        from ci_local_stamp import _UNSET as _STAMP_UNSET

        stamp_calls = []

        def fake_pred(head_oid, *, repo_root, stamp=_STAMP_UNSET):
            stamp_calls.append({"head_oid": head_oid, "stamp": stamp})
            return PredicateResult(
                name="ci_local_stamp",
                verdict=GateVerdict.PASS,
                detail="live-mode mock",
            )

        # Stub out the live pr_state_fn to return a clean PR (avoids network)
        def fake_live_pr_state(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": "livedeadbeef",
                "statusCheckRollup": [],
            }

        # Stub out all live seams to keep test hermetic
        monkeypatch.setattr(ci_local_stamp, "pred_ci_local_stamp", fake_pred)
        monkeypatch.setattr(deterministic_gate, "_live_pr_state_fn", fake_live_pr_state)

        # Stub thread fetch (avoid real gh)
        from deterministic_gate import fetch_threads_or_none as _orig_fetch
        monkeypatch.setattr(
            deterministic_gate, "fetch_threads_or_none",
            lambda url, *, threads_fn=None: [],
        )

        # Stub balloon guard to avoid real git diff
        def fake_balloon(*a, **kw):
            return PredicateResult(
                name="diff_not_ballooned", verdict=GateVerdict.PASS, detail="mocked"
            )
        monkeypatch.setattr(diff_balloon_guard, "pred_diff_not_ballooned", fake_balloon)

        # Config: skip copilot + human (both OMITTED) to reduce stubs needed
        live_config = {
            "review": {"expects_copilot": False, "require_human_approval": False},
            "ci": {"expects_github_checks": False},
        }

        # Pure live mode: no runners (runners=None → r = {} → _running_live = True)
        outcome = evaluate_gate(
            "https://example.com/pr/1",
            runners=None,
            config=live_config,
        )

        # Predicate must have fired exactly once
        assert len(stamp_calls) == 1, (
            f"Expected pred_ci_local_stamp called once in live mode, "
            f"got {len(stamp_calls)} calls"
        )
        assert stamp_calls[0]["head_oid"] == "livedeadbeef"
        # Live path omits stamp kwarg → fake_pred receives the default _UNSET
        assert stamp_calls[0]["stamp"] is _STAMP_UNSET, (
            "Live mode must call pred_ci_local_stamp WITHOUT stamp kwarg "
            f"(got stamp={stamp_calls[0]['stamp']!r})"
        )
