"""commit_guard.run passes staged paths after `--` (followups-1024 item 1.2).

A staged root file named `-h` or `--help` must not be read as a flag by the
guards' argparse, and a guard that raises `SystemExit` must block, not escape.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import commit_guard  # noqa: E402
from test_commit_guard_fragment import FRAG, TEMPLATE  # noqa: E402


OVERSIZE_LINES = 600  # past the markdown hard cap (500 lines) in file_size_guard


def _stage(monkeypatch, root: Path, staged: list, token: str = "Done — {pr}",
           oversize: list = ()) -> None:
    """Real index, built like `test_commit_guard_fragment._stage`: each path is
    written, then `git add --`-ed, so the guards see what the hook would.

    `oversize` names extra files written past the hard line cap; they stay
    unstaged unless `staged` names them, so the other tests are unaffected."""
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        monkeypatch.delenv(var, raising=False)
    frag = root / FRAG
    frag.parent.mkdir(parents=True, exist_ok=True)
    frag.write_text(TEMPLATE.format(token=token), encoding="utf-8")
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    for name in ("-h", "--help"):
        (root / name).write_text("x\n", encoding="utf-8")
    for name in oversize:
        (root / name).write_text("x\n" * OVERSIZE_LINES, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "add", "--", *staged], cwd=str(root), check=True)


def test_dash_h_file_does_not_hide_bad_fragment(tmp_path, monkeypatch):
    """A staged `-h` beside a bad fragment: the run still blocks (returns 1)."""
    _stage(monkeypatch, tmp_path, ["-h", FRAG], "Completion PR pending")
    assert commit_guard.run(tmp_path, "pre-commit") == 1


def test_dash_help_file_with_clean_stage_passes(tmp_path, monkeypatch):
    """A staged `--help` beside README.md: nothing wrong, returns 0, no raise."""
    _stage(monkeypatch, tmp_path, ["--help", "README.md"])
    assert commit_guard.run(tmp_path, "pre-commit") == 0


def test_dash_h_file_file_size_guard_passes(tmp_path, monkeypatch):
    """The size guard really reads the staged dash-prefixed path.

    A small staged `-h` passes (it is a path, not argparse help); an oversize
    staged `-h.md` (markdown class, past the 500-line hard cap) blocks. Every
    failure text names commit_guard.run and the offending return code."""
    monkeypatch.setattr(commit_guard, "_file_size_enabled", lambda repo: True)

    small = tmp_path / "small"
    _stage(monkeypatch, small, ["-h"])
    monkeypatch.chdir(small)
    got_small = commit_guard.run(small, "pre-commit")
    assert got_small == 0, (
        "commit_guard.run with the file-size guard on and only a small `-h` "
        f"staged must return 0, commit_guard.run returned {got_small!r}")

    big = tmp_path / "big"
    _stage(monkeypatch, big, ["-h", "-h.md"], oversize=("-h.md",))
    monkeypatch.chdir(big)
    got_big = commit_guard.run(big, "pre-commit")
    assert got_big == 1, (
        "commit_guard.run must block an oversize staged `-h.md` read by the "
        f"file-size guard, commit_guard.run returned {got_big!r}")


def test_guarded_system_exit_blocks(capsys):
    """A guard's `SystemExit` (argparse help / usage error) blocks as internal error.

    Every exit code blocks, not just success: `sys.exit(0)` (argparse `--help`)
    and `sys.exit(2)` (an argparse usage error) must each become a blocking
    return of 1 — never re-raised out of the hook, never passed through as the
    guard's own status — and each prints the internal-error line on stderr.
    Every failure names `commit_guard._guarded` and the offending value."""
    for code in (0, 2):
        got = commit_guard._guarded("demo", lambda: sys.exit(code))
        assert got == 1, (
            "commit_guard._guarded must block a guard's SystemExit as 1, "
            f"commit_guard._guarded returned {got!r} for sys.exit({code})")
        err = capsys.readouterr().err
        assert "commit-guard: internal error in demo" in err, (
            "commit_guard._guarded must print the internal-error line to "
            "stderr (containing 'commit-guard: internal error in demo'), "
            f"stderr held {err!r} for sys.exit({code})")
