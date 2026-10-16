"""test_task_verify_lint_step.py — step 7 of ``task_verify.check``: the lint on the task diff.

design: fragile-test-prevention (stages §Part C1, phase 5)

Step 7 runs after the Targets pass: ``fragility_lint.check_diff(adir, base, head="HEAD")``
over the attempt's committed text. A gating hit no waiver silences is FAIL
``fragile: <rule> at <path>:<line>``; a lint that could not judge the diff is logged as
``fragility-lint could-not-evaluate: <why>``, never read as a pass and never a fail by itself.
Oracle: ``example`` — each case is a concrete commit shape built in a real tmp repo
(``attempt_fixture``, M23).
"""
from __future__ import annotations

import hashlib
import shlex
import sys
from pathlib import Path

import task_attempts
import task_verify
import task_verify_lint_step
from attempt_fixture import DD, commit, commit_pair, git, make_seat, task_row

RUNNER = f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider"
TEST = "skills/test_a.py"
COULD_NOT = "fragility-lint could-not-evaluate: "
DIGEST = hashlib.sha256(b"demo\n").hexdigest()  # the seat's README.md
GOLDEN = ("import hashlib\nfrom pathlib import Path\n\n\ndef test_a():\n"
          "    body = (Path(__file__).parents[1] / \"README.md\").read_bytes()\n"
          "    assert hashlib.sha256(body).hexdigest() == \"{digest}\"\n")
CLEAN = "import a\n\n\ndef test_a():\n    assert a.A == 2\n"
DENY = 'A = 2\nDENY = ("x", "y"){tail}\n'
BROKEN = "def (:\n"


def _attempt(tmp_path: Path, red: dict, green: dict, files=("skills/a.py",)):
    """An open attempt holding the red/green pair, and the row that declares the Targets."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    commit_pair(Path(att["attempt_dir"]), red, green)
    return att, task_row(files, f"`{TEST}::test_a`")


def _check(att: dict, row: dict) -> dict:
    return task_verify.check(att, row, RUNNER, rung="local", timeout=120)


def _line(source: str, needle: str) -> int:
    return next(n for n, text in enumerate(source.splitlines(), 1) if needle in text)


def _notes(res: dict) -> list[str]:
    return [line for line in res["logged"] if line.startswith(COULD_NOT)]


def test_a_golden_hash_in_the_red_fails_after_the_targets_pass(tmp_path):
    red = GOLDEN.format(digest=DIGEST)
    att, row = _attempt(tmp_path, {TEST: red}, {"skills/a.py": "A = 2\n"})
    res = _check(att, row)
    assert res["commands"], "the Targets ran before the lint judged the diff"
    assert (res["verdict"], res["reason"]) == (
        "FAIL", f"fragile: golden-hash at {TEST}:{_line(red, 'assert hashlib')}")
    assert task_verify.land(att)["reason"] == "not-passed: FAIL"


def test_a_deny_literal_in_a_production_file_fails_the_same_way(tmp_path):
    green = DENY.format(tail="")
    att, row = _attempt(tmp_path, {TEST: CLEAN}, {"skills/a.py": green})
    res = _check(att, row)
    assert (res["verdict"], res["reason"]) == (
        "FAIL", f"fragile: deny-literal at skills/a.py:{_line(green, 'DENY')}")


def test_a_waived_hit_passes_and_an_empty_waiver_still_fails(tmp_path):
    waived = DENY.format(tail="  # tp-allow-fragile: a closed protocol set")
    att, row = _attempt(tmp_path / "waived", {TEST: CLEAN}, {"skills/a.py": waived})
    res = _check(att, row)
    assert (res["verdict"], _notes(res)) == ("PASS", []), res["reason"]
    empty = DENY.format(tail="  # tp-allow-fragile:")
    att, row = _attempt(tmp_path / "empty", {TEST: CLEAN}, {"skills/a.py": empty})
    res = _check(att, row)
    assert (res["verdict"], res["reason"]) == (
        "FAIL", f"fragile: deny-literal at skills/a.py:{_line(empty, 'DENY')}")


def test_a_clean_pair_passes_with_nothing_logged_by_the_lint(tmp_path):
    att, row = _attempt(tmp_path, {TEST: CLEAN}, {"skills/a.py": "A = 2\n"})
    res = _check(att, row)
    assert (res["verdict"], _notes(res)) == ("PASS", []), res["reason"]
    assert task_verify.land(att)["exit"] == 0


def test_an_unparseable_non_targets_file_is_logged_and_the_verdict_is_the_others(tmp_path):
    att, row = _attempt(tmp_path, {TEST: CLEAN},
                        {"skills/a.py": "A = 2\n", "skills/broken.py": BROKEN},
                        files=("skills/a.py", "skills/broken.py"))
    res = _check(att, row)
    notes = _notes(res)
    assert res["verdict"] == "PASS" and len(notes) == 1, res["reason"]
    assert "skills/broken.py" in notes[0] and notes[0] in res["reason"]


def test_a_gating_hit_still_fails_beside_an_unparseable_file(tmp_path):
    green = {"skills/a.py": DENY.format(tail=""), "skills/broken.py": BROKEN}
    att, row = _attempt(tmp_path, {TEST: CLEAN}, green,
                        files=("skills/a.py", "skills/broken.py"))
    res = _check(att, row)
    assert (res["verdict"], res["reason"]) == (
        "FAIL", f"fragile: deny-literal at skills/a.py:{_line(green['skills/a.py'], 'DENY')}")


def test_a_red_test_is_reported_before_the_lint_runs(tmp_path):
    att, row = _attempt(tmp_path, {TEST: GOLDEN.format(digest="0" * 64)},
                        {"skills/a.py": "A = 2\n"})
    res = _check(att, row)
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test")


def test_run_returns_the_reason_and_logs_what_it_could_not_judge(tmp_path):
    att, _row = _attempt(tmp_path, {TEST: CLEAN}, {"skills/a.py": DENY.format(tail="")})
    adir, base, logged = str(att["attempt_dir"]), str(att["base_sha"]), []
    reason = task_verify_lint_step.run(adir, base, logged)
    assert reason and reason.startswith("fragile: deny-literal at skills/a.py:")
    assert logged == []
    reason = task_verify_lint_step.run(adir, "0" * 40, logged)  # a ref that is not there
    assert reason is None and len(logged) == 1
    assert logged[0].startswith(COULD_NOT), "an unjudged diff is logged, not a pass"


def test_run_lints_the_committed_text_not_the_working_tree(tmp_path):
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    base = str(att["base_sha"])
    commit(adir, {"skills/a.py": "A = 2\n"})
    (adir / "skills" / "a.py").write_text(DENY.format(tail=""), encoding="utf-8")  # dirty
    assert task_verify_lint_step.run(str(adir), base, []) is None
    commit(adir, {"skills/a.py": DENY.format(tail="")})
    (adir / "skills" / "a.py").write_text("A = 2\n", encoding="utf-8")  # dirty, now clean
    assert task_verify_lint_step.run(str(adir), base, []).startswith("fragile: deny-literal")


def test_run_ignores_a_repo_local_git_env_of_the_caller(tmp_path, monkeypatch):
    seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    commit(adir, {"skills/a.py": DENY.format(tail="")})
    monkeypatch.setenv("GIT_DIR", git(seat, "rev-parse", "--absolute-git-dir"))
    monkeypatch.setenv("GIT_WORK_TREE", str(seat))
    reason = task_verify_lint_step.run(str(adir), str(att["base_sha"]), [])
    assert reason and reason.startswith("fragile: deny-literal at skills/a.py:")
