"""test_land_backstop.py — land() boundary backstop and repro-script regression guards.

Covers:
  TestLandBoundaryBackstop — land() hard-refuses when require_human_approval=false
                              (Task 2.1)
  TestReproScripts         — repro scripts in audits/ exit 0 (Finding 4 regression
                              guards)

See also:
  test_gate_provenance.py — _load_repo_config HEAD-read provenance and Behavior 6
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# Ensure tp-merge-from-main/scripts is on sys.path (for merge_gate)
_FROM_MAIN_SCRIPTS = _SHARED_DIR.parent / "tp-merge-from-main" / "scripts"
if str(_FROM_MAIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_FROM_MAIN_SCRIPTS))

# Ensure tp-merge/scripts is on sys.path (for land)
_MERGE_SCRIPTS = _SHARED_DIR.parent / "tp-merge" / "scripts"
if str(_MERGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MERGE_SCRIPTS))


# ---------------------------------------------------------------------------
# Task 2.1: TestLandBoundaryBackstop
# ---------------------------------------------------------------------------

class TestLandBoundaryBackstop:
    """Verify land() hard-refuses when review.require_human_approval resolves false."""

    def _make_sentinels(self):
        """Return recording fake require_fn and merge_fn."""
        calls = {"require": [], "merge": []}

        def require_fn(pr_url, *, config=None):
            calls["require"].append(pr_url)
            # Simulate PASS (no exception raised, return a mock outcome)
            from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL
            return GateOutcome(verdict=GateVerdict.PASS, blocking=[], label=GATE_LABEL)

        def merge_fn(pr_url):
            calls["merge"].append(pr_url)

        return require_fn, merge_fn, calls

    def test_explicit_false_config_refuses_before_gate(self, capsys):
        """config={"review": {"require_human_approval": False}} -> exit 2, gate not called."""
        import land as land_mod

        require_fn, merge_fn, calls = self._make_sentinels()

        rc = land_mod.land(
            "https://github.com/test/repo/pull/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config={"review": {"require_human_approval": False}},
        )

        assert rc == 2, f"Expected exit 2, got {rc}"
        assert calls["require"] == [], "require_fn must not be called on backstop refusal"
        assert calls["merge"] == [], "merge_fn must not be called on backstop refusal"

        out = capsys.readouterr().out
        # Output names the human_approved predicate
        assert "human_approved" in out.lower() or "human approval" in out.lower() or "require_human_approval" in out
        # Output names the resolved value
        assert "false" in out.lower() or "False" in out

    def test_explicit_false_config_output_mentions_authorization(self, capsys):
        """Backstop refusal output includes pointer to authorization path."""
        import land as land_mod

        require_fn, merge_fn, calls = self._make_sentinels()

        land_mod.land(
            "https://github.com/test/repo/pull/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config={"review": {"require_human_approval": False}},
        )

        out = capsys.readouterr().out
        # Should mention how to re-enable: either the howto file or the key/label
        assert "tp:human-approved" in out or "human-approval-howto" in out or "require_human_approval" in out

    def test_head_resolved_false_refuses(self, monkeypatch, capsys):
        """config=None with _load_repo_config monkeypatched to return false -> exit 2.

        Patches the name on land_mod directly (not deterministic_gate) because land.py
        imports _load_repo_config by name, creating its own binding.
        """
        import deterministic_gate
        import land as land_mod

        # Patch both the source module and land's imported name binding
        fake_loader = lambda: {"review": {"require_human_approval": False}}
        monkeypatch.setattr(deterministic_gate, "_load_repo_config", fake_loader)
        monkeypatch.setattr(land_mod, "_load_repo_config", fake_loader)

        require_fn, merge_fn, calls = self._make_sentinels()

        rc = land_mod.land(
            "https://github.com/test/repo/pull/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config=None,
        )

        assert rc == 2
        assert calls["require"] == []
        assert calls["merge"] == []

    def test_explicit_true_config_proceeds_to_gate(self, capsys):
        """config={"review": {"require_human_approval": True}} -> proceeds to require_fn."""
        import land as land_mod

        require_fn, merge_fn, calls = self._make_sentinels()

        rc = land_mod.land(
            "https://github.com/test/repo/pull/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config={"review": {"require_human_approval": True}},
        )

        assert rc == 0
        assert len(calls["require"]) == 1, "require_fn must be called"
        assert len(calls["merge"]) == 1, "merge_fn must be called on PASS"

    def test_empty_config_proceeds_to_gate(self, capsys):
        """config={} (strict default) -> proceeds to require_fn (default True)."""
        import land as land_mod

        require_fn, merge_fn, calls = self._make_sentinels()

        rc = land_mod.land(
            "https://github.com/test/repo/pull/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config={},
        )

        assert rc == 0
        assert len(calls["require"]) == 1
        assert len(calls["merge"]) == 1

    def test_blocked_gate_still_returns_2(self, capsys):
        """When require_fn raises MergeGateBlocked, land still returns 2."""
        import land as land_mod
        from merge_gate import MergeGateBlocked
        from deterministic_gate import GateOutcome, GateVerdict, PredicateResult, GATE_LABEL

        blocked_outcome = GateOutcome(
            verdict=GateVerdict.FAIL,
            blocking=[PredicateResult(
                name="human_approved",
                verdict=GateVerdict.FAIL,
                detail="no tp:human-approved label",
            )],
            label=GATE_LABEL,
        )

        def require_fn(pr_url, *, config=None):
            raise MergeGateBlocked(blocked_outcome)

        calls = {"merge": []}

        def merge_fn(pr_url):
            calls["merge"].append(pr_url)

        rc = land_mod.land(
            "https://github.com/test/repo/pull/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config={"review": {"require_human_approval": True}},
        )

        assert rc == 2
        assert calls["merge"] == []


# ---------------------------------------------------------------------------
# Finding 4: TestReproScripts — repro scripts as automatic regression guards
# ---------------------------------------------------------------------------

class TestReproScripts:
    """Each repro script in the 2026-06-09-framework-audit/repro/ directory
    exits 0, turning manual evidence into an automatic regression guard.
    """

    def _repo_root(self) -> Path:
        """Resolve the repo root via git from the _shared/ directory."""
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(_SHARED_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
        # Fallback: _shared/ -> skills/ -> repo root
        return _SHARED_DIR.parent.parent

    def test_gate_integrity_4_diskread_exits_zero(self):
        """gate_integrity_4_diskread.py exits 0 (HEAD-read fix holds)."""
        repo_root = self._repo_root()
        script = (
            repo_root
            / "three-pillars-docs"
            / "audits"
            / "2026-06-09-framework-audit"
            / "repro"
            / "gate_integrity_4_diskread.py"
        )
        assert script.exists(), f"Repro script not found: {script}"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"gate_integrity_4_diskread.py exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_gate_integrity_4_verify_exits_zero(self):
        """gate_integrity_4_verify.py exits 0 (both arms refuse the boundary)."""
        repo_root = self._repo_root()
        script = (
            repo_root
            / "three-pillars-docs"
            / "audits"
            / "2026-06-09-framework-audit"
            / "repro"
            / "gate_integrity_4_verify.py"
        )
        assert script.exists(), f"Repro script not found: {script}"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"gate_integrity_4_verify.py exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
