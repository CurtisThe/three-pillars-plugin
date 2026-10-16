"""test_finalizer_effects.py — post-hoc check + injectable gh/git seams.

design: fable-first-stops (Task 1.6)

No test here ever calls a real `gh` or `git`: every seam is injected, and the
default seams take a `runner` argument that records argv (lists, never
`shell=True`).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finalizer_effects as fe  # noqa: E402

URL = "https://github.com/x/y/pull/7"
HEAD = "a1" * 20  # pre-stop head
CHILD = "b2" * 20  # a descendant of HEAD
UNRELATED = "c3" * 20

STOP = {"source": "pr-iterate", "signal": "round-cap", "target": URL, "head": HEAD}


class Proc:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def state_fn(state, oid):
    def fn(_url):
        return {"state": state, "headRefOid": oid}
    return fn


def test_posthoc_pr_merged_violation():
    r = fe.posthoc(STOP, URL, pr_state_fn=state_fn("merged", CHILD),
                   is_ancestor_fn=lambda a, b: True)
    assert r == {"ok": False, "violation": "pr-merged"}


def test_posthoc_pr_merged_real_gh_uppercase():
    # `gh pr view --json state` returns the uppercase enum MERGED, not "merged".
    out = json.dumps({"state": "MERGED", "headRefOid": CHILD})
    runner = lambda argv, **kw: Proc(0, out, "")  # noqa: E731
    seam = lambda url: fe.default_pr_state_fn(url, runner=runner)  # noqa: E731
    r = fe.posthoc(STOP, URL, pr_state_fn=seam, is_ancestor_fn=lambda a, b: True)
    assert r == {"ok": False, "violation": "pr-merged"}


def test_posthoc_head_rewritten_violation():
    r = fe.posthoc(STOP, URL, pr_state_fn=state_fn("OPEN", UNRELATED),
                   is_ancestor_fn=lambda a, b: False)
    assert r == {"ok": False, "violation": "head-rewritten"}


def test_posthoc_clean_fix_forward_descends():
    r = fe.posthoc(STOP, URL, pr_state_fn=state_fn("OPEN", CHILD),
                   is_ancestor_fn=lambda a, b: a == HEAD and b == CHILD)
    assert r == {"ok": True}


def test_posthoc_clean_head_unchanged():
    r = fe.posthoc(STOP, URL, pr_state_fn=state_fn("OPEN", HEAD),
                   is_ancestor_fn=lambda a, b: a == HEAD and b == HEAD)
    assert r == {"ok": True}


def test_posthoc_no_head_unverified():
    stop = {"source": "pr-iterate", "signal": "round-cap", "target": URL}
    called = []
    r = fe.posthoc(stop, URL,
                   pr_state_fn=lambda u: called.append(1)
                   or {"state": "OPEN", "headRefOid": CHILD},
                   is_ancestor_fn=lambda a, b: called.append(2) or True)
    assert r["ok"] is True
    assert isinstance(r["unverified"], str) and r["unverified"]
    assert not called  # nothing to check without a pre-stop head


def test_posthoc_pr_state_seam_raises_unverified():
    def boom(_url):
        raise RuntimeError("gh died")
    r = fe.posthoc(STOP, URL, pr_state_fn=boom, is_ancestor_fn=lambda a, b: True)
    assert r["ok"] is True
    assert isinstance(r["unverified"], str) and r["unverified"]


def test_posthoc_ancestor_seam_raises_unverified():
    def boom(a, b):
        raise RuntimeError("git missing")
    r = fe.posthoc(STOP, URL, pr_state_fn=state_fn("OPEN", CHILD), is_ancestor_fn=boom)
    assert r["ok"] is True
    assert isinstance(r["unverified"], str) and r["unverified"]


def test_default_pr_state_gh_missing_unverified():
    def no_gh(argv, **kw):
        raise FileNotFoundError(2, "No such file or directory", "gh")
    seam = lambda url: fe.default_pr_state_fn(url, runner=no_gh)  # noqa: E731
    r = fe.posthoc(STOP, URL, pr_state_fn=seam, is_ancestor_fn=lambda a, b: True)
    assert r["ok"] is True
    assert isinstance(r["unverified"], str) and r["unverified"]


def test_default_pr_state_parses_real_gh_output():
    out = json.dumps({"state": "MERGED", "headRefOid": CHILD})
    calls = []

    def runner(argv, **kw):
        calls.append((argv, kw))
        return Proc(0, out, "")

    info = fe.default_pr_state_fn(URL, runner=runner)
    assert info == {"state": "MERGED", "headRefOid": CHILD}
    argv, kw = calls[0]
    assert isinstance(argv, list) and argv[:3] == ["gh", "pr", "view"]
    assert URL in argv and "--json" in argv and "state,headRefOid" in argv
    assert kw.get("shell") is not True


def test_default_pr_state_nonzero_rc_is_none():
    runner = lambda argv, **kw: Proc(1, "", "boom")  # noqa: E731
    assert fe.default_pr_state_fn(URL, runner=runner) is None


def test_default_comment_runs_gh_and_succeeds(capsys):
    calls = []

    def runner(argv, **kw):
        calls.append((argv, kw))
        return Proc(0, "", "")

    assert fe.default_comment_fn(URL, "note body", runner=runner) is True
    argv, kw = calls[0]
    assert isinstance(argv, list) and argv[:3] == ["gh", "pr", "comment"]
    assert URL in argv and "--body" in argv and "note body" in argv
    assert kw.get("shell") is not True


def test_default_comment_nonzero_rc_prints_and_returns_false(capsys):
    runner = lambda argv, **kw: Proc(1, "", "permission denied")  # noqa: E731
    assert fe.default_comment_fn(URL, "note body", runner=runner) is False
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(lines) == 1


def test_default_comment_gh_missing_fail_open(capsys):
    def no_gh(argv, **kw):
        raise FileNotFoundError(2, "No such file or directory", "gh")
    assert fe.default_comment_fn(URL, "note body", runner=no_gh) is False
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(lines) == 1


LABEL_ADD = ["gh", "api", "--method", "POST", "repos/x/y/issues/7/labels", "--input", "-"]


def test_default_label_posts_rest_never_gh_pr_edit(capsys):
    calls = []

    def runner(argv, **kw):
        calls.append((argv, kw))
        return Proc(0, "", "")

    assert fe.default_label_fn(URL, "tp:needs-human-attention", runner=runner) is True
    assert len(calls) == 1
    argv, kw = calls[0]
    assert argv == LABEL_ADD and "edit" not in argv  # gh pr edit dies on classic Projects
    assert json.loads(kw["input"]) == {"labels": ["tp:needs-human-attention"]}
    assert kw.get("shell") is not True


def test_default_label_creates_a_missing_label_and_retries_once(capsys):
    calls, replies = [], [Proc(1, "", "HTTP 422: Label does not exist"), Proc(0), Proc(0)]

    def runner(argv, **kw):
        calls.append(argv)
        return replies[len(calls) - 1]

    assert fe.default_label_fn(URL, "tp:needs-human-attention", runner=runner) is True
    assert calls == [LABEL_ADD,
                     ["gh", "label", "create", "tp:needs-human-attention", "--repo", "x/y"],
                     LABEL_ADD]


def test_default_label_nonzero_rc_prints_and_returns_false(capsys):
    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        return Proc(3, "", "permission denied")

    assert fe.default_label_fn(URL, "tp:needs-human-attention", runner=runner) is False
    assert calls == [LABEL_ADD]  # not a missing-label signal: no create, no retry
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(lines) == 1


def test_default_label_create_failure_is_one_line_and_false(capsys):
    runner = lambda argv, **kw: Proc(1, "", "label not found")  # noqa: E731
    assert fe.default_label_fn(URL, "tp:needs-human-attention", runner=runner) is False
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(lines) == 1 and "label create" in lines[0]


def test_default_label_non_pr_target_fails_open_without_gh(capsys):
    def runner(argv, **kw):
        raise AssertionError("gh must not run for a non-PR target")

    assert fe.default_label_fn("my-slug", "tp:needs-human-attention", runner=runner) is False
    assert len([l for l in capsys.readouterr().out.splitlines() if l]) == 1


def test_default_is_ancestor_true_and_false():
    assert fe.default_is_ancestor_fn(HEAD, CHILD, runner=lambda a, **k: Proc(0)) is True
    assert fe.default_is_ancestor_fn(HEAD, UNRELATED, runner=lambda a, **k: Proc(1)) is False


def test_default_is_ancestor_git_error_raises():
    import pytest
    with pytest.raises(RuntimeError):
        fe.default_is_ancestor_fn(HEAD, CHILD, runner=lambda a, **k: Proc(128, "", "bad sha"))
