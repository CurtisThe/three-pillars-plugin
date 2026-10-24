"""Task 1.3: the first-parent chain walk of proof_neutral_carry (link and line caps).

`strip_proof_neutral_commits` steps past at most 4 links (round-log or neutral) and at most 200
neutral changed lines, then returns the anchor; anything else stops the walk where it is, which
fails closed. The oracle is example-based: each case builds a real commit chain in a throwaway
git repo, scrubbed of `GIT_*` env, and reads the `NeutralStripResult`.
"""
import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import proof_neutral_carry as pnc  # noqa: E402

ARCH = "three-pillars-docs/completed-tp-designs/demo"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def commit(repo, files, msg="c"):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def grow(repo, rel, n_lines, tag="n"):
    """Append `n_lines` fresh lines to `rel` and commit: a neutral doc commit of n_lines changes."""
    old = (repo / rel).read_text(encoding="utf-8") if (repo / rel).exists() else ""
    extra = "".join(f"{tag} {len(old)} {i}\n" for i in range(n_lines))
    return commit(repo, {rel: old + extra})


def strip(repo, head, **kw):
    return pnc.strip_proof_neutral_commits(repo, head, **kw)


@pytest.fixture
def repo(tmp_path):
    """root -> P: P adds the archived design `demo` and changes code, so P is not neutral."""
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, {"README.md": "readme\n", "src.py": "x = 1\n"}, "root")
    p = commit(tmp_path, {f"{ARCH}/design.md": "d\n", f"{ARCH}/decisions.md": "a\n",
                          "src.py": "x = 2\n"}, "P")
    return tmp_path, p


def test_result_is_a_frozen_dataclass_with_the_five_fields():
    res = pnc.NeutralStripResult("a", 1, 1, 2, "why")
    assert (res.anchor, res.links, res.neutral_links, res.lines, res.reason) == ("a", 1, 1, 2, "why")
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.anchor = "b"


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_up_to_four_neutral_commits_are_stripped(repo, n):
    r, p = repo
    head = [grow(r, "README.md", 1, f"c{i}") for i in range(n)][-1]
    res = strip(r, head)
    assert res.anchor == p
    assert res.links == res.neutral_links == n
    assert res.lines == n


def test_five_neutral_commits_stop_at_the_link_cap(repo):
    r, p = repo
    shas = [grow(r, "README.md", 1, f"c{i}") for i in range(5)]
    res = strip(r, shas[-1])
    assert res.anchor == shas[0]  # the first commit above P is the one left unstripped
    assert res.links == res.neutral_links == 4
    assert "cap" in res.reason


def test_exactly_the_line_cap_is_stripped(repo):
    r, p = repo
    res = strip(r, grow(r, "README.md", 200))
    assert res.anchor == p
    assert res.neutral_links == 1
    assert res.lines == 200


def test_one_line_over_the_cap_stops_at_that_commit(repo):
    r, p = repo
    head = grow(r, "README.md", 201)
    res = strip(r, head)
    assert res.anchor == head
    assert res.links == res.neutral_links == res.lines == 0
    assert "lines" in res.reason


def test_the_line_cap_adds_up_across_the_chain(repo):
    r, p = repo
    older = grow(r, "README.md", 100, "a")
    newer = grow(r, "README.md", 101, "b")
    res = strip(r, newer)  # the walk meets the 101-line commit first, then the 100-line one
    assert res.anchor == older
    assert res.neutral_links == 1
    assert res.lines == 101
    assert "lines" in res.reason
    assert strip(r, older).anchor == p


def test_round_log_link_counts_toward_links_but_not_lines(repo):
    r, p = repo
    log = commit(r, {f"{ARCH}/decisions.md": "a\n" + "".join(f"r{i}\n" for i in range(300))})
    head = grow(r, "README.md", 7)
    res = strip(r, head)
    assert res.anchor == p
    assert res.links == 2
    assert res.neutral_links == 1
    assert res.lines == 7
    assert strip(r, log).lines == 0


