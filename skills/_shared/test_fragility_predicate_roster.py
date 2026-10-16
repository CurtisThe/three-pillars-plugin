"""test_fragility_predicate_roster.py — `roster_block` and the gate's `fragility_clear` entry.

design: fragile-test-prevention (detailed-design-stages.md Part C4, the `roster_block`,
`gate_roster` and `changed_tests_runs` writers bullets).

Oracle: ``example``. `roster_block` gives the gate exactly one roster entry named
`fragility_clear`: OMITTED on the `fragility.merge_predicate: false` opt-out, OMITTED on a
hermetic run with no `fragility_fn` seam, otherwise one predicate. The live cases build a real
tmp git repo with a local bare `origin` (so the gate's `git fetch origin <base>` never leaves
the machine) and patch only the PR-state / threads / base-name seams that would call GitHub.
At `/tp-merge` the design worktree may be one unpushed log-flush commit ahead of the PR head:
the lint and the run record still bind the PR head oid, and the items store is read for the
checked-out branch that contains it.
"""
from __future__ import annotations

import os
import shlex
import subprocess

import pytest

import changed_tests_runs
import deterministic_gate as dg
import diff_balloon_guard
import fragility_items
import fragility_predicate
import gate_roster
from deterministic_gate import FailureClass, GateVerdict, PredicateResult

PR_URL = "https://github.com/o/r/pull/1"
BRANCH = "tp/demo"
NAME = "fragility_clear"
QUIET = {"schema_version": 1, "ci": {"expects_github_checks": False},
         "review": {"expects_copilot": False, "require_human_approval": False,
                    "require_review_proof": False}}
GOLDEN = '''\
import hashlib
from pathlib import Path


def test_pin():
    body = Path("hooks/x.sh").read_bytes()
    assert hashlib.sha256(body).hexdigest() == "abc123"
'''


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch):
    """A test run from a git hook inherits GIT_DIR / GIT_INDEX_FILE; drop them all."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)


def _git(root, *args: str) -> str:
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=root,
                          capture_output=True, text=True, check=True, encoding="utf-8")
    return done.stdout.strip()


def _commit(root, files: dict[str, str], message: str = "c") -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    """A repo whose `main` is pushed to a local bare origin; `tp/demo` is checked out."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    root = tmp_path / "work"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "remote", "add", "origin", str(origin))
    _commit(root, {"README.md": "x\n", "pytest.ini": "[pytest]\n"})
    _git(root, "push", "-q", "origin", "main")
    _git(root, "checkout", "-q", "-b", BRANCH)
    return root


def _base(root) -> str:
    return _git(root, "rev-parse", "main")


def _block(config, r, *, live, root=None, head="0" * 40, base=None):
    return fragility_predicate.roster_block(config=config, r=r, running_live=live,
                                            repo_root=root, pr_head=head, base_ref=base)


def _only(entries):
    assert [e.name for e in entries] == [NAME]
    return entries[0]


