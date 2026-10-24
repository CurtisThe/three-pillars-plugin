"""test_changed_tests_runs_skips.py — an all-skipped changed test file is ``unverified``, not ``fail``.

design: opt-in-skip-unverified

Oracle: ``example``. Each case builds a real tmp git repo and calls `changed_tests_runs.record`
over it with the real pytest runner. A file whose tests all skip (an opt-in tier gated on an unset
env var) neither stops the loop nor fails the record: the verdict is ``unverified`` naming the file,
and `fragility_predicate` then applies ``fragility.strict`` unchanged. A real failure still wins,
and so does a timeout.
"""
from __future__ import annotations

import changed_tests_runs as ctr
import fragility_predicate
from test_changed_tests_runs import OK_TEST, RED_TEST, commit, make_repo

SKIP_TEST = "import pytest\n\n\ndef test_live():\n    pytest.skip('opt-in: STAGE unset')\n"
MIXED_TEST = ("import pytest\n\n\ndef test_ok():\n    assert True\n\n\n"
              "def test_live():\n    pytest.skip('opt-in')\n")
BROKEN_TEST = "import module_that_does_not_exist\n\n\ndef test_x():\n    pass\n"
NEEDS_SDK_TEST = ("import pytest\n\nsdk = pytest.importorskip('tp_missing_sdk_xyz')\n\n\n"
                  "def test_x():\n    assert sdk\n")
NO_TESTS = "VALUE = 1\n"
FN_NEEDS_SDK_TEST = ("import pytest\n\n\ndef test_x():\n"
                     "    pytest.importorskip('tp_missing_sdk_xyz')\n")
WARN_THEN_OPT_IN = ("import warnings, pytest\n"
                    "warnings.warn(\"could not import 'fastjson', falling back to json\")\n\n\n"
                    "def test_live():\n    pytest.skip('opt-in: STAGE unset')\n")
PHRASE_IN_REASON = ("import pytest\n\n\ndef test_live():\n"
                    "    pytest.skip(\"opt-in: could not import 'creds' from STAGE env\")\n")


def record(tmp_path, files):
    repo, base = make_repo(tmp_path)
    head = commit(repo, files)
    return repo, base, head, ctr.record(repo, base, head)


def test_all_skipped_file_is_unverified_naming_it(tmp_path):
    _repo, _base, _head, out = record(tmp_path, {"test_live.py": SKIP_TEST})
    assert out["verdict"] == "unverified"
    assert out["reason"] == "skipped (opt-in?): test_live.py"


def test_predicate_passes_with_note_when_strict_off_and_fails_when_on(tmp_path):
    repo, base, head, _out = record(tmp_path, {"test_live.py": SKIP_TEST})
    status, detail = fragility_predicate._runs_check(ctr.read, repo, base, head, strict=False)
    assert status == "pass" and "test_live.py" in detail
    status, detail = fragility_predicate._runs_check(ctr.read, repo, base, head, strict=True)
    assert status == "fail" and "test_live.py" in detail


def test_skipped_then_failing_file_fails_naming_the_failure(tmp_path):
    _repo, _base, _head, out = record(
        tmp_path, {"test_a_skip.py": SKIP_TEST, "test_b_red.py": RED_TEST})
    assert out["verdict"] == "fail" and "test_b_red.py" in out["reason"]


def test_failing_then_skipped_file_fails_naming_the_failure(tmp_path):
    _repo, _base, _head, out = record(
        tmp_path, {"test_a_red.py": RED_TEST, "test_b_skip.py": SKIP_TEST})
    assert out["verdict"] == "fail" and "test_a_red.py" in out["reason"]


def test_skipped_file_plus_passing_file_is_unverified_not_pass(tmp_path):
    _repo, _base, _head, out = record(
        tmp_path, {"test_ok.py": OK_TEST, "test_live.py": SKIP_TEST})
    assert out["verdict"] == "unverified"
    assert out["reason"] == "skipped (opt-in?): test_live.py"


