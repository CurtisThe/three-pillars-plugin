"""test_explain_deliver.py — write the brief file and post-or-edit the forge comment.

Covers explainer-agent plan Task 8.3 (detailed-design §Interfaces, the explain_deliver
bullet and `explainer_marker.parse`):
  - `write_brief(root, slug, env, evidence_head=...)` writes `<design dir>/brief.md`
    (marker first, stamped with the briefed head, drafter and check outcome),
    `<state>/<slug>/pr-brief.html` (offline-clean) and `pr-brief.envelope.json`, and never
    commits: no `git commit` / `git add` runs and the repo HEAD and index do not move;
  - `post_or_edit(root, slug, pr, body, *, kind, context, forge_mod)` finds the comment by
    the stored id, then by the stable marker prefix (kind + slug, any head), then posts;
    on success it stores `comment_id` and `posted_head` in that kind's delivery entry only;
  - per-kind guard: a brief post then a rulings post leave two distinct ids, and a later
    brief edit targets the brief id.

Every test builds a tmp git repo under `tmp_path` and passes a fake forge module object, so
nothing touches the network or the real repo's `.git/three-pillars/explainer/`. Assertions
read parsed values (the marker via `explainer_marker.parse`, JSON files, the fake forge's
recorded calls), never pinned markup (skills/_shared/test-fragility.md).
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
import explain_offline  # noqa: E402
import explain_state  # noqa: E402
import explainer_marker  # noqa: E402
from forge import Result  # noqa: E402

HEAD = "abc123"
SLUG = "demo"
_REAL_RUN = subprocess.run


def _git(cwd, *args) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    out = _REAL_RUN(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                    cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    return root


def _env() -> dict:
    sections = [{"id": sid, "title": f"Title {sid}",
                 "items": [{"text": f"Item for {sid}.", "refs": ["diffstat"]}]}
                for sid in explain_envelope.REQUIRED_SECTIONS["pr-brief"]]
    env = {"schema": explain_envelope.SCHEMA, "kind": "pr-brief",
           "ste_summary": {"text": "The change adds a brief.", "refs": ["diffstat"]},
           "sections": sections, "diagram_specs": [],
           "confidence_note": {"text": "The evidence is the diff.", "refs": ["diffstat"]},
           "drafter": "sonnet", "check_outcome": "edited"}
    assert explain_envelope.validate_envelope(env, "pr-brief") == []
    return env


def _body(kind="pr-brief", head=HEAD, slug=SLUG) -> str:
    return explainer_marker.marker(kind, slug, head) + "\n\nBody text.\n"


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


def _deliver(repo, fake, body, *, kind="pr-brief", pr=7):
    return explain_deliver.post_or_edit(repo, SLUG, pr, body, kind=kind,
                                        context="manual", forge_mod=fake)


def _entry(repo, kind="pr-brief") -> dict:
    return explain_state.delivery(repo, SLUG, kind)


# ------------------------------------------------------------------ write_brief

def test_write_brief_stamps_the_markdown_in_the_design_dir(repo):
    path = explain_deliver.write_brief(repo, SLUG, _env(), evidence_head=HEAD)
    expect = repo / "three-pillars-docs" / "tp-designs" / SLUG / "brief.md"
    assert Path(path) == expect
    text = expect.read_text(encoding="utf-8")
    assert explainer_marker.parse(text) == {"kind": "pr-brief", "slug": SLUG, "head": HEAD}
    assert re.search(rf"Briefed head:\s*`?{HEAD}`?", text)
    assert "sonnet" in text and "edited" in text


def test_write_brief_takes_drafter_and_check_outcome_overrides(repo):
    explain_deliver.write_brief(repo, SLUG, _env(), evidence_head=HEAD,
                                drafter="opus", check_outcome="rewritten")
    text = (repo / "three-pillars-docs" / "tp-designs" / SLUG / "brief.md").read_text(encoding="utf-8")
    assert "opus" in text and "rewritten" in text
    assert "sonnet" not in text and "edited" not in text


def test_write_brief_writes_offline_html_and_the_envelope_json(repo):
    env = _env()
    explain_deliver.write_brief(repo, SLUG, env, evidence_head=HEAD)
    out = explain_state.state_root(repo) / SLUG
    page = (out / "pr-brief.html").read_text(encoding="utf-8")
    explain_offline.assert_offline(page)
    assert HEAD in page
    assert json.loads((out / "pr-brief.envelope.json").read_text(encoding="utf-8")) == env
    assert _entry(repo)["html"] == str(out / "pr-brief.html")


def test_write_brief_never_commits(repo, monkeypatch):
    seen: list = []

    def spy(argv, *a, **kw):
        seen.append(list(argv))
        return _REAL_RUN(argv, *a, **kw)

    head_before = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(subprocess, "run", spy)
    explain_deliver.write_brief(repo, SLUG, _env(), evidence_head=HEAD)
    monkeypatch.undo()
    git_verbs = {a[1] for a in seen if a and a[0] == "git" and len(a) > 1}
    assert not git_verbs & {"commit", "add", "push", "stash", "reset"}
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert _git(repo, "diff", "--cached", "--name-only") == ""


@pytest.mark.parametrize("slug", ["../x", "a/b", "..", ""])
def test_write_brief_refuses_a_slug_that_is_not_one_path_component(repo, slug):
    with pytest.raises(ValueError):
        explain_deliver.write_brief(repo, slug, _env(), evidence_head=HEAD)
    assert not (repo / "three-pillars-docs").exists()


# ---------------------------------------------------------------- post_or_edit

def test_a_stored_comment_id_is_edited_not_reposted(repo):
    explain_state.delivery(repo, SLUG, "pr-brief", update={"comment_id": 55})
    fake = FakeForge(comments=[{"id": 55, "body": _body(head="old999")}])
    body = _body(head="new111")
    result = _deliver(repo, fake, body)
    assert result.status == "ok"
    assert fake._calls("edit") == [("edit", str(repo), 55, body)]
    assert fake._calls("post") == [] and fake._calls("list") == []
    assert _entry(repo)["comment_id"] == 55
    assert _entry(repo)["posted_head"] == "new111"


def test_marker_fallback_finds_the_comment_after_a_head_change(repo):
    fake = FakeForge(comments=[
        {"id": 7, "body": _body(head="old999", slug="other")},      # same kind, other slug
        {"id": 8, "body": _body(kind="rulings", head="old999")},    # same slug, other kind
        {"id": 9, "body": _body(head="old999")},                    # the one to edit
        {"id": 10, "body": "an unrelated review comment"},
    ])
    body = _body(head="new111")
    result = _deliver(repo, fake, body)
    assert result.status == "ok"
    assert fake._calls("list") == [("list", str(repo), 7)]
    assert fake._calls("edit") == [("edit", str(repo), 9, body)]
    assert fake._calls("post") == []
    assert [c for c in fake.comments if c["id"] == 9][0]["body"] == body
    assert _entry(repo)["comment_id"] == 9
    assert _entry(repo)["posted_head"] == "new111"


def test_a_new_comment_is_posted_when_nothing_is_stored_or_found(repo):
    fake = FakeForge(comments=[{"id": 3, "body": "an unrelated review comment"}])
    body = _body()
    result = _deliver(repo, fake, body)
    assert result.status == "ok"
    assert fake._calls("post") == [("post", str(repo), 7, body)]
    assert fake._calls("edit") == []
    assert _entry(repo)["comment_id"] == result.payload["id"]
    assert _entry(repo)["posted_head"] == HEAD


def test_a_second_post_edits_the_comment_it_stored(repo):
    fake = FakeForge()
    first = _deliver(repo, fake, _body(head="one"))
    _deliver(repo, fake, _body(head="two"))
    assert len(fake._calls("post")) == 1
    assert [c[2] for c in fake._calls("edit")] == [first.payload["id"]]
    assert _entry(repo)["posted_head"] == "two"


# -------------------------------------------------------- per-kind guard

def test_brief_and_rulings_keep_distinct_comment_ids(repo):
    fake = FakeForge()
    brief = _deliver(repo, fake, _body("pr-brief", "b1"), kind="pr-brief")
    rulings = _deliver(repo, fake, _body("rulings", "r1"), kind="rulings")
    assert brief.payload["id"] != rulings.payload["id"]
    stored = json.loads((explain_state.state_root(repo) / SLUG / "delivery.json")
                        .read_text(encoding="utf-8"))
    assert stored["pr-brief"]["comment_id"] == brief.payload["id"]
    assert stored["rulings"]["comment_id"] == rulings.payload["id"]
    assert len(fake._calls("post")) == 2

    refreshed = _body("pr-brief", "b2")
    _deliver(repo, fake, refreshed, kind="pr-brief")
    assert fake._calls("edit") == [("edit", str(repo), brief.payload["id"], refreshed)]
    assert _entry(repo, "rulings")["comment_id"] == rulings.payload["id"]
    assert _entry(repo, "rulings")["posted_head"] == "r1"


def test_an_unknown_kind_raises_before_any_forge_call(repo):
    fake = FakeForge()
    with pytest.raises(ValueError):
        _deliver(repo, fake, _body(), kind="digest")
    assert fake.calls == []


# ------------------------------------------------------------- forge failures

def test_a_degraded_post_returns_the_result_and_stores_nothing(repo):
    fake = FakeForge(fail={"post"})
    result = _deliver(repo, fake, _body())
    assert result.status == "degraded" and result.line == "post refused"
    assert _entry(repo) == {}


def test_a_degraded_list_returns_it_and_never_posts_a_duplicate(repo):
    fake = FakeForge(fail={"list"})
    result = _deliver(repo, fake, _body())
    assert result.status == "degraded" and result.line == "list refused"
    assert fake._calls("post") == []
    assert _entry(repo) == {}


def test_a_stored_id_that_will_not_edit_falls_back_to_the_marker_then_a_post(repo):
    explain_state.delivery(repo, SLUG, "pr-brief", update={"comment_id": 55})
    fake = FakeForge(comments=[], fail={"edit"})
    result = _deliver(repo, fake, _body())
    assert result.status == "ok"
    assert len(fake._calls("post")) == 1
    assert _entry(repo)["comment_id"] == result.payload["id"]


def test_a_stored_id_that_will_not_edit_with_no_listing_is_reported_not_reposted(repo):
    explain_state.delivery(repo, SLUG, "pr-brief", update={"comment_id": 55})
    fake = FakeForge(fail={"edit", "list"})
    result = _deliver(repo, fake, _body())
    assert result.status == "degraded" and result.line == "edit refused"
    assert fake._calls("post") == []
    assert _entry(repo)["comment_id"] == 55
