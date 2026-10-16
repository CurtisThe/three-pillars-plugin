"""Tests for review_prep_scaffold notes, scratch wrappers and adoption reader.

design: cheap-tier-review-prep (Task 5.3)

`write_note` records an accepted scaffold only for a real target key, under
`prep/scaffolds/`, and keeps `index.json` one-entry-per-key.
`adopted_reproducers` maps the tail's adopted keys onto `{"kind": "test", ...}`
reproducers, refusing anything stale, foreign, unaccepted or malformed —
one complete refusal line per bad entry.
`scratch`/`discard` delegate to `cheap_fix` under the `review-prep` prefix,
importing it lazily so the tp-pr-iterate side never pulls in `reproduce`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import review_prep_scaffold  # noqa: E402
from review_prep_scaffold import finding_key  # noqa: E402

HEAD = "0" * 40
SCRIPTS_DIR = str(Path(__file__).parent)


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _reply(findings):
    """`build_prompt` reply shape: one `{"findings": [...]}` object in one fence (M27)."""
    return "```json\n" + json.dumps({"findings": findings}) + "\n```\n"


@pytest.fixture()
def setup(tmp_path):
    def build():
        rd = tmp_path / "proof" / "rounds" / "pr1" / "r2"
        log = tmp_path / "proof" / "iterate-log.1.md"
        f = {"file": "src/a.py", "line_range": [3, 5], "summary": "boom",
             "class": "P", "blocking": True}  # a blocking claim, no reproducer
        rp = rd / "angle0" / "reply.md"
        _write(rd, rp.relative_to(rd), _reply([f]))
        manifest = {"pr_url": "https://github.com/o/r/pull/1", "round": 2,
                    "ordinal": "r2", "base": "BASE",
                    "paths": {"proof_root": str(tmp_path / "proof"),
                              "state_path": str(tmp_path / "proof" / "s.json"),
                              "log_path": str(log)},
                    "angles": [{"name": "angle0", "role": "confirmer", "model": "opus",
                               "tier": "claude", "reply_path": str(rp)}]}
        _write(rd, "angles.json", json.dumps(manifest, indent=2) + "\n")
        return rd, log
    return build


def _target_key() -> str:
    return finding_key({"file": "src/a.py", "line_range": [3, 5],
                        "summary": "boom", "class": "P", "blocking": True})


def _picked_finding(rd) -> dict:
    """The merge-normalized finding `write_note` records, by its key."""
    picked = review_prep_scaffold._picked(rd)
    assert len(picked) == 1
    return picked[0]["finding"]


def _scaffolds(rd):
    return Path(rd) / "prep" / "scaffolds"


# -- write_note -------------------------------------------------------------


def test_write_note_creates_note_and_index(setup):
    rd, _log = setup()
    assert not _scaffolds(rd).exists()
    key = _target_key()
    note = review_prep_scaffold.write_note(rd, key,
                                           {"source": "def t():\n    assert 0",
                                            "test_name": "test_t"},
                                           HEAD)
    data = json.loads(note.read_text(encoding="utf-8"))
    assert set(data) == {"key", "head", "accepted", "source", "test_name", "finding"}
    assert data["key"] == key
    assert data["head"] == HEAD
    assert data["accepted"] is True
    assert data["source"] == "def t():\n    assert 0"
    assert data["test_name"] == "test_t"
    assert data["finding"] == _picked_finding(rd)
    assert note.parent == _scaffolds(rd)
    assert note.name == f"{key}.json"

    index = json.loads((_scaffolds(rd) / "index.json").read_text(encoding="utf-8"))
    assert index == [{"key": key, "file": "src/a.py", "summary": "boom",
                      "note": str(note)}]


def test_write_note_same_key_replaces_index_entry(setup):
    rd, _log = setup()
    key = _target_key()
    for source in ("first source", "second source"):
        review_prep_scaffold.write_note(rd, key,
                                        {"source": source, "test_name": "test_t"},
                                        HEAD)
    index = json.loads((_scaffolds(rd) / "index.json").read_text(encoding="utf-8"))
    assert len(index) == 1
    assert index[0] == {"key": key, "file": "src/a.py", "summary": "boom",
                        "note": str(_scaffolds(rd) / f"{key}.json")}
    data = json.loads((_scaffolds(rd) / f"{key}.json").read_text(encoding="utf-8"))
    assert data["source"] == "second source"


def test_write_note_refuses_non_target_and_writes_nothing(setup):
    rd, _log = setup()
    foreign = finding_key({"file": "src/other.py", "line_range": [9, 9],
                           "summary": "not in this round"})
    assert foreign != _target_key()
    with pytest.raises(ValueError):
        review_prep_scaffold.write_note(rd, foreign,
                                        {"source": "x", "test_name": "t"}, HEAD)
    assert not _scaffolds(rd).exists()


def test_write_note_refuses_bad_artifact_or_key(setup):
    rd, _log = setup()
    key = _target_key()
    with pytest.raises(ValueError):
        review_prep_scaffold.write_note(rd, key, {"source": "", "test_name": "t"}, HEAD)
    with pytest.raises(ValueError):
        review_prep_scaffold.write_note(rd, key,
                                        {"source": "x", "test_name": None}, HEAD)
    with pytest.raises(ValueError):
        review_prep_scaffold.write_note(rd, key, "not a dict", HEAD)
    with pytest.raises(ValueError):
        review_prep_scaffold.write_note(rd, "nothex",
                                        {"source": "x", "test_name": "t"}, HEAD)
    assert not _scaffolds(rd).exists()


# -- adopted_reproducers ----------------------------------------------------


def _adopted(rd, entries):
    ap = Path(rd) / "tail" / "adopted.json"
    _write(rd, ap.relative_to(rd), json.dumps(entries) + "\n")
    return ap


def test_adopted_accepts_a_current_accepted_note(setup):
    rd, _log = setup()
    key = _target_key()
    review_prep_scaffold.write_note(rd, key,
                                    {"source": "def ok():\n    assert 1",
                                     "test_name": "test_ok"},
                                    HEAD)
    ap = _adopted(rd, [{"key": key}])
    out, refusals = review_prep_scaffold.adopted_reproducers(rd, ap, HEAD)
    assert out == {key: {"kind": "test", "source": "def ok():\n    assert 1"}}
    assert refusals == []


def test_adopted_refuses_unknown_key(setup):
    rd, _log = setup()
    key = _target_key()
    review_prep_scaffold.write_note(rd, key,
                                    {"source": "s", "test_name": "t"}, HEAD)
    unknown = finding_key({"file": "src/none.py", "line_range": [1, 1],
                           "summary": "no note"})
    ap = _adopted(rd, [{"key": unknown}])
    out, refusals = review_prep_scaffold.adopted_reproducers(rd, ap, HEAD)
    assert out == {}
    assert refusals == [f"scaffold-adopt-refused: {unknown}: unknown key"]


def test_adopted_refuses_stale_head(setup):
    rd, _log = setup()
    key = _target_key()
    review_prep_scaffold.write_note(rd, key,
                                    {"source": "s", "test_name": "t"},
                                    "f" * 40)
    ap = _adopted(rd, [{"key": key}])
    out, refusals = review_prep_scaffold.adopted_reproducers(rd, ap, HEAD)
    assert out == {}
    assert refusals == [f"scaffold-adopt-refused: {key}: stale head"]


def test_adopted_refuses_unaccepted_note(setup):
    rd, _log = setup()
    key = _target_key()
    scaffolds = _scaffolds(rd)
    scaffolds.mkdir(parents=True, exist_ok=True)
    (scaffolds / f"{key}.json").write_text(json.dumps({
        "key": key, "head": HEAD, "accepted": False, "source": "s",
        "test_name": "t", "finding": {}}) + "\n", encoding="utf-8")
    ap = _adopted(rd, [{"key": key}])
    out, refusals = review_prep_scaffold.adopted_reproducers(rd, ap, HEAD)
    assert out == {}
    assert refusals == [f"scaffold-adopt-refused: {key}: not accepted"]


def test_adopted_mixed_and_malformed(setup):
    rd, _log = setup()
    good = _target_key()
    review_prep_scaffold.write_note(rd, good,
                                    {"source": "def g():\n    pass",
                                     "test_name": "test_g"},
                                    HEAD)
    foreign = finding_key({"file": "src/x.py", "line_range": [2, 2],
                           "summary": "foreign"})
    ap = _adopted(rd, [{"key": good}, {"key": foreign}])
    out, refusals = review_prep_scaffold.adopted_reproducers(rd, ap, HEAD)
    assert out == {good: {"kind": "test", "source": "def g():\n    pass"}}
    assert refusals == [f"scaffold-adopt-refused: {foreign}: unknown key"]

    bad = Path(rd) / "tail" / "bad.json"
    _write(rd, bad.relative_to(rd), '{"key": 1}\n')
    out, refusals = review_prep_scaffold.adopted_reproducers(rd, bad, HEAD)
    assert out == {}
    assert refusals == ["scaffold-adopt-refused: *: malformed adopted.json"]

    not_json = Path(rd) / "tail" / "notjson.json"
    _write(rd, not_json.relative_to(rd), "this is not json\n")
    out, refusals = review_prep_scaffold.adopted_reproducers(rd, not_json, HEAD)
    assert out == {}
    assert refusals == ["scaffold-adopt-refused: *: malformed adopted.json"]


# -- scratch / discard ------------------------------------------------------


def test_scratch_and_discard_delegate_to_cheap_fix(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo, ".gitignore", ".claude/worktrees/\n")
    _write(repo, "f.txt", "hello\n")

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, timeout=60)

    git("init", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    git("add", "f.txt")
    git("commit", "-m", "init")
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          check=True, capture_output=True, timeout=60,
                          text=True).stdout.strip()

    p = review_prep_scaffold.scratch(repo, head)
    assert p.name == "r1"
    assert p.parent.name.startswith("review-prep-")
    got = subprocess.run(["git", "-C", str(p), "rev-parse", "HEAD"],
                         check=True, capture_output=True, timeout=60,
                         text=True).stdout.strip()
    assert got == head

    review_prep_scaffold.discard(p)
    assert not p.exists()
    assert not p.parent.exists()


# -- lazy import ------------------------------------------------------------


def test_import_does_not_load_cheap_fix_or_reproduce():
    code = ("import sys; sys.path.insert(0, %r); "
            "import review_prep_scaffold; "
            "print('cheap_fix' in sys.modules, 'reproduce' in sys.modules)") % SCRIPTS_DIR
    out = subprocess.run([sys.executable, "-c", code], check=True,
                         capture_output=True, timeout=120, text=True)
    assert out.stdout.strip() == "False False"
