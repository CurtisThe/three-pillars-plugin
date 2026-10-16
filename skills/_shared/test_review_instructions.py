"""test_review_instructions — status and scaffold, and their CLI.

design: consumer-repo-parity (Task 8.2)

`status(repo, config)` is the three-valued read the `/tp-pr-iterate` prose
branches on: `present` if `.github/review-instructions.md` exists, `declined`
if `review.instructions_declined` is true, else `absent`. `scaffold(repo)`
writes both `.github` files from the shared template (the copilot file under a
sync header) and never overwrites; the returned list holds only what was
written. `review_instructions.py status|scaffold [--repo P]` are the entry
points the skill prose calls: `status` prints the word, `scaffold` prints each
written path one per line (nothing when nothing was written); both exit 0.
Run with: python3 -m pytest skills/_shared/test_review_instructions.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_config_load as rcl  # noqa: E402
import review_instructions as ri  # noqa: E402

SHARED_DIR = Path(__file__).resolve().parent
SCRIPT = SHARED_DIR / "review_instructions.py"
TEMPLATE = SHARED_DIR / "templates" / "review-instructions.md"
REVIEW_FILE = ".github/review-instructions.md"
COPILOT_FILE = ".github/copilot-instructions.md"

# GIT_* scrubbed so the fixture repo's own identity wins over any inherited
# GIT_CONFIG_* (same pattern as fixtures/foreign_repo.py).
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root: Path, *args: str) -> None:
    env = dict(CLEAN_ENV)
    env["HOME"] = str(root)  # the fixture repo's local config, never the user's
    subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True, env=env,
    )


def _repo(tmp_path: Path, *, committed: dict | None = None) -> Path:
    """A scratch git repo under `tmp_path`; optionally a committed config file."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    if committed is not None:
        cfg_dir = root / ".three-pillars"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(
            json.dumps(committed, indent=2) + "\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t82@test.local")
    _git(root, "config", "user.name", "T82 Fixture")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _config(root: Path) -> dict:
    return rcl.load_repo_config(root).config


# --- status ------------------------------------------------------------------


def test_status_present(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    (root / ".github").mkdir()
    (root / REVIEW_FILE).write_text("x\n", encoding="utf-8")
    assert ri.status(root, _config(root)) == "present"


def test_status_present_wins_over_declined(tmp_path):
    root = _repo(tmp_path, committed={
        "schema_version": 1, "review": {"instructions_declined": True}})
    (root / ".github").mkdir()
    (root / REVIEW_FILE).write_text("x\n", encoding="utf-8")
    assert ri.status(root, _config(root)) == "present"


def test_status_declined(tmp_path):
    root = _repo(tmp_path, committed={
        "schema_version": 1, "review": {"instructions_declined": True}})
    assert ri.status(root, _config(root)) == "declined"


def test_status_absent(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    assert ri.status(root, _config(root)) == "absent"


def test_status_declined_must_be_true_not_truthy(tmp_path):
    root = _repo(tmp_path)
    assert ri.status(root, {"review": {"instructions_declined": 1}}) == "absent"
    assert ri.status(root, {"review": {"instructions_declined": "yes"}}) == "absent"
    assert ri.status(root, {}) == "absent"


# --- scaffold ----------------------------------------------------------------


def test_scaffold_writes_review_instructions_equal_to_template(tmp_path):
    root = _repo(tmp_path)
    written = ri.scaffold(root)
    assert (root / REVIEW_FILE).read_bytes() == TEMPLATE.read_bytes()


def test_scaffold_writes_copilot_with_sync_header_and_same_body(tmp_path):
    root = _repo(tmp_path)
    ri.scaffold(root)
    text = (root / COPILOT_FILE).read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    assert template in text  # the same body
    assert not text.startswith(template)  # …under a header, not raw
    header = text[:text.index(template)]
    assert "<!--" in header and ".github/review-instructions.md" in header


def test_scaffold_returns_written_paths(tmp_path):
    root = _repo(tmp_path)
    written = ri.scaffold(root)
    assert written == [root / REVIEW_FILE, root / COPILOT_FILE]


def test_scaffold_never_overwrites(tmp_path):
    root = _repo(tmp_path)
    (root / ".github").mkdir()
    mine = root / REVIEW_FILE
    mine.write_text("my own\n", encoding="utf-8")
    written = ri.scaffold(root)
    assert mine.read_text(encoding="utf-8") == "my own\n"  # byte-identical
    assert mine not in written
    assert written == [root / COPILOT_FILE]


def test_scaffold_repeat_writes_nothing(tmp_path):
    root = _repo(tmp_path)
    ri.scaffold(root)
    assert ri.scaffold(root) == []


def test_scaffold_creates_github_dir(tmp_path):
    root = _repo(tmp_path)
    assert not (root / ".github").exists()
    ri.scaffold(root)
    assert (root / ".github").is_dir()


# --- CLI ---------------------------------------------------------------------


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=dict(CLEAN_ENV))


def test_cli_status_then_declined_then_present(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})

    proc = _cli("status", "--repo", str(root))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "absent"

    set_proc = _cli_set_declined(root, True)
    assert set_proc.returncode == 0
    proc = _cli("status", "--repo", str(root))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "declined"

    proc = _cli("scaffold", "--repo", str(root))
    assert proc.returncode == 0
    proc = _cli("status", "--repo", str(root))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "present"


def _cli_set_declined(root: Path, value: bool) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SHARED_DIR / "repo_config_load.py"),
         "set", "review.instructions_declined", json.dumps(value),
         "--repo", str(root)],
        capture_output=True, text=True, env=dict(CLEAN_ENV))


def test_cli_scaffold_prints_written_paths_and_repeat_prints_nothing(tmp_path):
    root = _repo(tmp_path)
    first = _cli("scaffold", "--repo", str(root))
    assert first.returncode == 0
    assert first.stdout.splitlines() == [
        str(root / REVIEW_FILE), str(root / COPILOT_FILE)]

    second = _cli("scaffold", "--repo", str(root))
    assert second.returncode == 0
    assert second.stdout == ""


def test_cli_bad_usage_exits_2_with_usage_on_stderr():
    for args in ([], ["nope"], ["status", "extra"], ["status", "--repo"],
                 ["scaffold", "extra"], ["scaffold", "--repo"],
                 ["status", "scaffold"]):
        proc = _cli(*args)
        assert proc.returncode == 2, f"args={args} rc={proc.returncode}"
        assert "usage" in proc.stderr.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
