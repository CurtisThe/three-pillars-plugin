"""Tests for verify_moves.py — the verbatim move verifier.

Covers the ten red cases pinned by plan Task 1.2: a clean move passes; a
dropped line, a duplicated archive line, a deleted prior archive line and an
undeclared archive line each fail and name the offending line; a pointer line
added to the live doc is allowed; a whitespace-only reflow passes while a
changed word fails; the CLI reads the before texts from `git show REV:path`
in a real tmp git repo (identity set locally, ambient repo untouched) and
exits 0/1; a freshly created archive seeded with ARCHIVE_HEADER lines plus a
`## History` heading verifies; and a repeated table header plus its `|---|`
delimiter row above moved rows pass as scaffold.

Run with: python -m pytest skills/_shared/test_verify_moves.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from living_doc_archive import ARCHIVE_HEADER
from task_scope import _git_env

MODULE = Path(__file__).resolve().parent / "verify_moves.py"
LIVE_REL = "three-pillars-docs/product_roadmap.md"
ARCHIVE_REL = "three-pillars-docs/product_roadmap_archive.md"
IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test",
}

LIVE = "keep-me\n\n- a\n- b\n- c\n- d\n- e\n"
MOVED = "- c\n- d\n- e\n"


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(repo), env=_git_env(**IDENTITY),
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def write(repo: Path, rel: str, text: str) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _repo(tmp_path: Path) -> tuple[Path, str]:
    """A throwaway git repo (identity set locally) with the live doc at base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@test")
    write(repo, LIVE_REL, "keep\n- a\n- b\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def _cli(repo: Path, argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MODULE), *argv, "--repo-root", str(repo)],
        cwd=str(repo), capture_output=True, text=True, env=_git_env(),
    )


# --------------------------------------------------------------------------- #
# verify_move
# --------------------------------------------------------------------------- #


def test_clean_move_passes():
    from verify_moves import verify_move

    assert verify_move(LIVE, "keep-me\n\n- a\n- b\n", "", MOVED) == []


def test_pointer_line_added_to_live_doc_is_allowed():
    from verify_moves import verify_move

    pointer = "See [the archive](product_roadmap_archive.md) for older history.\n"
    after_live = "keep-me\n\n- a\n- b\n" + pointer
    assert verify_move(LIVE, after_live, "", MOVED) == []


