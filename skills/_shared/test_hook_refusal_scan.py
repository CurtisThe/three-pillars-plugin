"""Tests for hook_refusal_scan.refused_commit — the watchdog's fast catch of a refused commit.

design: red-commit-hook-refusal 1.5. Records are hand-built in the shape `attempt_scan._tool_calls`
reads: `assistant` records carrying `tool_use` blocks, `user` records carrying `tool_result` blocks
with `is_error`.
"""
import hook_refusal_scan as hrs

HOOK_TAIL = ("pre-commit failed\n"
             "FAILED skills/_shared/test_foo.py::test_a - AssertionError\n"
             "1 failed in 0.42s")


def rec_tool_use(call_id, command, name="Bash"):
    return {"type": "assistant",
            "message": {"id": "m1", "content": [
                {"type": "tool_use", "id": call_id, "name": name, "input": {"command": command}}]}}


def rec_result(call_id, text, is_error=True):
    return {"type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": text,
                 "is_error": is_error}]}}


def transcript(command, text, is_error=True, call_id="t1"):
    return [rec_tool_use(call_id, command), rec_result(call_id, text, is_error)]


RED = 'git commit -m "Red: red-commit-hook-refusal 1.5 — find a refused commit in a transcript"'


def test_red_commit_refused_by_test_hook_returns_tail():
    tail = hrs.refused_commit(transcript(RED, HOOK_TAIL))
    assert tail is not None
    assert "FAILED skills/_shared/test_foo.py::test_a" in tail


def test_successful_commit_returns_none():
    assert hrs.refused_commit(transcript(RED, "[tp/x abc1234] Red: x", is_error=False)) is None


def test_git_own_failures_return_none():
    for text in ("nothing to commit, working tree clean",
                 "no changes added to commit",
                 "Author identity unknown\n\n*** Please tell me who you are.",
                 "fatal: not the branch you think",
                 "Unable to create '.git/index.lock': File exists"):
        assert hrs.refused_commit(transcript(RED, text)) is None, text


def test_fixable_hook_tail_returns_none():
    # file-size-guard is a class the ladder can fix in-attempt, so it is not a fast catch
    tail = "file-size-guard: skills/_shared/foo.py is 520 lines\n" + HOOK_TAIL
    assert hrs.refused_commit(transcript(RED, tail)) is None


def test_non_commit_bash_error_returns_none():
    assert hrs.refused_commit(transcript("pytest -q skills/_shared/test_foo.py", HOOK_TAIL)) is None


def test_implement_commit_refusal_returns_none():
    impl = 'git commit -m "Implement: red-commit-hook-refusal 1.5 — find a refused commit"'
    assert hrs.refused_commit(transcript(impl, HOOK_TAIL)) is None


def test_red_refusal_with_no_failing_test_path_returns_none():
    assert hrs.refused_commit(transcript(RED, "ruff: src/a.py:3:1: E501 line too long")) is None


def test_red_refusal_after_an_earlier_successful_commit_returns_none():
    records = [rec_tool_use("t1", 'git commit -m "Red: design 1.1 — first"'),
               rec_result("t1", "[tp/x 1111111] Red: design 1.1 — first", False),
               rec_tool_use("t2", RED),
               rec_result("t2", HOOK_TAIL, True)]
    assert hrs.refused_commit(records) is None


def test_red_refusal_followed_by_a_successful_commit_returns_none():
    # the worker contract is "fix the cause, retry the commit once", so a refusal that a
    # later commit call succeeds is a recovered attempt, not a fast catch
    records = [rec_tool_use("t1", RED),
               rec_result("t1", HOOK_TAIL, True),
               rec_tool_use("t2", 'git commit -m "Red: red-commit-hook-refusal 1.5 — retry"'),
               rec_result("t2", "[tp/x 2222222] Red: red-commit-hook-refusal 1.5 — retry", False)]
    assert hrs.refused_commit(records) is None


def test_tail_is_sanitized_and_capped():
    noisy = 'pre-commit: "$HOME/x" `y` ' + "z" * 400 + "\n" + HOOK_TAIL
    tail = hrs.refused_commit(transcript(RED, noisy))
    assert tail is not None
    for ch in ('"', "`", "$", "\\"):
        assert ch not in tail, ch
    assert len(tail) <= 300
    assert "\n" not in tail


def test_dry_run_returns_none():
    assert hrs.refused_commit(transcript("git commit --dry-run -m \"Red: x\"", HOOK_TAIL)) is None


def test_call_without_result_returns_none():
    assert hrs.refused_commit([rec_tool_use("t1", RED)]) is None


def test_malformed_records_return_none_without_raising():
    for bad in (None, [], [None], [{"type": "assistant"}],
                [{"type": "assistant", "message": {"content": "not a list"}}],
                [{"type": "user", "message": {"content": [None]}}]):
        assert hrs.refused_commit(bad) is None, bad


def test_first_qualifying_call_wins():
    records = [rec_tool_use("t1", RED),
               rec_result("t1", "FAILED skills/_shared/test_a.py::test_one - boom", True),
               rec_tool_use("t2", RED),
               rec_result("t2", "FAILED skills/_shared/test_b.py::test_two - boom", True)]
    tail = hrs.refused_commit(records)
    assert "test_a.py" in tail and "test_b.py" not in tail


def test_result_content_as_text_blocks():
    records = [rec_tool_use("t1", RED),
               {"type": "user", "message": {"content": [
                   {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                    "content": [{"type": "text", "text": "FAILED skills/_shared/test_a.py::t"}]}]}}]
    assert "test_a.py" in hrs.refused_commit(records)
