"""test_explain_rulings.py — the rulings ledgers, id continuity and the late fold.

Covers explainer-agent plan Task 8.5 (detailed-design §Interfaces, the explain_rulings
bullet; Test Strategy §Deliver / rulings / state):
  - before archival (`tp-designs/<slug>/` exists) `append_ruling` returns `r<n>`, appends a
    row that stores its `id` to `<design dir>/rulings.ndjson` and a Decision Entry to
    `decisions.md`, and makes no commit;
  - after archival (only `completed-tp-designs/<slug>/` exists) it writes only the out-of-tree
    `<state>/<slug>/rulings-late.ndjson`, so `git status --porcelain` stays empty;
  - ids continue across both ledgers: two archived rows make the first late ruling `r3`;
  - `fold_late` moves the late rows (ids kept) into the archived `rulings.ndjson` and their
    entries into the archived `decisions.md`, empties the late ledger, never commits, and the
    next ruling is `r<n+1>`.

Every test builds a tmp git repo under `tmp_path`, so nothing touches the real repo or its
`.git/three-pillars/explainer/`. Assertions read parsed ledger rows and git state, never
pinned markup (skills/_shared/test-fragility.md).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_envelope  # noqa: E402
import explain_rulings  # noqa: E402
import explain_state  # noqa: E402

SLUG = "demo"
_REAL_RUN = subprocess.run
DOCS = Path("three-pillars-docs")


def _git_raw(cwd, *args) -> str:
    """The stdout of git, untouched (porcelain lines start with a space when unstaged)."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    out = _REAL_RUN(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                    cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return out.stdout


def _git(cwd, *args) -> str:
    return _git_raw(cwd, *args).strip()


def _changed_paths(repo: Path) -> list:
    """The paths `git status --porcelain` lists, sorted; each line is `XY <path>`."""
    return sorted(line[3:] for line in _git_raw(repo, "status", "--porcelain").splitlines())


def _ruling_env(n: int) -> dict:
    """An auto-ruling envelope (no id yet) whose summary names `n`."""
    sections = [{"id": sid, "title": f"Title {sid}",
                 "items": [{"text": f"Ruling {n} {sid} item.", "refs": ["diffstat"]}]}
                for sid in explain_envelope.REQUIRED_SECTIONS["auto-ruling"]]
    env = {"schema": explain_envelope.SCHEMA, "kind": "auto-ruling",
           "ste_summary": {"text": f"Fable chose option {n}.", "refs": ["subject:question"]},
           "sections": sections, "diagram_specs": [],
           "confidence_note": {"text": "The evidence is the diff.", "refs": ["diffstat"]}}
    assert explain_envelope.validate_envelope(env, "auto-ruling") == []
    return env


def _row(n: int) -> dict:
    return {"id": f"r{n}", **_ruling_env(n)}


