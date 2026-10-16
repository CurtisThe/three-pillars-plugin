"""The design-dir `decisions.md` lane in the shared byte path (basesync-three-way-verifier Task 5.3).

Spec: detailed-design.md Interfaces (`resolve_conflict_bytes_detail`). With `path` set to a design's
`decisions.md`, the shared byte path takes `decisions_union.union_decisions` BEFORE diff3 and returns
`(RESOLVED, union, True)`; every other path, `path=None`, and every shape the union refuses behave
exactly as the call without `path`. The driver passes the path, so a real `merge_back` where both
sides append entries resolves that file to the union bytes. The texts are the #206 shape: two heading
tails with a table, a fence, `- flag:` bullets and HTML comments, which diff3 alone defers. A deferral
carries a per-call marker nonce, so off-lane results compare with the nonce normalised away
(skills/_shared/test-fragility.md: assert the contract, not incidental bytes).
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from decisions_union import union_decisions  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from resolve import DEFER, RESOLVED  # noqa: E402
from task_scope import _git_env  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from auto_safe_resolution import (  # noqa: E402
    resolve_conflict_bytes, resolve_conflict_bytes_detail)

LANE = "three-pillars-docs/tp-designs/x/decisions.md"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
BASE = "# Decisions\n\n### [tp-plan] first\n**Decided**: yes\n"
TAIL_O = (
    "### [tp-plan-audit] round 1 results\n"
    "| finding | verdict |\n|---|---|\n| F1 | bind |\n"
    "```python\nx = 1\n```\n"
    "- flag: --auto\n- flag: --spike\n"
    "<!-- keep: a note -->\n"
    "**Decided**: bind F1\n"
)
TAIL_T = (
    "### [tp-implement] worker flags\n"
    "- flag: --local\n"
    "```\nsh -c true\n```\n"
    "<!-- closed -->\n"
)
OURS, THEIRS = BASE + "\n" + TAIL_O, BASE + "\n" + TAIL_T
UNION = BASE + "\n" + TAIL_O + "\n" + TAIL_T
NONCE = re.compile(r"\b(ours|base|theirs)-[0-9a-f]{32}\b")


def _norm(result):
    status, merged, *rest = result
    return (status, NONCE.sub(r"\1-N", merged), *rest)


def _detail(path=None, base=BASE, ours=OURS, theirs=THEIRS):
    return resolve_conflict_bytes_detail(base=base, ours=ours, theirs=theirs, path=path)


def test_the_lane_takes_the_union_before_diff3():
    assert _detail()[0] == DEFER      # the premise: diff3 alone defers this shape
    assert _detail(LANE) == (RESOLVED, UNION, True)
    assert _detail(LANE)[1] == union_decisions(BASE, OURS, THEIRS)


def test_every_off_lane_path_behaves_as_the_call_without_path():
    want = _norm(_detail())
    for path in (None, "three-pillars-docs/completed-tp-designs/x/decisions.md",
                 "three-pillars-docs/known_issues.md",
                 "three-pillars-docs/tp-designs/../decisions.md",
                 "three-pillars-docs/tp-designs/./decisions.md",
                 "three-pillars-docs/tp-designs/x/decisions.md\n",
                 "three-pillars-docs/tp-designs/x/y/decisions.md"):
        assert _norm(_detail(path)) == want, path


def test_a_shape_the_union_refuses_behaves_as_the_call_without_path():
    ours, theirs = BASE + "**Outcome**: shipped\n", BASE + "**Why**: cost\n"
    assert union_decisions(BASE, ours, theirs) is None      # two continuation tails
    on_lane = _detail(LANE, ours=ours, theirs=theirs)
    assert on_lane[0] == DEFER
    assert _norm(on_lane) == _norm(_detail(ours=ours, theirs=theirs))


def test_resolve_conflict_bytes_forwards_path():
    assert resolve_conflict_bytes(base=BASE, ours=OURS, theirs=THEIRS, path=LANE) == (
        RESOLVED, UNION)
    assert resolve_conflict_bytes(base=BASE, ours=OURS, theirs=THEIRS)[0] == DEFER


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=_git_env(**IDENT))


def _commit(repo, text, msg):
    p = repo / LANE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def test_merge_back_auto_resolves_a_design_decisions_append_to_the_union(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _commit(repo, BASE, "base")
    _git(repo, "checkout", "-q", "-b", "design")
    _commit(repo, OURS, "ours")
    _git(repo, "checkout", "-q", "master")
    _commit(repo, THEIRS, "theirs")
    _git(repo, "checkout", "-q", "design")

    report = merge_back(str(repo), "master")

    assert LANE in report.auto_resolved, report.to_json()
    assert LANE not in report.deferred and LANE not in report.partially_resolved
    assert (repo / LANE).read_text(encoding="utf-8") == union_decisions(BASE, OURS, THEIRS) == UNION
    assert LANE not in _git(repo, "diff", "--name-only", "--diff-filter=U").stdout