def _no_subprocess(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("roster_block ran a subprocess")
    monkeypatch.setattr(subprocess, "run", refuse)


# --- activation ----------------------------------------------------------------------------

def test_opt_out_gives_no_predicate_and_an_omitted_entry(monkeypatch):
    _no_subprocess(monkeypatch)
    calls = []
    seam = {"fragility_fn": lambda **k: calls.append(k)}
    for r, live in (({}, True), (seam, False), (seam, True)):
        preds, entries = _block({"fragility": {"merge_predicate": False}}, r, live=live)
        assert preds == []
        entry = _only(entries)
        assert entry.status == "OMITTED"
        assert entry.detail.startswith("skipped (opt-out)")
    assert calls == []


@pytest.mark.parametrize("r", [{}, {"fragility_fn": None}], ids=["absent", "explicit-none"])
def test_hermetic_run_without_the_seam_is_omitted_with_a_hermetic_reason(monkeypatch, r):
    _no_subprocess(monkeypatch)
    preds, entries = _block({}, r, live=False)
    assert preds == []
    entry = _only(entries)
    assert entry.status == "OMITTED"
    assert "hermetic run" in entry.detail


def test_the_seam_gives_one_predicate_bound_to_the_pr_head():
    seen = {}

    def seam(**kwargs):
        seen.update(kwargs)
        return PredicateResult(name=NAME, verdict=GateVerdict.FAIL, detail="stub")

    preds, entries = _block({}, {"fragility_fn": seam}, live=False, root="/r", head="abc",
                            base="origin/main")
    assert [p.name for p in preds] == [NAME]
    assert _only(entries).status == "FAIL"
    assert (seen["repo_root"], seen["head_ref"], seen["base_ref"]) == ("/r", "abc", "origin/main")


def test_the_gate_puts_fragility_clear_right_after_the_proof_predicate(monkeypatch, tmp_path):
    import proof_predicate

    monkeypatch.setattr(proof_predicate, "pred_review_proof_on_head", lambda *a, **k:
                        PredicateResult("review_proof_on_head", GateVerdict.PASS, "stub"))
    seen = {}

    def seam(**kwargs):
        seen.update(kwargs)
        return PredicateResult(name=NAME, verdict=GateVerdict.PASS, detail="stub")

    config = dict(QUIET, review=dict(QUIET["review"], require_review_proof=True))
    predicates, roster = gate_roster.build_predicates_and_roster(
        pr_url=PR_URL, rollup=[], failure_class=FailureClass.INDETERMINATE, threads=[],
        mergeable="MERGEABLE", head_oid="feedface", config=config,
        r={"comments_fn": lambda *_a: [], "fragility_fn": seam,
           "carry_repo_root": str(tmp_path)},
        copilot_runners=None, running_live=False, shared_dir=None)
    names = [e.name for e in roster]
    assert names.index(NAME) == names.index("review_proof_on_head") + 1
    assert [p.name for p in predicates][-2:] == ["review_proof_on_head", NAME]
    assert seen["head_ref"] == "feedface"
    assert str(seen["repo_root"]) == str(tmp_path)


# --- the live path -------------------------------------------------------------------------

@pytest.fixture
def live_gate(monkeypatch):
    """Patch only the GitHub-bound seams; the gate itself runs live (no runners)."""
    head = {}
    monkeypatch.setattr(dg, "_live_pr_state_fn", lambda url: {
        "mergeable": "MERGEABLE", "headRefOid": head["oid"], "statusCheckRollup": []})
    monkeypatch.setattr(dg, "_default_threads_fn", lambda url: [])
    monkeypatch.setattr(gate_roster, "derive_base_ref", lambda url: "main")
    monkeypatch.setattr(diff_balloon_guard, "pred_diff_not_ballooned",
                        lambda **k: PredicateResult("diff_not_ballooned", GateVerdict.PASS, "stub"))

    def run(root, oid):
        head["oid"] = oid
        return dg.evaluate_gate(PR_URL, config=QUIET, repo_root=str(root))
    return run


def _entry(outcome):
    return _only([e for e in outcome.roster if e.name == NAME])


def test_a_fragile_pr_head_makes_the_whole_gate_refuse_naming_fragility_clear(repo, live_gate):
    head = _commit(repo, {"skills/test_pin.py": GOLDEN})
    outcome = live_gate(repo, head)
    assert outcome.verdict == GateVerdict.FAIL
    assert [p.name for p in outcome.blocking] == [NAME]
    assert "golden-hash" in _entry(outcome).detail


def test_the_live_gate_passes_a_clear_head_once_its_run_record_exists(repo, live_gate):
    head = _commit(repo, {"lib.py": "VALUE = 1\n"})
    missing = live_gate(repo, head)
    assert [p.name for p in missing.blocking] == [NAME]
    assert "origin/main" in _entry(missing).detail  # the fetched base, handed through
    assert changed_tests_runs.record(repo, "origin/main", head)["written"] is True
    outcome = live_gate(repo, head)
    assert outcome.verdict == GateVerdict.PASS
    assert _entry(outcome).status == "PASS"


def _live(repo, head, config=None):
    preds, entries = _block(config or {}, {}, live=True, root=repo, head=head, base=_base(repo))
    assert [p.name for p in preds] == [NAME]
    return _only(entries)


def _item():
    return {"id": "abc123def456", "source": "pr-loop", "path": "lib.py", "line": 1,
            "fragility_class": "blocklist", "anchor": "<module>", "summary": "s"}


def test_a_worktree_one_commit_ahead_of_the_pr_head_reads_the_pr_heads_record(repo):
    head = _commit(repo, {"lib.py": "VALUE = 1\n"})
    assert changed_tests_runs.record(repo, _base(repo), head)["written"] is True
    _commit(repo, {"notes.md": "log flush\n"}, "the unpushed log-flush commit")
    assert _live(repo, head).status == "PASS"

    fragility_items.replace_source(repo, BRANCH, "pr-loop", head, [_item()])
    entry = _live(repo, head)
    assert entry.status == "FAIL"
    assert "abc123def456" in entry.detail


def test_the_items_waiver_hint_runs_against_the_items_cli(repo):
    head = _commit(repo, {"lib.py": "VALUE = 1\n"})
    assert changed_tests_runs.record(repo, _base(repo), head)["written"] is True
    fragility_items.replace_source(repo, BRANCH, "pr-loop", head, [_item()])
    detail = _live(repo, head).detail
    hint = detail.split("waive with: ", 1)[1].rsplit(")", 1)[0]
    argv = [{"<id>": "abc123def456", "<you>": "tester", "<why>": "a reviewed exception"}
            .get(arg, arg) for arg in shlex.split(hint)]
    subprocess.run(argv, cwd="/", check=True, capture_output=True, text=True)
    assert _live(repo, head).status == "PASS"


def test_a_head_on_no_local_branch_is_indeterminate_with_a_fetch_hint(repo):
    _git(repo, "checkout", "-q", "--detach")
    head = _commit(repo, {"lib.py": "VALUE = 1\n"})
    entry = _live(repo, head)
    assert entry.status == "INDETERMINATE"
    assert "fetch" in entry.detail
    assert _live(repo, "0" * 40).status == "INDETERMINATE"


def test_the_live_path_is_indeterminate_without_a_root_or_a_base(repo):
    head = _commit(repo, {"lib.py": "VALUE = 1\n"})
    for root, base in ((None, _base(repo)), (repo, None)):
        preds, entries = _block({}, {}, live=True, root=root, head=head, base=base)
        assert [p.verdict for p in preds] == [GateVerdict.INDETERMINATE]
        assert _only(entries).status == "INDETERMINATE"
