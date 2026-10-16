"""Tests for the design-learn consumer-facing change flag.

The markdown under test is always a stand-in built from the string constants
below and written into a throwaway git repo; nothing here reads a real ``.md``
file back or asserts on markdown wording.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import consumer_facing_change as cfc  # noqa: E402

WATCHED_PATH = "skills/_shared/commit-after-work.md"

BASE = """# Commit After Work

Intro paragraph line.

## The protocol

Protocol rule one.
Protocol rule two.

## Task commits: red, then green

Red commit rule.
Green commit rule.

## Commit message conventions

Convention one.

## Hot-patch lane

Hot patch rule.
"""

PROTOCOL_EDIT = BASE.replace("Protocol rule one.", "Protocol rule one, rewritten.")
TASK_COMMITS_EDIT = BASE.replace("Red commit rule.", "Red commit rule, rewritten.")
CONVENTIONS_EDIT = BASE.replace("Convention one.", "Convention one, rewritten.")
HOTPATCH_EDIT = BASE.replace("Hot patch rule.", "Hot patch rule, rewritten.")
SPAN_EDIT = BASE.replace("Green commit rule.\n\n## Commit message conventions",
                         "Green commit rule, rewritten.\n\n## Commit message conventions")


def line_of(text, needle):
    """1-based line number of `needle` inside a constant."""
    return text.split("\n").index(needle) + 1


def sections_in(text):
    return [ln[3:] for ln in text.split("\n") if ln.startswith("## ")]


# -------------------------------------------------------------- flagged_sections

def test_hunk_in_task_commits_section_is_flagged():
    n = line_of(BASE, "Red commit rule.")
    got = cfc.flagged_sections(TASK_COMMITS_EDIT, [(n, 1)], cfc.WATCHED[WATCHED_PATH])
    assert got == ["Task commits: red, then green"]


def test_hunk_in_commit_message_conventions_is_flagged():
    n = line_of(BASE, "Convention one.")
    got = cfc.flagged_sections(CONVENTIONS_EDIT, [(n, 1)], cfc.WATCHED[WATCHED_PATH])
    assert got == ["Commit message conventions"]


def test_hunk_in_the_protocol_section_is_flagged():
    n = line_of(BASE, "Protocol rule one.")
    got = cfc.flagged_sections(PROTOCOL_EDIT, [(n, 1)], cfc.WATCHED[WATCHED_PATH])
    assert got == ["The protocol"]


def test_hunk_in_hot_patch_lane_is_not_flagged():
    n = line_of(BASE, "Hot patch rule.")
    got = cfc.flagged_sections(HOTPATCH_EDIT, [(n, 1)], cfc.WATCHED[WATCHED_PATH])
    assert got == []


def test_pure_deletion_maps_to_section_holding_new_start():
    # git reports a `-U0` deletion at the new-side line it followed.
    n = line_of(BASE, "Convention one.")
    got = cfc.flagged_sections(CONVENTIONS_EDIT, [(n - 1, 0)], cfc.WATCHED[WATCHED_PATH])
    assert got == ["Commit message conventions"]


def test_pure_deletion_in_the_protocol_section_is_flagged():
    n = line_of(BASE, "Protocol rule two.")
    got = cfc.flagged_sections(PROTOCOL_EDIT, [(n - 1, 0)], cfc.WATCHED[WATCHED_PATH])
    assert got == ["The protocol"]


def test_hunk_spanning_two_sections_names_both():
    n = line_of(BASE, "Green commit rule.")
    got = cfc.flagged_sections(SPAN_EDIT, [(n, 3)], cfc.WATCHED[WATCHED_PATH])
    assert got == ["Task commits: red, then green", "Commit message conventions"]


def test_multiple_hunks_report_each_section_once():
    a = line_of(BASE, "Protocol rule one.")
    b = line_of(BASE, "Convention one.")
    got = cfc.flagged_sections(CONVENTIONS_EDIT, [(a, 1), (b, 1)], cfc.WATCHED[WATCHED_PATH])
    assert got == ["The protocol", "Commit message conventions"]


def test_titles_none_counts_whole_file():
    n = line_of(BASE, "Hot patch rule.")
    got = cfc.flagged_sections(HOTPATCH_EDIT, [(n, 1)], None)
    assert got == sections_in(BASE)


def test_no_hunks_is_not_flagged():
    assert cfc.flagged_sections(BASE, [], cfc.WATCHED[WATCHED_PATH]) == []


# ---------------------------------------------------------------- git helpers

def init_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "skills" / "_shared").mkdir(parents=True)
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["init", "-q"], check=True)
    subprocess.run(git + ["config", "user.name", "Tester"], check=True)
    subprocess.run(git + ["config", "user.email", "t@example.com"], check=True)
    return repo


def write_and_commit(repo, text, message):
    (repo / WATCHED_PATH).write_text(text, encoding="utf-8")
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", message], check=True)


def rev(repo, spec):
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", spec],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


# -------------------------------------------------------------------- check

def test_check_flags_protocol_edit(tmp_path):
    repo = init_repo(tmp_path)
    write_and_commit(repo, BASE, "base")
    write_and_commit(repo, PROTOCOL_EDIT, "edit")
    rng = "%s..%s" % (rev(repo, "HEAD~1"), rev(repo, "HEAD"))
    out = cfc.check(rng, root=str(repo))
    assert out["flagged"] is True, "the protocol-section edit was left unflagged"
    assert out["hits"] == [{"path": WATCHED_PATH, "sections": ["The protocol"]}], \
        "the hit does not name exactly the protocol section"


def test_check_flags_task_commits_edit(tmp_path):
    repo = init_repo(tmp_path)
    write_and_commit(repo, BASE, "base")
    write_and_commit(repo, TASK_COMMITS_EDIT, "edit")
    out = cfc.check("HEAD~1...HEAD", root=str(repo))
    assert out["flagged"] is True
    assert out["hits"][0]["sections"] == ["Task commits: red, then green"]


def test_check_does_not_flag_hot_patch_edit(tmp_path):
    repo = init_repo(tmp_path)
    write_and_commit(repo, BASE, "base")
    write_and_commit(repo, HOTPATCH_EDIT, "edit")
    out = cfc.check("HEAD~1...HEAD", root=str(repo))
    assert out == {"flagged": False, "hits": []}


def test_check_unwatched_path_is_not_flagged(tmp_path):
    repo = init_repo(tmp_path)
    write_and_commit(repo, BASE, "base")
    (repo / "skills" / "_shared" / "other.md").write_text("## The protocol\n\nRule.\n",
                                                          encoding="utf-8")
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "other"], check=True)
    out = cfc.check("HEAD~1...HEAD", root=str(repo))
    assert out == {"flagged": False, "hits": []}


def test_check_bad_range_is_not_flagged(tmp_path):
    repo = init_repo(tmp_path)
    write_and_commit(repo, BASE, "base")
    out = cfc.check("nope..also-nope", root=str(repo))
    assert out == {"flagged": False, "hits": []}


def test_check_no_commits_is_not_flagged(tmp_path):
    out = cfc.check("HEAD~1...HEAD", root=str(tmp_path))
    assert out == {"flagged": False, "hits": []}


# --------------------------------------------------------------------- CLI

def run_cli(args, repo):
    return subprocess.run([sys.executable, str(cfc.__file__)] + args +
                          ["--root", str(repo)], capture_output=True, text=True)


def test_cli_prints_one_json_line_and_exits_zero(tmp_path):
    repo = init_repo(tmp_path)
    write_and_commit(repo, BASE, "base")
    write_and_commit(repo, CONVENTIONS_EDIT, "edit")
    proc = run_cli(["check", "--range", "HEAD~1...HEAD"], repo)
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["flagged"] is True
    assert payload["hits"][0]["sections"] == ["Commit message conventions"]


def test_cli_bad_range_exits_zero_with_false(tmp_path):
    repo = init_repo(tmp_path)
    write_and_commit(repo, BASE, "base")
    proc = run_cli(["check", "--range", "bogus..bogus"], repo)
    assert proc.returncode == 0
    assert json.loads(proc.stdout.strip()) == {"flagged": False, "hits": []}
