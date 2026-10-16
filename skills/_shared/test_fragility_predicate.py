"""test_fragility_predicate.py — the merge-gate `fragility_clear` predicate (Behavior 3).

design: fragile-test-prevention (detailed-design-stages.md Part C4, `fragility_predicate.py`
bullet list; detailed-design.md `pred_fragility_clear`).

Oracle: ``example``. Each case builds a real tmp git repo and lints it with the real
`fragility_lint`; `items_fn` and `runs_fn` are injected stubs (the items store and the run
record are covered by their own modules' tests). The three conditions are evaluated in
order — lint, items, runs — and a FAIL names the failing condition; a lint exit 2 or an
internal error is INDETERMINATE, never a silent PASS.
"""
from __future__ import annotations

import os
import subprocess

import pytest

import changed_tests_runs
from deterministic_gate import GateVerdict
from fragility_predicate import pred_fragility_clear

GOLDEN = '''\
import hashlib
from pathlib import Path


def test_pin():
    body = Path("hooks/x.sh").read_bytes()
    assert hashlib.sha256(body).hexdigest() == "abc123"
'''
CLEAN = "def test_ok():\n    assert 1 + 1 == 2\n"
TEST = "skills/_shared/test_pin.py"
PROD = "skills/_shared/denylist.py"


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch):
    """A test run from a git hook inherits GIT_DIR / GIT_INDEX_FILE; drop them all."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)


def _git(root, *args: str) -> str:
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=root,
                          capture_output=True, text=True, check=True, encoding="utf-8")
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(root, name, text) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


def _commit(root, files: dict[str, str], message: str = "c") -> str:
    for name, text in files.items():
        _write(root, name, text)
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _pass_items(_root, _branch):
    return []


def _pass_runs(_root, _head):
    return {"verdict": "pass", "reason": ""}


@pytest.fixture
def base(repo):
    return _commit(repo, {"README.md": "x\n"})


# --- lint condition ----------------------------------------------------------------------

def test_fails_naming_fragility_clear_and_lists_the_hit_for_a_fragile_addition(repo, base):
    head = _commit(repo, {TEST: GOLDEN})
    result = pred_fragility_clear(repo_root=repo, base_ref=base, head_ref=head, config={},
                                  items_fn=_pass_items, runs_fn=_pass_runs)
    assert result.name == "fragility_clear"
    assert result.verdict == GateVerdict.FAIL
    assert "golden-hash" in result.detail
    assert TEST in result.detail


def test_lists_up_to_5_hits(repo, base):
    src = "\n".join(f'DENY_{i} = {{"a"}}  # HIT' for i in range(6))
    head = _commit(repo, {PROD: src})
    result = pred_fragility_clear(repo_root=repo, base_ref=base, head_ref=head, config={},
                                  items_fn=_pass_items, runs_fn=_pass_runs)
    assert result.verdict == GateVerdict.FAIL
    assert result.detail.count("deny-literal") == 5


def test_passes_when_the_same_code_is_already_on_the_base(repo):
    base_head = _commit(repo, {TEST: GOLDEN})
    head = _commit(repo, {"notes.md": "unrelated\n"})
    result = pred_fragility_clear(repo_root=repo, base_ref=base_head, head_ref=head, config={},
                                  items_fn=_pass_items, runs_fn=_pass_runs)
    assert result.verdict == GateVerdict.PASS


def test_lint_exit_2_is_indeterminate(repo, base):
    head = _commit(repo, {TEST: CLEAN})
    result = pred_fragility_clear(repo_root=repo, base_ref="no-such-ref", head_ref=head,
                                  config={}, items_fn=_pass_items, runs_fn=_pass_runs)
    assert result.verdict == GateVerdict.INDETERMINATE


def test_internal_error_is_indeterminate(repo, base):
    head = _commit(repo, {TEST: CLEAN})

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    result = pred_fragility_clear(repo_root=repo, base_ref=base, head_ref=head, config={},
                                  lint_fn=boom, items_fn=_pass_items, runs_fn=_pass_runs)
    assert result.verdict == GateVerdict.INDETERMINATE


# --- items condition ---------------------------------------------------------------------

def test_fails_listing_the_open_items_id_until_waived(repo, base):
    head = _commit(repo, {TEST: CLEAN})

    def open_items(_root, _branch):
        return [{"id": "abc123def456", "source": "pr-loop", "path": TEST,
                 "fragility_class": "blocklist"}]

    result = pred_fragility_clear(repo_root=repo, base_ref=base, head_ref=head, config={},
                                  items_fn=open_items, runs_fn=_pass_runs)
    assert result.verdict == GateVerdict.FAIL
    assert "abc123def456" in result.detail

    result = pred_fragility_clear(repo_root=repo, base_ref=base, head_ref=head, config={},
                                  items_fn=_pass_items, runs_fn=_pass_runs)
    assert result.verdict == GateVerdict.PASS


# --- runs condition ----------------------------------------------------------------------

def test_runs_passes_on_pass(repo, base):
    head = _commit(repo, {TEST: CLEAN})
    result = pred_fragility_clear(repo_root=repo, base_ref=base, head_ref=head, config={},
                                  items_fn=_pass_items, runs_fn=_pass_runs)
    assert result.verdict == GateVerdict.PASS


def test_runs_fails_on_fail(repo, base):
    head = _commit(repo, {TEST: CLEAN})
    result = pred_fragility_clear(
        repo_root=repo, base_ref=base, head_ref=head, config={}, items_fn=_pass_items,
        runs_fn=lambda _r, _h: {"verdict": "fail", "reason": "boom"})
    assert result.verdict == GateVerdict.FAIL
    assert "boom" in result.detail


def test_runs_fails_on_a_missing_or_stale_record_naming_the_record_command(repo, base):
    head = _commit(repo, {TEST: CLEAN})
    result = pred_fragility_clear(repo_root=repo, base_ref=base, head_ref=head, config={},
                                  items_fn=_pass_items, runs_fn=lambda _r, _h: None)
    assert result.verdict == GateVerdict.FAIL
    assert "changed_tests_runs.py" in result.detail
    assert "record" in result.detail
    assert base in result.detail and head in result.detail


def test_runs_passes_unverified_with_a_note_by_default(repo, base):
    head = _commit(repo, {TEST: CLEAN})
    result = pred_fragility_clear(
        repo_root=repo, base_ref=base, head_ref=head, config={}, items_fn=_pass_items,
        runs_fn=lambda _r, _h: {"verdict": "unverified", "reason": "no pytest"})
    assert result.verdict == GateVerdict.PASS
    assert "unverified" in result.detail


def test_runs_fails_unverified_under_fragility_strict(repo, base):
    head = _commit(repo, {TEST: CLEAN})
    result = pred_fragility_clear(
        repo_root=repo, base_ref=base, head_ref=head, config={"fragility": {"strict": True}},
        items_fn=_pass_items, runs_fn=lambda _r, _h: {"verdict": "unverified", "reason": "no pytest"})
    assert result.verdict == GateVerdict.FAIL


# --- the documented tp-merge order: record, then the gate -------------------------------

def test_light_class_pr_with_no_prior_record_passes_after_record_runs_first(repo, base):
    _write(repo, "pytest.ini", "[pytest]\n")
    _git(repo, "add", "pytest.ini")
    _git(repo, "commit", "-q", "-m", "add pytest config")
    new_base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, {"lib.py": "VALUE = 1\n"})

    assert changed_tests_runs.read(repo, head) is None
    out = changed_tests_runs.record(repo, new_base, head)
    assert out["written"] is True

    result = pred_fragility_clear(repo_root=repo, base_ref=new_base, head_ref=head, config={},
                                  items_fn=_pass_items)
    assert result.verdict == GateVerdict.PASS
