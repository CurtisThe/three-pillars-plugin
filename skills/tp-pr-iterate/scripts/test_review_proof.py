"""Tests for review_proof.py — Phase 1 (Tasks 1.1–1.3).

Covers:
    Task 1.1  resolve_numstat + default_proof_root
    Task 1.2  capture_proof (artifact write)
    Task 1.3  proof_present_and_nonempty (gate predicate)

Tasks 1.4–1.5 + 5.1 (digest formatting, size/C1 guards, gitignore carve) live
in the sibling test_review_proof_digest.py (split for the file-size cap).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_proof  # noqa: E402


# ---------- helpers ----------


def _fake_git_ok(numstat_stdout: str):
    """Return a run_git stub that succeeds with the given stdout."""
    def _run(args):
        return 0, numstat_stdout, ""
    return _run


def _fake_git_fail():
    """Return a run_git stub that fails with rc=1."""
    def _run(args):
        return 1, "", "fatal: bad revision"
    return _run


# ============================================================
# Task 1.1 — resolve_numstat + default_proof_root
# ============================================================


def test_resolve_numstat_non_empty_diff():
    """Normal diff with insertions and deletions parses correctly."""
    numstat = "10\t2\tskills/foo.py\n3\t0\tskills/bar.py\n"
    result = review_proof.resolve_numstat("abc", "def", run_git=_fake_git_ok(numstat))
    assert result["ok"] is True
    assert result["degraded"] is False
    assert result["reason"] is None
    assert result["files_changed"] == 2
    assert result["insertions"] == 13
    assert result["deletions"] == 2
    assert result["base"] == "abc"
    assert result["head"] == "def"
    assert "skills/foo.py" in result["numstat_raw"]


def test_resolve_numstat_empty_diff():
    """Zero-line diff (no output) → degraded=True, reason='empty-diff'."""
    result = review_proof.resolve_numstat("abc", "def", run_git=_fake_git_ok(""))
    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["reason"] == "empty-diff"
    assert result["files_changed"] == 0


def test_resolve_numstat_git_failed():
    """Non-zero git exit → degraded=True, reason='git-failed'."""
    result = review_proof.resolve_numstat("abc", "def", run_git=_fake_git_fail())
    assert result["ok"] is False
    assert result["degraded"] is True
    assert result["reason"] == "git-failed"


def test_resolve_numstat_binary_rows():
    """Binary rows (-\\t-\\t<path>) count toward files_changed, not ins/del."""
    numstat = "-\t-\tpath/image.png\n5\t1\tpath/code.py\n"
    result = review_proof.resolve_numstat("abc", "def", run_git=_fake_git_ok(numstat))
    assert result["ok"] is True
    assert result["degraded"] is False
    assert result["files_changed"] == 2  # binary + code
    assert result["insertions"] == 5
    assert result["deletions"] == 1


def test_resolve_numstat_binary_only_not_degraded():
    """A binary-only diff has files_changed > 0 → not degraded."""
    numstat = "-\t-\tpath/image.png\n"
    result = review_proof.resolve_numstat("abc", "def", run_git=_fake_git_ok(numstat))
    assert result["files_changed"] == 1
    assert result["degraded"] is False


def test_resolve_numstat_malformed_rows_ignored():
    """Malformed rows are silently skipped; valid rows still parsed."""
    numstat = "bad-line\n10\t2\tskills/foo.py\n\n"
    result = review_proof.resolve_numstat("abc", "def", run_git=_fake_git_ok(numstat))
    assert result["files_changed"] == 1
    assert result["insertions"] == 10
    assert result["degraded"] is False


def test_default_proof_root_returns_path_with_suffix(tmp_path):
    """default_proof_root returns a Path ending in .three-pillars/review-proof."""
    root = review_proof.default_proof_root(start=tmp_path)
    assert root.name == "review-proof"
    assert root.parent.name == ".three-pillars"


def test_default_proof_root_fallback_when_not_git_repo(tmp_path, monkeypatch):
    """Falls back to start dir when not a git repo."""
    # Stub find_project_root to return None
    monkeypatch.setattr(review_proof, "find_project_root", lambda _: None)
    root = review_proof.default_proof_root(start=tmp_path)
    assert root == tmp_path / ".three-pillars" / "review-proof"


# ============================================================
# Task 1.2 — capture_proof (artifact write)
# ============================================================


def test_capture_proof_writes_files(tmp_path):
    """capture_proof writes meta.json, numstat.txt, transcripts.json under <root>/<head>/."""
    numstat = "3\t1\tfile.py\n"
    root = tmp_path / "proof"
    meta = review_proof.capture_proof(
        "base123", "head456",
        ["response A", "response B"],
        root=root,
        run_git=_fake_git_ok(numstat),
        now_iso="2026-06-20T10:00:00+00:00",
    )
    proof_dir = root / "head456"
    assert (proof_dir / "meta.json").exists()
    assert (proof_dir / "numstat.txt").exists()
    assert (proof_dir / "transcripts.json").exists()


def test_capture_proof_meta_fields(tmp_path):
    """meta.json contains all required fields with correct values."""
    numstat = "3\t1\tfile.py\n"
    root = tmp_path / "proof"
    meta = review_proof.capture_proof(
        "base123", "head456",
        ["resp1"],
        root=root,
        run_git=_fake_git_ok(numstat),
        now_iso="2026-06-20T10:00:00+00:00",
    )
    assert meta["base"] == "base123"
    assert meta["head"] == "head456"
    assert meta["files_changed"] == 1
    assert meta["insertions"] == 3
    assert meta["deletions"] == 1
    assert meta["degraded"] is False
    assert meta["reason"] is None
    assert meta["angle_count"] == 1
    assert meta["captured_at"] == "2026-06-20T10:00:00+00:00"
    assert "proof_dir" in meta
    # Verify on-disk matches
    disk = json.loads((root / "head456" / "meta.json").read_text(encoding="utf-8"))
    assert disk["base"] == "base123"
    assert disk["head"] == "head456"


def test_capture_proof_transcripts_truncated(tmp_path):
    """Per-angle transcripts truncated to 20000 chars."""
    long_resp = "x" * 30000
    root = tmp_path / "proof"
    review_proof.capture_proof(
        "b", "h",
        [long_resp],
        root=root,
        run_git=_fake_git_ok("1\t0\tf.py\n"),
    )
    transcripts = json.loads((root / "h" / "transcripts.json").read_text(encoding="utf-8"))
    assert len(transcripts) == 1
    assert len(transcripts[0]) == 20000


def test_capture_proof_non_str_angle_coerced(tmp_path):
    """Non-str angle responses are coerced to str."""
    root = tmp_path / "proof"
    review_proof.capture_proof(
        "b", "h",
        [{"key": "value"}, 42],
        root=root,
        run_git=_fake_git_ok("1\t0\tf.py\n"),
    )
    transcripts = json.loads((root / "h" / "transcripts.json").read_text(encoding="utf-8"))
    assert len(transcripts) == 2
    assert isinstance(transcripts[0], str)
    assert isinstance(transcripts[1], str)


def test_capture_proof_meta_oserror_returns_degraded(tmp_path):
    """When root is a file (not a dir) → OSError → returned dict has degraded=True."""
    # Make root path point to a FILE so mkdir fails
    root_file = tmp_path / "proof_as_file"
    root_file.write_text("I am a file")
    # The proof_dir would be root_file / head, but mkdir on a file fails
    result = review_proof.capture_proof(
        "b", "headXYZ",
        [],
        root=root_file,
        run_git=_fake_git_ok("1\t0\tf.py\n"),
    )
    assert result.get("degraded") is True
    assert result.get("reason") == "capture-write-failed"


def test_capture_proof_zero_angles_degrades_even_with_real_diff(tmp_path):
    """capture_proof([]) on a real, non-empty diff must still degrade — proof-of-
    REVIEW requires a review to have actually run (review finding on PR #109:
    previously a zero-angle capture on a real diff yielded a non-degraded,
    gate-passing digest)."""
    root = tmp_path / "proof"
    meta = review_proof.capture_proof(
        "base123", "head456",
        [],
        root=root,
        run_git=_fake_git_ok("3\t1\tfile.py\n"),
    )
    assert meta["degraded"] is True
    assert meta["reason"] == "no-review-angles"
    assert meta["files_changed"] == 1
    assert meta["angle_count"] == 0
    assert review_proof.proof_present_and_nonempty("head456", root=root) is False


# ============================================================
# Task 1.3 — proof_present_and_nonempty
# ============================================================


def test_proof_present_nonempty_true(tmp_path):
    """Present + nonempty meta → True."""
    root = tmp_path / "proof"
    review_proof.capture_proof(
        "base", "headABC",
        ["resp"],
        root=root,
        run_git=_fake_git_ok("2\t1\tf.py\n"),
    )
    assert review_proof.proof_present_and_nonempty("headABC", root=root) is True


def test_proof_present_missing_dir_false(tmp_path):
    """Missing dir → False."""
    root = tmp_path / "proof"
    assert review_proof.proof_present_and_nonempty("nonexistent", root=root) is False


def test_proof_present_degraded_meta_false(tmp_path):
    """Degraded meta (empty-diff) → False."""
    root = tmp_path / "proof"
    # Write a degraded meta manually
    proof_dir = root / "headDEG"
    proof_dir.mkdir(parents=True)
    meta = {"head": "headDEG", "degraded": True, "files_changed": 0, "reason": "empty-diff"}
    (proof_dir / "meta.json").write_text(json.dumps(meta))
    assert review_proof.proof_present_and_nonempty("headDEG", root=root) is False


def test_proof_present_degraded_with_files_changed_positive_false(tmp_path):
    """degraded=True but files_changed>0 (forged/corrupt meta) → False.

    Independently pins the `meta['degraded'] is True` conjunct. Every OTHER degraded
    fixture also has files_changed==0, so the files_changed<=0 conjunct masks the
    degraded check — drop `degraded` and those tests stay green. Here files_changed>0
    and head matches, so ONLY the degraded conjunct can return False: remove it and
    proof_present_and_nonempty wrongly returns True (a forged or git-failed meta with a
    non-zero count would certify). This is exactly the provenance threat model the
    design exists to close.
    """
    root = tmp_path / "proof"
    proof_dir = root / "headDEGNZ"
    proof_dir.mkdir(parents=True)
    meta = {"head": "headDEGNZ", "degraded": True, "files_changed": 5, "reason": "git-failed"}
    (proof_dir / "meta.json").write_text(json.dumps(meta))
    assert review_proof.proof_present_and_nonempty("headDEGNZ", root=root) is False


def test_proof_present_head_mismatch_false(tmp_path):
    """meta['head'] != head → False (stale artifact)."""
    root = tmp_path / "proof"
    proof_dir = root / "headMISMATCH"
    proof_dir.mkdir(parents=True)
    meta = {"head": "differentHead", "degraded": False, "files_changed": 3}
    (proof_dir / "meta.json").write_text(json.dumps(meta))
    assert review_proof.proof_present_and_nonempty("headMISMATCH", root=root) is False


def test_proof_present_zero_files_changed_false(tmp_path):
    """files_changed == 0 → False."""
    root = tmp_path / "proof"
    proof_dir = root / "headZERO"
    proof_dir.mkdir(parents=True)
    meta = {"head": "headZERO", "degraded": False, "files_changed": 0}
    (proof_dir / "meta.json").write_text(json.dumps(meta))
    assert review_proof.proof_present_and_nonempty("headZERO", root=root) is False


def test_proof_present_malformed_meta_false(tmp_path):
    """Malformed meta JSON → False (never raises)."""
    root = tmp_path / "proof"
    proof_dir = root / "headMAL"
    proof_dir.mkdir(parents=True)
    (proof_dir / "meta.json").write_text("{invalid json{{")
    assert review_proof.proof_present_and_nonempty("headMAL", root=root) is False


def test_proof_present_falsy_head_false(tmp_path):
    """Falsy head (empty string) → False."""
    root = tmp_path / "proof"
    assert review_proof.proof_present_and_nonempty("", root=root) is False
    assert review_proof.proof_present_and_nonempty(None, root=root) is False
