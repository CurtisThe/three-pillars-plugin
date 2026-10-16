"""The shared path predicate `round_log_slug` (archived round-log file OR a run ruling file) and
the ruling-aware shape of `is_round_log_commit` (fable-escalation 4.7).

A run's two-stable flush commits an archived round-log file *and* the run's ruling file, so the
carry must accept that shape; a ruling-only commit, a seat ruling, or a ruling belonging to a
different design never is a round-log commit.

Run with: pytest skills/_shared/test_round_log_carry_rulings.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import round_log_carry  # noqa: E402
from round_log_carry import strip_round_log_commits  # noqa: E402

ARCH = "three-pillars-docs/completed-tp-designs"
RULINGS = "three-pillars-docs/escalations/rulings"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def _commit(repo, files, msg="c"):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            p.unlink()
        else:
            p.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    parent = _commit(tmp_path, {f"{ARCH}/demo/design.md": "d\n", f"{ARCH}/demo/decisions.md": "a\n",
                                f"{ARCH}/other/design.md": "d\n"})
    return tmp_path, parent


def _seam(repo_root):
    def _run(args):
        r = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True)
        return (r.returncode, r.stdout.decode("utf-8", "surrogateescape"),
                r.stderr.decode("utf-8", "surrogateescape"))
    return _run


def _classify(repo, parent, files):
    h = _commit(repo, files)
    return round_log_carry.is_round_log_commit(_seam(repo), parent, h)


# ---------------------------------------------------------------- round_log_slug (pure)

@pytest.mark.parametrize("name", list(round_log_carry.ROUND_LOG_NAMES))
def test_slug_of_archived_log_file(name):
    path = f"{ARCH}/demo/{name}"
    assert round_log_carry.round_log_slug(path) == "demo"


def test_slug_of_a_run_ruling_file():
    assert round_log_carry.round_log_slug(f"{RULINGS}/demo-20261011-abcdef.md") == "demo"


def test_slug_of_a_ruling_for_a_multi_word_design():
    assert round_log_carry.round_log_slug(
        f"{RULINGS}/seat-quiet-watch-20261011-abcdef.md") == "seat-quiet-watch"


@pytest.mark.parametrize("path", [
    f"{RULINGS}/seat-20261011-abcdef.md",            # a seat ruling is never a design's
    f"{RULINGS}/Demo-20261011-abcdef.md",            # not ID_RE
    f"{RULINGS}/demo_20261011-abcdef.md",            # not ID_RE
    f"{RULINGS}/demo-20261011-abcde.md",             # 5 hex chars
    f"{RULINGS}/demo-20261011-abcdefg.md",           # 7 hex chars
    f"{RULINGS}/demo-20261011-abcdef.txt",           # wrong suffix
    f"{RULINGS}/demo-2026101-abcdef.md",             # 7-digit date
    f"{RULINGS}/demo-202610111-abcdef.md",           # 9-digit date
    f"{RULINGS}/sub/demo-20261011-abcdef.md",        # nested under the rulings dir
    f"{RULINGS}/demo-20261011-abcdef.md/extra",      # nested under the rulings dir
    "three-pillars-docs/escalations/rulings/demo-20261011-abcdef.md.bak",
    "three-pillars-docs/tp-designs/demo/decisions.md",
    "three-pillars-docs/tp-designs/demo/rulings/demo-20261011-abcdef.md",
    f"{ARCH}/demo/design.md",                        # not a round-log name
    f"{ARCH}/demo/nested/decisions.md",              # nested archive path
    f"{ARCH}/Demo/decisions.md",                     # bad slug
    f"{ARCH}/demo/decisions.md/extra",               # nested archive path
    "skills/_shared/round_log_carry.py",
    "",
])
def test_slug_is_none_for_anything_else(path):
    assert round_log_carry.round_log_slug(path) is None


def test_rulings_prefix_constant():
    assert round_log_carry.RULINGS_PREFIX == "three-pillars-docs/escalations/rulings/"


# ------------------------------------------------------- is_round_log_commit (real git repo)

def test_archived_log_plus_own_ruling_is_accepted(repo):
    r, parent = repo
    ok, why = _classify(r, parent, {
        f"{ARCH}/demo/decisions.md": "a\nflush\n",
        f"{RULINGS}/demo-20261011-abcdef.md": "# ruling\n",
    })
    assert (ok, why) == (True, "")


def test_archived_logs_and_a_ruling_are_accepted(repo):
    r, parent = repo
    ok, _ = _classify(r, parent, {
        f"{ARCH}/demo/decisions.md": "a\nflush\n",
        f"{ARCH}/demo/dispatch-telemetry.ndjson": "{}\n",
        f"{ARCH}/demo/escape-ledger.ndjson": "{}\n",
        f"{RULINGS}/demo-20261011-abcdef.md": "# ruling\n",
    })
    assert ok


@pytest.mark.parametrize("ruling", [
    f"{RULINGS}/other-20261011-abcdef.md",      # another design's ruling
    f"{RULINGS}/seat-20261011-abcdef.md",       # a seat ruling
    f"{RULINGS}/demo-2026101-abcdef.md",        # not ID_RE
    f"{RULINGS}/demo-20261011-abcdef.txt",      # wrong suffix
    f"{RULINGS}/sub/demo-20261011-abcdef.md",   # nested
])
def test_bad_ruling_in_a_flush_is_rejected(repo, ruling):
    r, parent = repo
    ok, why = _classify(r, parent, {
        f"{ARCH}/demo/decisions.md": "a\nflush\n",
        ruling: "# ruling\n",
    })
    assert not ok
    assert why


def test_ruling_delete_is_rejected(repo):
    r, parent = repo
    first = _commit(r, {f"{RULINGS}/demo-20261011-abcdef.md": "# ruling\n"})
    ok, why = _classify(r, first, {
        f"{ARCH}/demo/decisions.md": "a\nflush\n",
        f"{RULINGS}/demo-20261011-abcdef.md": None,
    })
    assert not ok
    assert why


def test_ruling_only_commit_is_rejected(repo):
    r, parent = repo
    ok, why = _classify(r, parent, {f"{RULINGS}/demo-20261011-abcdef.md": "# ruling\n"})
    assert (ok, why) == (False, "no archived round-log file")


def test_two_rulings_of_two_designs_is_rejected(repo):
    r, parent = repo
    ok, why = _classify(r, parent, {
        f"{ARCH}/demo/decisions.md": "a\nflush\n",
        f"{RULINGS}/demo-20261011-abcdef.md": "# r\n",
        f"{RULINGS}/other-20261011-abcdef.md": "# r\n",
    })
    assert not ok
    assert why


def test_ruling_outside_the_rulings_dir_is_rejected(repo):
    r, parent = repo
    ok, why = _classify(r, parent, {
        f"{ARCH}/demo/decisions.md": "a\nflush\n",
        "three-pillars-docs/escalations/demo-20261011-abcdef.md": "# r\n",
    })
    assert not ok
    assert "outside the archive" in why


def test_strip_carries_across_a_flush_with_a_ruling(repo):
    r, parent = repo
    h = _commit(r, {f"{ARCH}/demo/decisions.md": "a\nflush\n",
                    f"{RULINGS}/demo-20261011-abcdef.md": "# ruling\n"})
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (parent, 1)


def test_strip_does_not_carry_a_ruling_only_commit(repo):
    r, _ = repo
    h = _commit(r, {f"{RULINGS}/demo-20261011-abcdef.md": "# ruling\n"})
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (h, 0)
    assert res.reason == "no archived round-log file"