def test_dropped_line_fails_and_names_it(tmp_path, capsys):
    from verify_moves import main, verify_move

    problems = verify_move(LIVE, "keep-me\n\n- a\n- b\n", "", "- c\n- d\n")
    assert problems == ["lost: - e"], f"dropped line must be reported lost: {problems}"

    # A repeated line: both copies leave the live doc, only one reaches the
    # archive — the Counter (not the set) difference must still see a loss.
    problems = verify_move("keep\n- r\n- r\n", "keep\n", "", "- r\n")
    assert problems == ["lost: - r"], f"repeated line half-dropped must be lost: {problems}"

    # Blank and whitespace-only lines dropped from the live doc (or landing
    # in the archive) are ignored.
    problems = verify_move("keep\n\n   \n- z\n\n\t\n", "keep\n", "", "\n  \n- z\n\n")
    assert problems == [], f"blank/whitespace-only removed lines must be ignored: {problems}"

    # The archive already holds "- e" before the move; the move drops "- e"
    # from the live doc but never adds it. Only the lines the move ADDED to
    # the archive count — a check against the whole post-move archive would
    # wrongly see "- e" as arrived.
    problems = verify_move(LIVE, "keep-me\n\n- a\n- b\n", "- e\n", "- e\n- c\n- d\n")
    assert problems == ["lost: - e"], f"pre-existing archive copy must not mask a loss: {problems}"

    # Archive pre-holds one "- r", the move adds one, the live doc dropped
    # two: one copy is lost.
    problems = verify_move("keep\n- r\n- r\n", "keep\n", "- r\n", "- r\n- r\n")
    assert problems == ["lost: - r"], f"only archive additions offset removals: {problems}"

    # The CLI exits 1 on exactly one problem.
    repo, base = _repo(tmp_path)
    write(repo, LIVE_REL, "keep\n- a\n")  # "- b" dropped, archive absent
    capsys.readouterr()
    rc = main(["--base", base, "--live", LIVE_REL, "--archive", ARCHIVE_REL,
               "--repo-root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["problems"] == ["lost: - b"], f"expected one lost problem: {payload}"
    assert rc == 1, f"CLI must exit 1 on a single problem, got {rc}"

    # CLI over a base whose archive already holds "- b": the live doc drops
    # "- b", the archive is left as-is -> lost, exit 1.
    write(repo, LIVE_REL, "keep\n- a\n- b\n")
    write(repo, ARCHIVE_REL, "- b\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "archive pre-holds - b")
    base2 = git(repo, "rev-parse", "HEAD")
    write(repo, LIVE_REL, "keep\n- a\n")
    capsys.readouterr()
    rc = main(["--base", base2, "--live", LIVE_REL, "--archive", ARCHIVE_REL,
               "--repo-root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["problems"] == ["lost: - b"], f"pre-existing archive copy masked a loss: {payload}"
    assert rc == 1, f"CLI must exit 1 on a lost line, got {rc}"

    # The CLI exits 1 on any problem kind, not only "lost": a lone undeclared
    # archive line (live doc unchanged).
    write(repo, LIVE_REL, "keep\n- a\n- b\n")
    write(repo, ARCHIVE_REL, "- b\nstray prose\n")
    capsys.readouterr()
    rc = main(["--base", base2, "--live", LIVE_REL, "--archive", ARCHIVE_REL,
               "--repo-root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["problems"] == ["unexpected-archive-line: stray prose"], payload
    assert rc == 1, f"CLI must exit 1 on any problem, got {rc}"


def test_line_written_twice_to_archive_fails_and_names_it():
    from verify_moves import verify_move

    problems = verify_move(LIVE, "keep-me\n\n- a\n- b\n", "", "- c\n- c\n- d\n- e\n")
    assert any(p.startswith("duplicated:") and "- c" in p for p in problems)


def test_prior_archive_line_deleted_fails_and_names_it():
    from verify_moves import verify_move

    problems = verify_move("", "", "- old-resolved\n", "")
    assert any(p.startswith("archive-removed:") and "- old-resolved" in p for p in problems)


def test_header_and_history_heading_scaffold_passes():
    from verify_moves import scaffold_lines, verify_move

    after_archive = ARCHIVE_HEADER[ARCHIVE_REL] + "## History\n\n" + MOVED
    assert verify_move(
        LIVE, "keep-me\n\n- a\n- b\n", "", after_archive,
        scaffold=scaffold_lines(ARCHIVE_REL, after_archive),
    ) == []


def test_undeclared_extra_prose_line_fails_and_names_it():
    from verify_moves import scaffold_lines, verify_move

    after_archive = MOVED + "\nUndeclared prose about the roadmap.\n"
    problems = verify_move(
        LIVE, "keep-me\n\n- a\n- b\n", "", after_archive,
        scaffold=scaffold_lines(ARCHIVE_REL, after_archive),
    )
    assert any(
        p.startswith("unexpected-archive-line:") and "Undeclared prose" in p
        for p in problems
    )


def test_repeated_table_header_and_delimiter_pass_as_scaffold():
    from verify_moves import scaffold_lines, verify_move

    before_live = "| Name | Status |\n|---|---|\n| one | Done |\n| two | Done |\n"
    live_after = "| Name | Status |\n|---|---|\n| one | Done |\n"
    archive_after = "| Name | Status |\n|---|---|\n| two | Done |\n"
    assert verify_move(
        before_live, live_after, "", archive_after,
        scaffold=scaffold_lines(ARCHIVE_REL, archive_after),
    ) == []


def test_repeated_table_header_fails_without_scaffold():
    from verify_moves import verify_move

    before_live = "| Name | Status |\n|---|---|\n| one | Done |\n| two | Done |\n"
    live_after = "| Name | Status |\n|---|---|\n| one | Done |\n"
    archive_after = "| Name | Status |\n|---|---|\n| two | Done |\n"
    problems = verify_move(before_live, live_after, "", archive_after)
    assert any(p.startswith("unexpected-archive-line:") for p in problems)


# --------------------------------------------------------------------------- #
# verify_reflow
# --------------------------------------------------------------------------- #


def test_reflow_bullet_split_onto_continuation_passes():
    from verify_moves import verify_reflow

    assert verify_reflow("- bullet one\n", "- bullet\n  one\n") == []


def test_reflow_blank_removal_passes():
    from verify_moves import verify_reflow

    assert verify_reflow("a\n\nb\n", "a\nb\n") == []


def test_reflow_changed_word_fails():
    from verify_moves import verify_reflow

    assert verify_reflow("- bullet one\n", "- bullet ONE\n") != []


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_clean_move_exit_zero(tmp_path):
    repo, base = _repo(tmp_path)
    write(repo, LIVE_REL, "keep\n- a\n")
    write(repo, ARCHIVE_REL, ARCHIVE_HEADER[ARCHIVE_REL] + "- b\n")
    proc = _cli(repo, ["--base", base, "--live", LIVE_REL, "--archive", ARCHIVE_REL])
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cli_dropped_line_exit_one_with_json(tmp_path):
    repo, base = _repo(tmp_path)
    write(repo, LIVE_REL, "keep\n- a\n")  # "- b" dropped in transit, archive absent
    proc = _cli(repo, [
        "--base", base, "--live", LIVE_REL, "--archive", ARCHIVE_REL, "--json",
    ])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert any(p.startswith("lost:") and "- b" in p for p in payload["problems"])
