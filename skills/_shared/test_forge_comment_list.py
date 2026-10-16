"""Tests for `comment_list` on both forges, the dispatcher and the CLI.

design: explainer-agent (Task 8.1). Hermetic: a fake `runner` (GitHub), a fake
`urlopen` (Gitea) and monkeypatched `token_for` / `resolve` / `forge.comment_list`;
no `gh`, no network, no token. The explainer finds its rolling comment by marker
when the stored id is lost, so every forge answers with `{"comments": [{id, body}]}`
(the payload is a dict, like every forge `Result`). Gitea without a token degrades
through `forge_gitea_agit.no_token`, so a missing token is never silent.

The Gitea render pin: the explainer writes only ```mermaid fences and `<details>`
(with its `<summary>`) outside plain markdown. Gitea renders both from 1.17 on, so
`GITEA_RENDER_PIN` names that floor and the body must stay inside it.

Assertions read the argv, the request and the parsed payload, never the helper's
wording (skills/_shared/test-fragility.md).
Run with: python3 -m pytest skills/_shared/test_forge_comment_list.py -q -n0
"""
from __future__ import annotations

import io
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "explainer"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_envelope  # noqa: E402
import explainer_marker  # noqa: E402
import forge  # noqa: E402
import forge_gitea  # noqa: E402
import forge_gitea_agit  # noqa: E402
import forge_github  # noqa: E402
from explain_markdown import render_markdown  # noqa: E402

GITEA_RENDER_PIN = {"min_version": (1, 17), "renders": ("mermaid", "details")}

GITHUB = forge.ForgeInfo("github", "github.com", "o", "r", "https://github.com",
                         "https://api.github.com", "")
GITEA = forge.ForgeInfo("gitea", "gitea.lan", "o", "r", "https://gitea.lan",
                        "https://gitea.lan/api/v1", "")
OTHER = forge.ForgeInfo("other", "git.example.com", "o", "r",
                        "https://git.example.com", "https://git.example.com/api/v1",
                        "unsupported forge: git.example.com")
TOKEN = "t2"

# What each forge sends: more fields than the explainer needs.
RAW = [
    {"id": 11, "body": "first", "html_url": "https://x/11", "user": {"login": "a"}},
    {"id": 12, "body": "<!-- tp-explainer:pr-brief slug=s head=abc -->\nhi",
     "html_url": "https://x/12", "user": {"login": "bot"}},
]
WANT = {"comments": [{"id": 11, "body": "first"},
                     {"id": 12, "body": "<!-- tp-explainer:pr-brief slug=s head=abc "
                                        "-->\nhi"}]}


class Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class Runner:
    """Fake gh runner: records each argv, answers a scripted process."""

    def __init__(self, proc=None, missing=False):
        self.calls: list = []
        self.proc = proc or Proc(stdout=json.dumps(RAW))
        self.missing = missing

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.missing:
            raise FileNotFoundError(2, "No such file or directory: 'gh'")
        return self.proc


class Resp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class Api:
    """Fake Gitea urlopen: one canned body (or one raised error), requests logged."""

    def __init__(self, body=RAW, error=None):
        self.body, self.error = body, error
        self.requests: list = []

    def __call__(self, request, timeout=None, context=None):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        raw = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()
        return Resp(raw)


# --- GitHub ---------------------------------------------------------------------


def test_github_lists_comments_through_gh_api_paginate():
    run = Runner()
    res = forge_github.comment_list(GITHUB, 7, runner=run)
    assert run.calls == [["gh", "api", "--paginate", "repos/o/r/issues/7/comments"]]
    assert res.status == "ok"
    assert res.payload == WANT


def test_github_paginated_pages_are_one_list():
    page1, page2 = json.dumps(RAW[:1]), json.dumps(RAW[1:])
    run = Runner(Proc(stdout=page1 + "\n" + page2))  # pages not merged by gh
    res = forge_github.comment_list(GITHUB, 7, runner=run)
    assert res.payload == WANT


def test_github_no_comments_is_an_empty_list():
    res = forge_github.comment_list(GITHUB, 7, runner=Runner(Proc(stdout="[]")))
    assert res.status == "ok"
    assert res.payload == {"comments": []}


@pytest.mark.parametrize("run", [
    Runner(Proc(returncode=1, stderr="HTTP 404: Not Found\nmore")),
    Runner(missing=True),
    Runner(Proc(stdout="not json")),
    Runner(Proc(stdout='{"message": "oops"}')),
], ids=["nonzero", "no_gh", "bad_json", "not_a_list"])
def test_github_failures_degrade_with_one_line(run):
    res = forge_github.comment_list(GITHUB, 7, runner=run)
    assert res.status == "degraded"
    assert res.line and "\n" not in res.line
    assert res.payload == {}


# --- Gitea ----------------------------------------------------------------------


def test_gitea_lists_comments_with_the_token_header():
    api = Api()
    res = forge_gitea.comment_list(GITEA, 7, token=TOKEN, urlopen=api)
    (req,) = api.requests
    assert req.get_method() == "GET"
    assert urlparse(req.full_url).path == "/api/v1/repos/o/r/issues/7/comments"
    assert req.get_header("Authorization") == f"token {TOKEN}"
    assert res.status == "ok"
    assert res.payload == WANT
    assert TOKEN not in json.dumps(res.payload)


def test_gitea_skips_entries_that_are_not_comments():
    api = Api(RAW + ["junk", None, {"body": "no id"}])
    res = forge_gitea.comment_list(GITEA, 7, token=TOKEN, urlopen=api)
    assert res.payload == WANT


