"""test_explain_rulings_sync.py — the late ledger as evidence, and `sync_rulings`.

Covers explainer-agent plan Task 8.5 (detailed-design §Interfaces, the explain_rulings
bullet: "`explain_sources` reads both ledgers for `ruling:<id>` refs, so a refresh cites
late rulings too. `sync_rulings(root, slug, pr)` merges both ledgers in id order, rebuilds the
one rulings comment and calls `post_or_edit(…, kind="rulings")`; with no rows it does
nothing"):
  - `explain_sources.ruling_items` offers `ruling:r3` from `<state>/<slug>/rulings-late.ndjson`
    next to the design ledger's `ruling:r1` and `ruling:r2`;
  - `sync_rulings` merges both ledgers in id order (numeric, so `r10` follows `r2`), builds
    the body with the design slug in its marker, and calls `post_or_edit` once with
    `kind="rulings"` and the caller's `context`;
  - with no rows anywhere it makes no forge call and stores nothing;
  - a second sync edits the comment the first one posted, and one that finds the old comment
    only by its marker (no stored id, an old `head`) edits that one and posts no duplicate;
  - a forge degrade is returned, printed as one `explainer:` line and logged in the kind's
    delivery entry.

Every test builds a tmp git repo under `tmp_path` and passes a fake forge module, so nothing
touches the network or the real repo's `.git/three-pillars/explainer/`. Assertions read the
parsed marker, ledger rows and the fake forge's recorded calls, never pinned markup
(skills/_shared/test-fragility.md).
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

import explain_deliver  # noqa: E402
import explain_envelope  # noqa: E402
import explain_rulings  # noqa: E402
import explain_sources  # noqa: E402
import explain_state  # noqa: E402
import explainer_marker  # noqa: E402
from forge import Result  # noqa: E402

SLUG = "demo"
PR = 7
_REAL_RUN = subprocess.run
DOCS = Path("three-pillars-docs")
HOOK_ID_RE = re.compile(r"Your call on ruling (\S+?):")


def _git(cwd, *args) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    out = _REAL_RUN(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                    cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _row(n) -> dict:
    """Ledger row r<n>: an auto-ruling envelope that stores its id."""
    sections = [{"id": sid, "title": f"Title {sid}",
                 "items": [{"text": f"Ruling {n} {sid} item.", "refs": ["diffstat"]}]}
                for sid in explain_envelope.REQUIRED_SECTIONS["auto-ruling"]]
    env = {"schema": explain_envelope.SCHEMA, "kind": "auto-ruling",
           "ste_summary": {"text": f"Fable chose option {n}.", "refs": ["subject:question"]},
           "sections": sections, "diagram_specs": [],
           "confidence_note": {"text": "The evidence is the diff.", "refs": ["diffstat"]}}
    assert explain_envelope.validate_envelope(env, "auto-ruling") == []
    return {"id": f"r{n}", **env}


def _write_ledger(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    return root


def _design(repo: Path, tree="completed-tp-designs") -> Path:
    d = repo / DOCS / tree / SLUG
    d.mkdir(parents=True)
    (d / "design.md").write_text("# demo\n", encoding="utf-8")
    return d


def _late(repo: Path) -> Path:
    return explain_state.state_root(repo) / SLUG / "rulings-late.ndjson"


class FakeForge:
    """A forge module stand-in: records every call, serves a mutable comment list."""

    def __init__(self, comments=None, *, fail=()):
        self.comments = [dict(c) for c in (comments or [])]
        self.fail = set(fail)
        self.calls: list = []
        self._next_id = 100

    def _calls(self, op):
        return [c for c in self.calls if c[0] == op]

    def comment_list(self, repo, number, **_kw):
        self.calls.append(("list", str(repo), number))
        if "list" in self.fail:
            return Result.degraded("list refused")
        return Result.ok({"comments": [dict(c) for c in self.comments]})

    def comment_edit(self, repo, comment_id, body, **_kw):
        self.calls.append(("edit", str(repo), comment_id, body))
        if "edit" in self.fail:
            return Result.degraded("edit refused")
        for c in self.comments:
            if str(c["id"]) == str(comment_id):
                c["body"] = body
        return Result.ok({})

    def comment_post(self, repo, number, body, **_kw):
        self.calls.append(("post", str(repo), number, body))
        if "post" in self.fail:
            return Result.degraded("post refused")
        self._next_id += 1
        self.comments.append({"id": self._next_id, "body": body})
        return Result.ok({"id": self._next_id, "url": f"https://example.invalid/{self._next_id}"})


def _entry(repo) -> dict:
    return explain_state.delivery(repo, SLUG, "rulings")


def _hook_ids(body: str) -> list:
    return HOOK_ID_RE.findall(body)


# --------------------------------------------------- explain_sources.ruling_items

def test_ruling_items_offers_the_late_ruling_after_the_archived_ones(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1), _row(2)])
    _write_ledger(_late(repo), [_row(3)])
    items = explain_sources.ruling_items(repo, SLUG)
    assert [i["ref"] for i in items] == ["ruling:r1", "ruling:r2", "ruling:r3"]
    assert json.loads(items[2]["text"])["id"] == "r3"


def test_ruling_items_reads_the_late_ledger_with_no_design_dir(repo):
    _write_ledger(_late(repo), [_row(1)])
    assert [i["ref"] for i in explain_sources.ruling_items(repo, SLUG)] == ["ruling:r1"]


def test_ruling_items_lists_an_id_once_when_both_ledgers_hold_it(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1), _row(2)])
    _write_ledger(_late(repo), [_row(2), _row(3)])
    assert [i["ref"] for i in explain_sources.ruling_items(repo, SLUG)] == [
        "ruling:r1", "ruling:r2", "ruling:r3"]


def test_ruling_items_skips_a_malformed_late_row_and_never_raises(repo):
    _design(repo)
    late = _late(repo)
    late.parent.mkdir(parents=True, exist_ok=True)
    late.write_text("not json\n" + json.dumps(_row(3)) + "\n[1, 2]\n", encoding="utf-8")
    assert [i["ref"] for i in explain_sources.ruling_items(repo, SLUG)] == ["ruling:r3"]


def test_ruling_items_outside_a_git_repo_still_reads_the_design_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    d = tmp_path / DOCS / "tp-designs" / SLUG
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    assert [i["ref"] for i in explain_sources.ruling_items(tmp_path, SLUG)] == ["ruling:r1"]


@pytest.mark.parametrize("slug", ["../x", "a/b", "..", ""])
def test_ruling_items_with_a_bad_slug_gives_nothing(repo, slug):
    assert explain_sources.ruling_items(repo, slug) == []


# ------------------------------------------------------------------ sync_rulings

def test_sync_merges_both_ledgers_in_id_order_and_posts_once(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(2), _row(10)])
    _write_ledger(_late(repo), [_row(1), _row(3)])
    fake = FakeForge()
    result = explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    assert result.status == "ok"
    assert [c[0] for c in fake.calls] == ["list", "post"]
    body = fake._calls("post")[0][3]
    assert _hook_ids(body) == ["r1", "r2", "r3", "r10"]


def test_sync_calls_post_or_edit_once_for_the_rulings_kind_with_the_context(repo, monkeypatch):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1), _row(2)])
    seen: list = []

    def spy(root, slug, pr, body, *, kind, context, **kw):
        seen.append({"root": root, "slug": slug, "pr": pr, "body": body, "kind": kind,
                     "context": context, "kw": kw})
        return Result.ok({"id": 1})

    monkeypatch.setattr(explain_deliver, "post_or_edit", spy)
    explain_rulings.sync_rulings(repo, SLUG, PR, context="autonomous", forge_mod="the-forge")
    assert len(seen) == 1
    call = seen[0]
    assert (call["slug"], call["pr"], call["kind"], call["context"]) == (
        SLUG, PR, "rulings", "autonomous")
    assert call["kw"].get("forge_mod") == "the-forge"
    assert _hook_ids(call["body"]) == ["r1", "r2"]


def test_the_context_defaults_to_manual(repo, monkeypatch):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    seen: list = []

    def spy(root, slug, pr, body, *, kind, context, **kw):
        seen.append(context)
        return Result.ok({"id": 1})

    monkeypatch.setattr(explain_deliver, "post_or_edit", spy)
    explain_rulings.sync_rulings(repo, SLUG, PR)
    assert seen == ["manual"]


def test_the_body_marker_names_the_design_slug_and_the_repo_head(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    fake = FakeForge()
    explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    body = fake._calls("post")[0][3]
    parsed = explainer_marker.parse(body)
    assert parsed == {"kind": "rulings", "slug": SLUG, "head": _git(repo, "rev-parse", "HEAD")}


def test_an_explicit_head_goes_in_the_marker(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    fake = FakeForge()
    explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake, head="feedbeef")
    assert explainer_marker.parse(fake._calls("post")[0][3])["head"] == "feedbeef"


def test_a_duplicate_id_across_the_ledgers_shows_once(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1), _row(2)])
    _write_ledger(_late(repo), [_row(2), _row(3)])
    fake = FakeForge()
    explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    assert _hook_ids(fake._calls("post")[0][3]) == ["r1", "r2", "r3"]


def test_sync_reads_a_live_design_ledger_too(repo):
    d = _design(repo, tree="tp-designs")
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    fake = FakeForge()
    explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    assert _hook_ids(fake._calls("post")[0][3]) == ["r1"]


def test_sync_stores_the_comment_id_under_the_rulings_kind_only(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    fake = FakeForge()
    result = explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    assert _entry(repo)["comment_id"] == result.payload["id"]
    assert explain_state.delivery(repo, SLUG, "pr-brief") == {}


# ------------------------------------------------------------------ empty ledger

def test_with_no_ledger_rows_sync_makes_no_forge_call(repo):
    _design(repo)
    fake = FakeForge()
    assert explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake) is None
    assert fake.calls == []
    assert _entry(repo) == {}


def test_with_empty_ledger_files_sync_makes_no_forge_call(repo):
    d = _design(repo)
    (d / "rulings.ndjson").write_text("", encoding="utf-8")
    late = _late(repo)
    late.parent.mkdir(parents=True, exist_ok=True)
    late.write_text("\n", encoding="utf-8")
    fake = FakeForge()
    assert explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake) is None
    assert fake.calls == []


def test_with_no_design_dir_and_no_late_ledger_sync_does_nothing(repo):
    fake = FakeForge()
    assert explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake) is None
    assert fake.calls == []
    assert _entry(repo) == {}


def test_a_late_ledger_emptied_by_a_fold_still_syncs_the_archived_rows(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1), _row(2), _row(3)])
    _write_ledger(_late(repo), [])
    fake = FakeForge()
    explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    assert _hook_ids(fake._calls("post")[0][3]) == ["r1", "r2", "r3"]


# ------------------------------------- the slug in the marker keeps one comment

def test_a_second_sync_edits_the_comment_the_first_one_posted(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    fake = FakeForge()
    first = explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    _write_ledger(_late(repo), [_row(2)])
    explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    assert len(fake._calls("post")) == 1
    assert [c[2] for c in fake._calls("edit")] == [first.payload["id"]]
    assert _hook_ids(fake.comments[0]["body"]) == ["r1", "r2"]


def test_with_no_stored_id_the_marker_finds_the_old_rulings_comment(repo):
    """A sync that lost its stored id edits the old comment found by marker, not a duplicate.

    This fails if sync_rulings leaves the marker's slug at "-": the fallback matches the
    marker's kind AND slug.
    """
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    old = explainer_marker.marker("rulings", SLUG, "old") + "\n\nan earlier rulings comment\n"
    fake = FakeForge(comments=[
        {"id": 31, "body": explainer_marker.marker("rulings", "other", "old") + "\n"},
        {"id": 32, "body": explainer_marker.marker("pr-brief", SLUG, "old") + "\n"},
        {"id": 33, "body": old},
    ])
    assert _entry(repo) == {}
    result = explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    assert result.status == "ok"
    assert fake._calls("post") == []
    assert [c[2] for c in fake._calls("edit")] == [33]
    assert _entry(repo)["comment_id"] == 33
    assert _hook_ids([c for c in fake.comments if c["id"] == 33][0]["body"]) == ["r1"]


def test_a_brief_comment_is_never_taken_for_the_rulings_comment(repo):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    explain_state.delivery(repo, SLUG, "pr-brief", update={"comment_id": 55})
    fake = FakeForge(comments=[
        {"id": 55, "body": explainer_marker.marker("pr-brief", SLUG, "b") + "\n"}])
    explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    assert [c[0] for c in fake.calls] == ["list", "post"]
    assert explain_state.delivery(repo, SLUG, "pr-brief")["comment_id"] == 55
    assert _entry(repo)["comment_id"] != 55


# ------------------------------------------------------------ degrade and no commit

def test_a_forge_degrade_is_returned_and_printed_as_one_line(repo, capsys):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    fake = FakeForge(fail={"post"})
    result = explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=fake)
    assert result.status == "degraded" and result.line == "post refused"
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if ln.startswith("explainer:")]
    assert len(lines) == 1 and "post refused" in lines[0]
    assert "post refused" in _entry(repo)["degraded"][0]
    assert "comment_id" not in _entry(repo)


def test_sync_makes_no_commit_and_changes_no_tracked_file(repo, monkeypatch):
    d = _design(repo)
    _write_ledger(d / "rulings.ndjson", [_row(1)])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    head = _git(repo, "rev-parse", "HEAD")
    seen: list = []

    def spy(argv, *a, **kw):
        seen.append(list(argv))
        return _REAL_RUN(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    explain_rulings.sync_rulings(repo, SLUG, PR, forge_mod=FakeForge())
    monkeypatch.undo()
    verbs = {a[1] for a in seen if a and a[0] == "git" and len(a) > 1}
    assert not verbs & {"commit", "add", "push", "stash", "reset"}
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "status", "--porcelain", "-uall") == ""
