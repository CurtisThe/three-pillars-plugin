"""test_hot_patch_commit_msg.py — `hot_patch_hook.commit_msg_mode` (Task 5.1).

Arm (b) of the hot-patch lane on the *pending* commit: the `commit-msg` hook
hands the message file to `hot_patch_check.py --commit-msg FILE`, which reads
the trailers with git's own rules (`git interpret-trailers --parse`) and, only
when a `hot-patch` trailer is present (any key casing), runs the exclusions and
the DIFF_CAP over the index (`git diff --cached`).

Modes are called directly in tmp repos. House rules: real tmp_path git repos,
GIT_* env scrubbed, HOME isolated. Stdlib + pytest only; shipped test (builds
everything it needs in tmp_path).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV.update({
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
})

LEDGER = "three-pillars-docs/tp-designs/orchestration/hot-patches.md"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME: the mode runs git through
    subprocess with the ambient os.environ."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, env=CLEAN_ENV,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _repo(tmp_path: Path, *, born: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    if born:
        (repo / "README.md").write_text("init\n", encoding="utf-8")
        _git(["add", "README.md"], repo)
        _git(["commit", "-q", "-m", "init"], repo)
    return repo


def _stage(repo: Path, rel: str, text: str | bytes) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    _git(["add", rel], repo)


def _msg(tmp_path: Path, text: str) -> str:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _mode(repo: Path, msg_file: str) -> int:
    from skills._shared.hot_patch_hook import commit_msg_mode  # noqa: PLC0415
    return commit_msg_mode(str(repo), msg_file)


TRAILERED = "Hotfix: fix a typo\n\nhot-patch: fixture\n"


def test_no_trailer_is_inert(tmp_path, capsys):
    """An ordinary commit, even one touching a protected path, passes."""
    repo = _repo(tmp_path)
    _stage(repo, ".three-pillars/config.json", '{"schema_version": 1}\n')
    assert _mode(repo, _msg(tmp_path, "chore: plain commit\n")) == 0
    assert "VIOLATION" not in capsys.readouterr().out


@pytest.mark.parametrize("key", ["Hot-Patch", "hot-patch", "HOT-PATCH"])
def test_trailer_any_case_detected(tmp_path, capsys, key):
    repo = _repo(tmp_path)
    _stage(repo, ".three-pillars/config.json", '{"schema_version": 1}\n')
    rc = _mode(repo, _msg(tmp_path, f"Hotfix: x\n\n{key}: x\n"))
    assert rc == 1
    assert "VIOLATION staged exclusion" in capsys.readouterr().out


def test_trailer_shaped_line_outside_last_paragraph_is_not_a_trailer(tmp_path, capsys):
    """git's trailer rules: only the last paragraph holds trailers."""
    repo = _repo(tmp_path)
    _stage(repo, ".three-pillars/config.json", '{"schema_version": 1}\n')
    msg = "Hotfix: x\n\nhot-patch: not a trailer here\n\nThe body goes on after it.\n"
    assert _mode(repo, _msg(tmp_path, msg)) == 0
    assert "VIOLATION" not in capsys.readouterr().out


def test_trailer_below_a_dash_rule_is_still_a_trailer(tmp_path, capsys):
    """M40: git's `%(trailers)` read of the landed commit ignores a `---` body line, so
    the commit-msg arm must too, or it stays inert on a commit the other arms flag."""
    repo = _repo(tmp_path)
    _stage(repo, ".three-pillars/config.json", '{"schema_version": 1}\n')
    msg = "Hotfix: x\n\nnotes\n---\nmore\n\nhot-patch: x\n"
    assert _mode(repo, _msg(tmp_path, msg)) == 1
    assert "VIOLATION staged exclusion" in capsys.readouterr().out


def test_staged_protected_path_violation_line(tmp_path, capsys):
    repo = _repo(tmp_path)
    _stage(repo, ".three-pillars/config.json", '{"schema_version": 1}\n')
    assert _mode(repo, _msg(tmp_path, TRAILERED)) == 1
    out = capsys.readouterr().out
    assert ("VIOLATION staged exclusion: touches protected prefix "
            "'.three-pillars/config.json'") in out


def test_staged_protected_file_violation(tmp_path, capsys):
    repo = _repo(tmp_path)
    _stage(repo, "framework-check.sh", "#!/bin/sh\n")
    assert _mode(repo, _msg(tmp_path, TRAILERED)) == 1
    assert "protected file 'framework-check.sh'" in capsys.readouterr().out


def test_over_cap_staged_lines(tmp_path, capsys):
    repo = _repo(tmp_path)
    _stage(repo, "pkg/big.py", "".join(f"x = {i}\n" for i in range(151)))
    assert _mode(repo, _msg(tmp_path, TRAILERED)) == 1
    out = capsys.readouterr().out
    assert "VIOLATION staged diff-cap: 151 changed lines exceeds cap of 150" in out


def test_at_cap_passes(tmp_path):
    repo = _repo(tmp_path)
    _stage(repo, "pkg/ok.py", "".join(f"x = {i}\n" for i in range(150)))
    assert _mode(repo, _msg(tmp_path, TRAILERED)) == 0


def test_small_fix_plus_ledger_append_passes(tmp_path, capsys):
    """The ledger is exempt from the cap: paper never eats the fix budget."""
    repo = _repo(tmp_path)
    _stage(repo, "README.md", "init\nfixed\n")
    _stage(repo, LEDGER, "".join(f"- entry {i}\n" for i in range(300)))
    assert _mode(repo, _msg(tmp_path, TRAILERED)) == 0
    assert "VIOLATION" not in capsys.readouterr().out


def test_staged_binary_file(tmp_path, capsys):
    repo = _repo(tmp_path)
    _stage(repo, "asset.bin", b"\x00\x01\x02binary\x00")
    assert _mode(repo, _msg(tmp_path, TRAILERED)) == 1
    assert "VIOLATION staged diff-cap: binary file 'asset.bin'" in capsys.readouterr().out


def test_unborn_head(tmp_path, capsys):
    """`git diff --cached` works before the first commit."""
    repo = _repo(tmp_path, born=False)
    _stage(repo, ".three-pillars/config.json", '{"schema_version": 1}\n')
    assert _mode(repo, _msg(tmp_path, TRAILERED)) == 1
    assert "VIOLATION staged exclusion" in capsys.readouterr().out


def test_unborn_head_small_fix_passes(tmp_path):
    repo = _repo(tmp_path, born=False)
    _stage(repo, "README.md", "hello\n")
    assert _mode(repo, _msg(tmp_path, TRAILERED)) == 0


def test_cli_commit_msg_flag(tmp_path):
    """`hot_patch_check.py --commit-msg FILE` is the entry point the hook uses."""
    repo = _repo(tmp_path)
    _stage(repo, ".three-pillars/config.json", '{"schema_version": 1}\n')
    script = Path(__file__).resolve().parent / "hot_patch_check.py"
    msg = _msg(tmp_path, TRAILERED)
    result = subprocess.run(
        ["python3", str(script), "--repo-root", str(repo), "--commit-msg", msg],
        capture_output=True, text=True, env=CLEAN_ENV, cwd=str(repo),
    )
    assert result.returncode == 1, result.stderr
    assert "VIOLATION staged exclusion" in result.stdout
    plain = _msg(tmp_path, "chore: plain\n")
    result = subprocess.run(
        ["python3", str(script), "--repo-root", str(repo), "--commit-msg", plain],
        capture_output=True, text=True, env=CLEAN_ENV, cwd=str(repo),
    )
    assert result.returncode == 0, result.stdout + result.stderr
