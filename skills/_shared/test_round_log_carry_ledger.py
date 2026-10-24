"""round_log_carry: `finalizer-ledger.json` is a round-log name and an archived file.

A commit that flushes `decisions.md` and rewrites `finalizer-ledger.json` of one archived design is
a round-log commit; the name tuple has one definition (review_readiness aliases it) and every name
in it is archive-allowlisted, so the step-6e2 prune never drops a name the carry strips.

Run with: python3 -m pytest skills/_shared/test_round_log_carry_ledger.py
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import archive_allowlist  # noqa: E402
import review_readiness  # noqa: E402
import round_log_carry  # noqa: E402
from round_log_carry import strip_round_log_commits  # noqa: E402
from test_round_log_carry import ARCH, _env, commit, git, repo  # noqa: E402,F401

LEDGER = "finalizer-ledger.json"


def _flush(r, text):
    return commit(r, {f"{ARCH}/demo/decisions.md": f"a\n{text}\n",
                      f"{ARCH}/demo/{LEDGER}": f'{{"v": "{text}"}}\n'})


def test_ledger_added_with_decisions_is_stripped(repo):
    r, p = repo
    h = _flush(r, "one")
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (p, 1)


def test_ledger_whole_file_rewrite_is_stripped(repo):
    r, p = repo
    _flush(r, "one")  # adds the ledger (A)
    h = _flush(r, "two")  # rewrites the whole ledger file (M)
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (p, 2)


def test_ledger_rewrite_alone_is_one_link(repo):
    r, _ = repo
    first = _flush(r, "one")
    h = commit(r, {f"{ARCH}/demo/{LEDGER}": '{"v": "rewritten"}\n'})
    res = strip_round_log_commits(r, h, max_links=1)
    assert (res.anchor, res.links) == (first, 1)


def test_ledger_with_code_file_is_not_stripped(repo):
    r, _ = repo
    h = commit(r, {f"{ARCH}/demo/decisions.md": "z\n", f"{ARCH}/demo/{LEDGER}": "{}\n",
                   "skills/x.py": "x\n"})
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (h, 0)
    assert res.reason


def test_four_ledger_commits_stop_at_the_cap(repo):
    r, _ = repo
    shas = [_flush(r, f"n{i}") for i in range(4)]
    res = strip_round_log_commits(r, shas[3], max_links=3)
    assert res.links == 3
    assert res.anchor == shas[0]
    assert "cap" in res.reason


def test_round_log_names_have_one_definition():
    assert review_readiness._ROUND_LOG_NAMES is round_log_carry.ROUND_LOG_NAMES


def test_every_round_log_name_is_archive_allowlisted():
    for name in round_log_carry.ROUND_LOG_NAMES:
        assert name in archive_allowlist.ALLOWLIST, name


def test_skill_md_names_ledger():
    text = (_HERE.parent / "tp-design-complete" / "SKILL.md").read_text(encoding="utf-8")
    assert f"`{LEDGER}`" in text