def test_collection_error_is_still_a_failure(tmp_path):
    _repo, _base, _head, out = record(tmp_path, {"test_broken.py": BROKEN_TEST})
    assert out["verdict"] == "fail" and "test_broken.py" in out["reason"]


def test_file_with_passing_and_skipped_nodes_still_passes(tmp_path):
    _repo, _base, _head, out = record(tmp_path, {"test_mixed.py": MIXED_TEST})
    assert out["verdict"] == "pass"


def test_a_timed_out_all_skipped_run_is_still_a_failure(tmp_path, monkeypatch):
    """design.md: timeouts stay ``fail``. pytest writes its report at session end, so a run that
    skips every test and then hangs at exit is killed with an all-skipped report on disk. The
    real run writes that report; only the timeout signal (``rc`` None) is simulated."""
    real = ctr.task_scope.run_capture

    def killed_at_timeout(*args, **kwargs):
        _rc, tail, _timed_out = real(*args, **kwargs)
        return None, tail, True

    monkeypatch.setattr(ctr.task_scope, "run_capture", killed_at_timeout)
    _repo, _base, _head, out = record(tmp_path, {"test_live.py": SKIP_TEST})
    assert (out["verdict"], out["runs"]) == ("fail", ["fail"])
    assert "test_live.py" in out["reason"]


def test_importorskip_of_a_missing_dependency_is_a_failure_not_an_opt_in_skip(tmp_path):
    """A skip because a module cannot be imported says nothing about an opt-in tier: the file
    never ran for an environment reason, so it stays `fail` naming the module."""
    _repo, _base, _head, out = record(tmp_path, {"test_sdk.py": NEEDS_SDK_TEST})
    assert out["verdict"] == "fail"
    assert "test_sdk.py" in out["reason"] and "tp_missing_sdk_xyz" in out["reason"]


def test_importorskip_inside_a_test_is_a_failure_naming_the_module(tmp_path):
    """The reason of a skip raised while running a test sits in the junit ``message``."""
    _repo, _base, _head, out = record(tmp_path, {"test_sdk.py": FN_NEEDS_SDK_TEST})
    assert out["verdict"] == "fail"
    assert "test_sdk.py" in out["reason"] and "tp_missing_sdk_xyz" in out["reason"]


def test_a_warning_naming_an_import_does_not_turn_an_opt_in_skip_into_a_failure(tmp_path):
    """PR #337 r3: the missing-dependency reason is read from the report, never from the
    output tail, so a warning in the warnings summary is not a skip reason."""
    _repo, _base, _head, out = record(tmp_path, {"test_live.py": WARN_THEN_OPT_IN})
    assert out["verdict"] == "unverified"
    assert out["reason"] == "skipped (opt-in?): test_live.py"


def test_a_user_reason_quoting_the_phrase_stays_an_opt_in_skip(tmp_path):
    """Only pytest's own reason, at the start of the message, names a missing dependency."""
    _repo, _base, _head, out = record(tmp_path, {"test_live.py": PHRASE_IN_REASON})
    assert out["verdict"] == "unverified"
    assert out["reason"] == "skipped (opt-in?): test_live.py"


def test_a_run_with_a_skipped_file_does_not_read_pass(tmp_path):
    _repo, _base, _head, out = record(tmp_path, {"test_ok.py": OK_TEST, "test_live.py": SKIP_TEST})
    assert out["runs"] == ["unverified"] * ctr.RUNS


def test_a_file_that_collects_no_tests_is_still_a_failure(tmp_path):
    """Only `unverified`/`skipped` is an opt-in skip: `file-no-tests` keeps its verdict."""
    _repo, _base, _head, out = record(tmp_path, {"test_empty.py": NO_TESTS})
    assert out["verdict"] == "fail" and "test_empty.py" in out["reason"]
