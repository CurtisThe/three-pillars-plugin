"""Tests for failure_class: classes, normalize, fingerprint, target_for."""
import failure_class as fc

ROW = {"files": ["skills/_shared/foo.py"], "test": {"specs": ["skills/_shared/test_foo.py::test_a"]}}


def cls(reason, outcome="FAIL", **kw):
    return fc.classify(outcome, reason, **kw)


def test_runaway_first_and_own_class():
    assert cls("runaway: wall-clock 900s") == "runaway"
    assert cls("runaway: generation client-reset", hook_tail="file-size-guard") == "runaway"


def test_unlisted_file():
    assert cls("unlisted file: other/x.py", row=ROW) == "deterministic:unlisted-file"


def test_size_split_before_unlisted():
    r = cls("unlisted file: skills/_shared/foo_more.py", row=ROW)
    assert r == "deterministic:size-split"


def test_size_split_hook_tail():
    assert cls("", "hook-failed", hook_tail="file-size-guard blocked") == "deterministic:size-split"
    assert cls("", "hook-failed", hook_tail="violates inv #34") == "deterministic:size-split"


def test_out_of_scope_pin():
    tail = "FAILED skills/_shared/test_other.py::test_z - boom"
    assert cls("", "hook-failed", hook_tail=tail, row=ROW) == "deterministic:out-of-scope-pin"
    ok = "FAILED skills/_shared/test_foo.py::test_a - boom"
    assert cls("", "hook-failed", hook_tail=ok, row=ROW) == "quality"


def test_missing_fixture():
    assert cls("x", hook_tail="fixture 'tmp_thing' not found") == "deterministic:missing-fixture"
    tail = "FileNotFoundError: [Errno 2] tests/fixtures/a.json"
    assert cls("x", hook_tail=tail) == "deterministic:missing-fixture"


def test_no_oracle():
    assert cls("no oracle: nothing runnable") == "deterministic:no-oracle"


def test_quality_conduct_failures():
    for reason in ("design-dir touched: a/b.md", "pushed", "2 commits", "edited-after-pass",
                   "regression skills/_shared/test_a.py::test_x", "tests failed"):
        assert cls(reason) == "quality", reason


def test_other_outcomes():
    assert cls("", "env-error") == "env"
    assert cls("", "PASS") == "pass"
    assert cls("", "PASS-unverified") == "pass"
    assert cls("", "unavailable") == "unavailable"


def test_permission_refused_wins_and_targets_sonnet_medium():
    flags = ["permission-refused: Bash(rm -rf build)"]
    assert cls("", flags=flags) == "deterministic:permission-refused"
    # the flag beats a class the evidence would otherwise match (size-split is listed first)
    both = cls("", "hook-failed", hook_tail="file-size-guard blocked",
               flags=["big-turn"] + flags)
    assert both == "deterministic:permission-refused"
    assert fc.target_for("deterministic:permission-refused") == "sonnet-medium"


def test_permission_refused_leaves_other_outcomes_alone():
    assert cls("", "PASS", flags=["permission-refused: WebFetch"]) == "pass"
    assert cls("", "env-error", flags=["permission-refused: WebFetch"]) == "env"
    assert cls("", "unavailable", flags=["permission-refused: WebFetch"]) == "unavailable"
    assert cls("runaway: wall-clock 900s", flags=["permission-refused: WebFetch"]) == "runaway"
    # a flag that is not a refusal changes nothing
    assert cls("tests failed", flags=["big-turn"]) == "quality"
    assert cls("tests failed") == "quality"


def test_bare_file_tool_refusal_is_logged_but_not_the_class():
    # b2-proof: the inner agent's Write/Edit are refused inside a worktree it already holds through
    # Edit(//<wt>/**), and the worker falls back to a heredoc. No rule to add → not the class, so
    # the attempt keeps its same-rung retry and local-xhigh instead of jumping to sonnet-medium.
    for tool in fc.GRANTED_FILE_TOOLS:
        assert cls("tests failed", flags=[f"permission-refused: {tool}"]) == "quality", tool
    assert cls("", "hook-failed", hook_tail="file-size-guard blocked",
               flags=["permission-refused: Write"]) == "deterministic:size-split"
    # any other refused rule beside them still picks the class
    assert cls("tests failed", flags=["permission-refused: Edit", "permission-refused: WebFetch"]) \
        == "deterministic:permission-refused"



def test_bare_file_tool_banner_in_hook_tail_does_not_pick_the_class():
    # PR #266 r1: build_evidence puts the banner line itself in hook_tail on a hook failure; the
    # flag row must not match it through the row scan, or GRANTED_FILE_TOOLS holds only off-hook.
    tail = "permission-refused: Write\npre-commit: framework-check invariant 12 failed"
    for tool in fc.GRANTED_FILE_TOOLS:
        t = tail.replace("Write", tool)
        assert cls("hook failed", "hook-failed", hook_tail=t, row=ROW,
                   flags=[f"permission-refused: {tool}"]) == "quality", tool
    # a refused rule the lists lack still picks the class on the hook path
    assert cls("hook failed", "hook-failed", hook_tail=tail, row=ROW,
               flags=["permission-refused: WebFetch"]) == "deterministic:permission-refused"

def test_normalize_strips_noise():
    tmp = "/" + "tmp" + "/pytest-of-x/attempt-12ab34cd/f"
    n = fc.normalize("2 commits on abcdef1234 in " + tmp)
    assert "abcdef1234" not in n and "pytest-of-x" not in n and "12ab34cd" not in n
    assert fc.normalize("3 commits") == fc.normalize("7 commits")
    assert fc.normalize("regression a::b at deadbeef") == fc.normalize("regression a::b at cafebabe1")


def test_normalize_cuts_runaway():
    assert fc.normalize("runaway: wall-clock 900s at 1.2") == "runaway: wall-clock"
    assert fc.normalize("runaway: generation client-reset mid-response") == "runaway: generation"


def test_fingerprint_stable_across_rungs():
    a = fc.fingerprint("FAIL", "tests failed at abcdef12", ["t::b", "t::a"])
    b = fc.fingerprint("FAIL", "tests failed at 1234567890", ["t::a", "t::b"])
    assert a == b and a.startswith("quality|t::a,t::b|")
    assert a != fc.fingerprint("FAIL", "tests failed at abcdef12", ["t::c"])


def test_fingerprint_runaway_and_regression():
    assert fc.fingerprint("FAIL", "runaway: generation x", []) == "runaway||runaway: generation"
    one = fc.fingerprint("FAIL", "regression n::a", [])
    assert "n::a" in one and one != fc.fingerprint("FAIL", "regression n::b", [])
    assert one.startswith("quality|")


def test_target_for():
    assert fc.target_for("deterministic:size-split") == "opus-medium"
    assert fc.target_for("deterministic:no-oracle") == "opus-medium"
    assert fc.target_for("runaway") is None
    assert fc.target_for("quality") is None
    assert {c["name"] for c in fc.CLASSES} >= {"unlisted-file", "size-split"}