def test_round_log_links_count_toward_the_link_cap(repo):
    r, p = repo
    logs = [commit(r, {f"{ARCH}/decisions.md": "a\n" + f"r{i}\n" * (i + 1)}) for i in range(5)]
    res = strip(r, logs[-1])
    assert res.anchor == logs[0], "round-log links count toward the link cap (4, 200)"
    assert res.links == 4
    assert res.neutral_links == 0
    assert "cap" in res.reason
    assert strip(r, logs[3]).anchor == p


def test_code_commit_stops_the_walk(repo):
    r, p = repo
    code = commit(r, {"src.py": "x = 3\n"})
    head = grow(r, "README.md", 1)
    res = strip(r, head)
    assert res.anchor == code
    assert res.links == res.neutral_links == 1
    assert res.reason


def test_merge_commit_stops_the_walk(repo):
    r, p = repo
    git(r, "checkout", "-q", "-b", "side")
    commit(r, {"side.md": "side\n"}, "side")
    git(r, "checkout", "-q", "main")
    commit(r, {"main.md": "main\n"}, "main")
    git(r, "merge", "-q", "--no-ff", "--no-edit", "side")
    merge = git(r, "rev-parse", "HEAD")
    res = strip(r, merge)
    assert res.anchor == merge
    assert res.links == 0
    assert "merge commit" in res.reason
    above = grow(r, "README.md", 1)
    res = strip(r, above)
    assert res.anchor == merge
    assert res.links == 1
    assert "merge commit" in res.reason


def test_root_commit_stops_the_walk(repo):
    r, p = repo
    root = git(r, "rev-list", "--max-parents=0", "HEAD")
    res = strip(r, root)
    assert res.anchor == root
    assert res.links == 0
    assert "root commit" in res.reason


def test_an_unresolvable_head_has_no_anchor(repo):
    r, p = repo
    res = strip(r, "0" * 40)
    assert res.anchor is None
    assert res.links == res.neutral_links == res.lines == 0
    assert res.reason


def test_a_raising_run_git_has_no_anchor_and_never_raises(repo):
    r, p = repo

    def boom(args):
        raise RuntimeError("git exploded")

    res = strip(r, p, run_git=boom)
    assert res.anchor is None
    assert res.links == 0
    assert res.reason


def test_a_failing_run_git_has_no_anchor(repo):
    r, p = repo
    assert strip(r, p, run_git=lambda args: (1, "", "no")).anchor is None


def test_caps_are_overridable(repo):
    r, p = repo
    first = grow(r, "README.md", 1, "a")
    head = grow(r, "README.md", 1, "b")
    res = strip(r, head, max_links=1)
    assert res.anchor == first
    assert res.links == 1
    big = grow(r, "README.md", 6, "c")
    res = strip(r, big, max_lines=5)
    assert res.anchor == big
    assert "lines" in res.reason
    assert strip(r, big, max_lines=6).anchor == head


def big_readme(repo, n=250):
    """A NON-neutral commit (touches src.py) that makes README.md n lines; returns (sha, lines)."""
    lines = [f"b{i}\n" for i in range(n)]
    return commit(repo, {"src.py": "x = 9\n", "README.md": "".join(lines)}), lines


def test_deleted_lines_count_toward_the_line_cap(repo):
    r, p = repo
    base, lines = big_readme(r)
    head = commit(r, {"README.md": ""})  # 0 added, 250 deleted
    # `in` (not `==`) so a failure's message keeps pytest's `where ... = strip(...)` chain
    assert strip(r, head).anchor in (head,)
    res = strip(r, head)
    assert res.lines == 0
    assert "lines" in res.reason


def test_default_caps_are_the_design_constants():
    assert (pnc.MAX_LINKS, pnc.MAX_LINES) == (4, 200)