def _write_ledger(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _rows(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _entry_ids(decisions: Path) -> list:
    """The ruling ids of the Decision Entry headings in a decisions.md."""
    text = decisions.read_text(encoding="utf-8") if decisions.exists() else ""
    return re.findall(r"^### \[explainer\] Ruling (\S+?):", text, re.MULTILINE)


def _snapshot(repo: Path) -> dict:
    return {str(p.relative_to(repo)): p.read_bytes()
            for p in sorted(repo.rglob("*")) if p.is_file() and ".git" not in p.parts}


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    return root


def _commit_all(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")


@pytest.fixture
def live(repo) -> Path:
    """A repo with a live design dir `tp-designs/demo/`; returns the design dir."""
    d = repo / DOCS / "tp-designs" / SLUG
    d.mkdir(parents=True)
    (d / "design.md").write_text("# demo\n", encoding="utf-8")
    _commit_all(repo)
    return d


@pytest.fixture
def archived(repo) -> Path:
    """A repo whose design is archived with two ledger rows and a decisions.md."""
    d = repo / DOCS / "completed-tp-designs" / SLUG
    d.mkdir(parents=True)
    (d / "design.md").write_text("# demo\n", encoding="utf-8")
    _write_ledger(d / "rulings.ndjson", [_row(1), _row(2)])
    (d / "decisions.md").write_text("# Decisions log — schema v1\n", encoding="utf-8")
    _commit_all(repo)
    return d


def _late(repo: Path) -> Path:
    return explain_state.state_root(repo) / SLUG / "rulings-late.ndjson"


# ------------------------------------------------------------ before archival

def test_the_first_live_ruling_is_r1_and_lands_in_the_design_ledger(live, repo):
    rid = explain_rulings.append_ruling(repo, SLUG, _ruling_env(1))
    assert rid == "r1"
    rows = _rows(live / "rulings.ndjson")
    assert [r["id"] for r in rows] == ["r1"]
    assert rows[0]["kind"] == "auto-ruling"
    assert rows[0]["ste_summary"] == _ruling_env(1)["ste_summary"]
    assert _entry_ids(live / "decisions.md") == ["r1"]
    assert not _late(repo).exists()


def test_a_live_ruling_makes_no_commit_and_stages_nothing(live, repo, monkeypatch):
    seen: list = []

    def spy(argv, *a, **kw):
        seen.append(list(argv))
        return _REAL_RUN(argv, *a, **kw)

    head = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(subprocess, "run", spy)
    explain_rulings.append_ruling(repo, SLUG, _ruling_env(1))
    monkeypatch.undo()
    verbs = {a[1] for a in seen if a and a[0] == "git" and len(a) > 1}
    assert not verbs & {"commit", "add", "push", "stash", "reset"}
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "diff", "--cached", "--name-only") == ""
    # The caller's next commit stages the two files, so they show as untracked here.
    changed = _git(repo, "status", "--porcelain", "-uall")
    assert "rulings.ndjson" in changed and "decisions.md" in changed


def test_live_rulings_count_up_and_each_row_stores_its_id(live, repo):
    ids = [explain_rulings.append_ruling(repo, SLUG, _ruling_env(n)) for n in (1, 2, 3)]
    assert ids == ["r1", "r2", "r3"]
    assert [r["id"] for r in _rows(live / "rulings.ndjson")] == ids
    assert _entry_ids(live / "decisions.md") == ids


def test_a_live_ruling_appends_to_an_existing_decisions_log(live, repo):
    (live / "decisions.md").write_text("# Decisions log — schema v1\n\n### [tp-plan] earlier\n"
                                       "**Decided**: x\n", encoding="utf-8")
    explain_rulings.append_ruling(repo, SLUG, _ruling_env(1))
    text = (live / "decisions.md").read_text(encoding="utf-8")
    assert text.startswith("# Decisions log — schema v1\n")
    assert "### [tp-plan] earlier" in text
    assert _entry_ids(live / "decisions.md") == ["r1"]


def test_an_existing_ledger_without_a_final_newline_still_parses_after_an_append(live, repo):
    (live / "rulings.ndjson").write_text(json.dumps(_row(1)), encoding="utf-8")
    assert explain_rulings.append_ruling(repo, SLUG, _ruling_env(2)) == "r2"
    assert [r["id"] for r in _rows(live / "rulings.ndjson")] == ["r1", "r2"]


def test_the_env_given_is_not_changed_and_its_id_is_assigned_by_the_ledger(live, repo):
    env = _ruling_env(1)
    env["id"] = "r99"  # a caller-supplied id never wins over the ledger's
    before = json.loads(json.dumps(env))
    assert explain_rulings.append_ruling(repo, SLUG, env) == "r1"
    assert env == before
    assert _rows(live / "rulings.ndjson")[0]["id"] == "r1"


# ------------------------------------------------------------- after archival

def test_after_archival_the_next_ruling_is_r3_and_only_the_late_ledger_changes(archived, repo):
    before = _snapshot(repo)
    rid = explain_rulings.append_ruling(repo, SLUG, _ruling_env(3))
    assert rid == "r3"
    assert [r["id"] for r in _rows(_late(repo))] == ["r3"]
    assert _snapshot(repo) == before  # the working tree did not change at all
    assert _git(repo, "status", "--porcelain", "-uall") == ""


def test_late_ids_keep_counting_across_both_ledgers(archived, repo):
    ids = [explain_rulings.append_ruling(repo, SLUG, _ruling_env(n)) for n in (3, 4, 5)]
    assert ids == ["r3", "r4", "r5"]
    assert [r["id"] for r in _rows(_late(repo))] == ids
    assert _git(repo, "status", "--porcelain", "-uall") == ""


def test_a_late_row_keeps_what_the_fold_needs_to_log_it(archived, repo):
    explain_rulings.append_ruling(repo, SLUG, _ruling_env(3))
    row = _rows(_late(repo))[0]
    assert row["kind"] == "auto-ruling" and row["ste_summary"]["text"] == "Fable chose option 3."


def test_a_live_dir_counts_the_late_rows_too(live, repo):
    (live / "rulings.ndjson").write_text(json.dumps(_row(1)) + "\n", encoding="utf-8")
    _write_ledger(_late(repo), [_row(2)])
    assert explain_rulings.append_ruling(repo, SLUG, _ruling_env(3)) == "r3"
    assert [r["id"] for r in _rows(live / "rulings.ndjson")] == ["r1", "r3"]
    assert [r["id"] for r in _rows(_late(repo))] == ["r2"]


def test_with_no_design_dir_a_ruling_goes_to_the_late_ledger(repo):
    assert explain_rulings.append_ruling(repo, SLUG, _ruling_env(1)) == "r1"
    assert [r["id"] for r in _rows(_late(repo))] == ["r1"]
    assert not (repo / DOCS).exists()


def test_an_id_is_never_reused_when_the_ledger_has_a_gap(live, repo):
    (live / "rulings.ndjson").write_text(
        json.dumps(_row(1)) + "\n" + json.dumps(_row(5)) + "\n", encoding="utf-8")
    rid = explain_rulings.append_ruling(repo, SLUG, _ruling_env(6))
    assert int(rid[1:]) > 5


@pytest.mark.parametrize("slug", ["../x", "a/b", "..", ""])
def test_a_slug_that_is_not_one_path_component_is_refused(repo, slug):
    with pytest.raises(ValueError):
        explain_rulings.append_ruling(repo, slug, _ruling_env(1))
    with pytest.raises(ValueError):
        explain_rulings.fold_late(repo, slug)
    assert not (repo / DOCS).exists()


def test_an_env_that_is_not_an_object_is_refused(live, repo):
    with pytest.raises(ValueError):
        explain_rulings.append_ruling(repo, SLUG, "not an envelope")
    assert not (live / "rulings.ndjson").exists()


# ------------------------------------------------------------------ fold_late

def _late_rulings(repo: Path, count: int = 2) -> list:
    return [explain_rulings.append_ruling(repo, SLUG, _ruling_env(n)) for n in range(3, 3 + count)]


def test_fold_late_moves_the_late_rows_into_the_archived_ledger_with_ids_kept(archived, repo):
    _late_rulings(repo)
    moved = explain_rulings.fold_late(repo, SLUG)
    assert moved == 2
    rows = _rows(archived / "rulings.ndjson")
    assert [r["id"] for r in rows] == ["r1", "r2", "r3", "r4"]
    assert rows[2] == {"id": "r3", **_ruling_env(3)}
    assert _rows(_late(repo)) == []


def test_fold_late_moves_the_entries_into_the_archived_decisions_log(archived, repo):
    _late_rulings(repo)
    explain_rulings.fold_late(repo, SLUG)
    assert _entry_ids(archived / "decisions.md") == ["r3", "r4"]
    assert (archived / "decisions.md").read_text(encoding="utf-8").startswith(
        "# Decisions log — schema v1\n")


def test_the_next_ruling_after_a_fold_is_r_n_plus_1(archived, repo):
    _late_rulings(repo)
    explain_rulings.fold_late(repo, SLUG)
    assert explain_rulings.append_ruling(repo, SLUG, _ruling_env(5)) == "r5"
    assert [r["id"] for r in _rows(_late(repo))] == ["r5"]
    assert [r["id"] for r in _rows(archived / "rulings.ndjson")] == ["r1", "r2", "r3", "r4"]


def test_fold_late_never_commits_and_leaves_only_the_archived_files_changed(archived, repo,
                                                                            monkeypatch):
    _late_rulings(repo)
    head = _git(repo, "rev-parse", "HEAD")
    seen: list = []

    def spy(argv, *a, **kw):
        seen.append(list(argv))
        return _REAL_RUN(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    explain_rulings.fold_late(repo, SLUG)
    monkeypatch.undo()
    verbs = {a[1] for a in seen if a and a[0] == "git" and len(a) > 1}
    assert not verbs & {"commit", "add", "push", "stash", "reset"}
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "diff", "--cached", "--name-only") == ""
    assert _changed_paths(repo) == sorted([f"{DOCS}/completed-tp-designs/{SLUG}/decisions.md",
                                           f"{DOCS}/completed-tp-designs/{SLUG}/rulings.ndjson"])


def test_fold_late_on_an_empty_late_ledger_changes_nothing(archived, repo):
    before = _snapshot(repo)
    assert explain_rulings.fold_late(repo, SLUG) == 0
    assert _snapshot(repo) == before
    assert _git(repo, "status", "--porcelain", "-uall") == ""


def test_folding_twice_does_not_duplicate_rows_or_entries(archived, repo):
    _late_rulings(repo)
    explain_rulings.fold_late(repo, SLUG)
    assert explain_rulings.fold_late(repo, SLUG) == 0
    assert [r["id"] for r in _rows(archived / "rulings.ndjson")] == ["r1", "r2", "r3", "r4"]
    assert _entry_ids(archived / "decisions.md") == ["r3", "r4"]


def test_a_fold_that_was_cut_short_does_not_duplicate_a_row_already_folded(archived, repo):
    _late_rulings(repo)
    with (archived / "rulings.ndjson").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "r3", **_ruling_env(3)}) + "\n")  # copied, late not emptied
    explain_rulings.fold_late(repo, SLUG)
    assert [r["id"] for r in _rows(archived / "rulings.ndjson")] == ["r1", "r2", "r3", "r4"]
    assert _entry_ids(archived / "decisions.md") == ["r3", "r4"]
    assert _rows(_late(repo)) == []


def test_fold_late_with_no_archived_dir_keeps_the_late_rows(repo):
    explain_rulings.append_ruling(repo, SLUG, _ruling_env(1))
    assert explain_rulings.fold_late(repo, SLUG) == 0
    assert [r["id"] for r in _rows(_late(repo))] == ["r1"]


def test_fold_late_with_a_live_dir_folds_into_the_live_ledger(live, repo):
    _write_ledger(_late(repo), [_row(1)])
    assert explain_rulings.fold_late(repo, SLUG) == 1
    assert [r["id"] for r in _rows(live / "rulings.ndjson")] == ["r1"]
    assert _entry_ids(live / "decisions.md") == ["r1"]
    assert _rows(_late(repo)) == []
