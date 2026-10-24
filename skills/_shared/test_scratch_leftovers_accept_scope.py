"""`accept` writes only a design's decisions.md, and a re-accept replaces the earlier entry for its path.

design: run-scratch-in-fence (impl-audit retry, item 6). `--design-dir D` may name only
`<repo>/three-pillars-docs/{tp-designs,completed-tp-designs}/<slug>` (the worktree, the
baseline's worktree or the seat checkout); anything else exits 2 and writes nothing. An
accepted directory stays accepted whatever later changes below it.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_scratch_leftovers import SLUG, fx  # noqa: E402,F401  (fixture)


def stray(fx, *children):
    fx.run("provision")
    p = fx.tmp / "sibling"
    p.mkdir()
    for c in children:
        (p / c).parent.mkdir(parents=True, exist_ok=True)
        (p / c).write_text("x", encoding="utf-8")
    return p


def accepted(fx):
    return json.loads(fx.baseline.read_text(encoding="utf-8"))["accepted"]


def accept(fx, p, *extra):
    return fx.run("accept", "--path", str(p), "--reason", "inspected", *extra)


def later(path, seconds=5):
    st = os.lstat(path)
    ns = st.st_mtime_ns + seconds * 10**9
    os.utime(path, ns=(ns, ns), follow_symlinks=False)


@pytest.mark.parametrize("rel", [
    "three-pillars-docs/tp-designs/" + SLUG,
    "three-pillars-docs/completed-tp-designs/" + SLUG,
])
def test_design_dir_inside_the_repo_design_dirs_is_accepted(fx, rel):
    d = fx.wt / rel
    d.mkdir(parents=True)
    p = stray(fx)
    assert accept(fx, p, "--design-dir", str(d))[0] == 0
    assert "accepted %s" % p in (d / "decisions.md").read_text(encoding="utf-8")


def test_design_dir_elsewhere_exits_2_and_writes_nothing(fx):
    p = stray(fx)
    for d in (fx.root / "elsewhere", fx.home, fx.tmp):
        d.mkdir(exist_ok=True)
        rc, out = accept(fx, p, "--design-dir", str(d))
        assert rc == 2 and "design-dir" in out, d
        assert not (d / "decisions.md").exists() and accepted(fx) == []


@pytest.mark.parametrize("rel", [
    "three-pillars-docs/tp-designs/other",
    "three-pillars-docs/specs/" + SLUG,
    "docs/tp-designs/" + SLUG,
])
def test_design_dir_with_the_wrong_slug_or_parent_exits_2(fx, rel):
    d = fx.wt / rel
    d.mkdir(parents=True)
    p = stray(fx)
    assert accept(fx, p, "--design-dir", str(d))[0] == 2
    assert not (d / "decisions.md").exists() and accepted(fx) == []


def test_design_dir_that_is_a_symlink_out_of_the_tree_exits_2(fx):
    target = fx.root / "elsewhere"
    target.mkdir()
    parent = fx.wt / "three-pillars-docs" / "tp-designs"
    parent.mkdir(parents=True)
    (parent / SLUG).symlink_to(target)
    p = stray(fx)
    assert accept(fx, p, "--design-dir", str(parent / SLUG))[0] == 2
    assert not (target / "decisions.md").exists()


def test_design_dir_dotdot_out_of_the_design_dir_exits_2(fx):
    d = fx.wt / "three-pillars-docs" / "tp-designs" / SLUG
    d.mkdir(parents=True)
    p = stray(fx)
    sneaky = d / ".." / ".." / ".." / ".."
    assert accept(fx, p, "--design-dir", str(sneaky))[0] == 2


def design_dir(fx):
    d = fx.wt / "three-pillars-docs" / "tp-designs" / SLUG
    d.mkdir(parents=True)
    return d


def test_an_unchanged_accepted_dir_stays_a_scratch_allowed_line(fx):
    design_dir(fx)
    p = stray(fx, "a/f")
    assert accept(fx, p)[0] == 0
    for _ in range(2):
        rc, out = fx.run("check")
        assert rc == 0 and "scratch-allowed: %s (accepted " % p in out


def test_a_file_created_below_an_accepted_dir_leaves_check_green(fx):
    """Accepting a dir accepts what lies below it; a later change there does not re-fire."""
    design_dir(fx)
    p = stray(fx, "a")
    assert accept(fx, p)[0] == 0
    new = p / "deep" / "er" / "new"
    new.parent.mkdir(parents=True)
    new.write_text("y", encoding="utf-8")
    for q in (new, new.parent, p / "deep", p):
        later(q, 10)
    rc, out = fx.run("check")
    assert rc == 0 and "scratch-allowed: %s (accepted " % p in out
    assert "changed below" not in out and "scratch-leftover:" not in out


def test_re_accepting_a_path_replaces_the_earlier_entry(fx):
    design_dir(fx)
    p = stray(fx, "a")
    assert accept(fx, p)[0] == 0
    assert fx.run("accept", "--path", str(p), "--reason", "second look")[0] == 0
    (entry,) = accepted(fx)
    assert entry["path"] == str(p) and entry["reason"] == "second look"
    rc, out = fx.run("check")
    assert rc == 0 and out.count("scratch-allowed: %s (accepted " % p) == 1