@pytest.mark.parametrize("api", [
    Api(error=HTTPError("u", 500, "err", {}, io.BytesIO(b"{}"))),
    Api(error=HTTPError("u", 401, "err", {}, io.BytesIO(b"{}"))),
    Api(error=URLError("down")),
    Api(body=b"not json"),
    Api(body={"message": "oops"}),
], ids=["http_500", "http_401", "unreachable", "bad_json", "not_a_list"])
def test_gitea_failures_degrade_with_one_line(api):
    res = forge_gitea.comment_list(GITEA, 7, token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    assert res.line and "\n" not in res.line
    assert TOKEN not in res.line


# --- the dispatcher -------------------------------------------------------------


def test_forge_routes_github_through_the_gh_runner(tmp_path):
    run = Runner()
    res = forge.comment_list(tmp_path, 7, info=GITHUB, runner=run)
    assert run.calls == [["gh", "api", "--paginate", "repos/o/r/issues/7/comments"]]
    assert res.payload == WANT


def test_forge_routes_gitea_with_a_token_to_rest(monkeypatch, tmp_path):
    monkeypatch.setattr(forge_gitea, "token_for", lambda web_base, **kw: TOKEN)
    api = Api()
    res = forge.comment_list(tmp_path, 7, info=GITEA, urlopen=api)
    assert [r.get_header("Authorization") for r in api.requests] == [f"token {TOKEN}"]
    assert res.payload == WANT


def test_gitea_without_a_token_degrades_visibly(monkeypatch, tmp_path):
    monkeypatch.setattr(forge_gitea, "token_for", lambda web_base, **kw: None)
    api = Api()
    res = forge.comment_list(tmp_path, 7, info=GITEA, urlopen=api)
    assert api.requests == []
    assert res.status == "degraded"
    # the dispatcher names every op by its CLI verb (`comment-list`)
    assert res == forge_gitea_agit.no_token("comment-list", GITEA)
    assert "tea login add --url https://gitea.lan" in res.line


def test_other_forge_is_unsupported(tmp_path):
    res = forge.comment_list(tmp_path, 7, info=OTHER)
    assert res.status == "degraded"
    assert "unsupported forge" in res.line and OTHER.host in res.line


# --- the CLI --------------------------------------------------------------------


def _cli(monkeypatch, info, result):
    calls: list = []
    monkeypatch.setattr(forge, "resolve", lambda repo, **kw: info)

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(forge, "comment_list", fake)
    return calls


def test_cli_comment_list_prints_one_json_line(monkeypatch, capsys, tmp_path):
    calls = _cli(monkeypatch, GITEA, forge.Result.ok(WANT))
    rc = forge.main(["comment-list", "--number", "7", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.count("\n") == 1 and json.loads(out) == WANT
    (args, kwargs), = calls
    assert args[0] == str(tmp_path) and str(args[1]) == "7"
    assert kwargs["info"] == GITEA


def test_cli_comment_list_degrade_is_exit_4(monkeypatch, capsys, tmp_path):
    _cli(monkeypatch, GITEA, forge.Result.degraded("comment-list: token needed"))
    rc = forge.main(["comment-list", "--number", "7", "--repo", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 4 and captured.out == ""
    assert captured.err.strip() == "comment-list: token needed"


def test_cli_comment_list_needs_a_number(monkeypatch, tmp_path):
    _cli(monkeypatch, GITEA, forge.Result.ok(WANT))
    assert forge.main(["comment-list", "--repo", str(tmp_path)]) == 2


# --- the Gitea render pin -------------------------------------------------------


class _Tags(HTMLParser):
    """Every HTML element name in the body (the marker is a comment, not a tag)."""

    def __init__(self, body: str):
        super().__init__(convert_charrefs=True)
        self.tags: set = set()
        self.feed(body)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)


def _envelope() -> dict:
    sections = []
    for i, sid in enumerate(explain_envelope.REQUIRED_SECTIONS["pr-brief"]):
        item = {"text": f"Item {i} for {sid}.", "refs": ["diffstat"]}
        sections.append({"id": sid, "title": f"Title {i}", "items": [item]})
    return {
        "schema": explain_envelope.SCHEMA,
        "kind": "pr-brief",
        "ste_summary": {"text": "The change adds a brief.", "refs": ["diffstat"]},
        "sections": sections,
        "diagram_specs": [
            {"kind": "flow", "nodes": ["draft", "gate"], "edges": [["draft", "gate"]]},
            {"kind": "sequence", "nodes": ["a", "b"], "messages": [["a", "b", "go"]]},
        ],
        "confidence_note": {"text": "The evidence is the diff.", "refs": ["diffstat"]},
    }


def _fence_languages(body: str) -> list:
    """The info string of every opening code fence, in order."""
    langs, inside = [], False
    for line in body.splitlines():
        fence = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if not fence:
            continue
        if not inside:
            langs.append(fence.group(2).strip())
        inside = not inside
    return langs


def test_gitea_render_pin_covers_what_the_explainer_writes():
    body = render_markdown(_envelope(), head="abc123",
                           marker=explainer_marker.marker("pr-brief", "s", "abc123"))
    langs = _fence_languages(body)
    assert langs, "the fixture must draw at least one diagram"
    assert set(langs) <= set(GITEA_RENDER_PIN["renders"])
    # <summary> is the <details> block's own title line, not a third block kind
    assert _Tags(body).tags <= {"details", "summary"}
    assert "details" in GITEA_RENDER_PIN["renders"]
    assert GITEA_RENDER_PIN["min_version"] >= (1, 17)
