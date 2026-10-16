"""Tests for forge_gitea.py: the six PR ops over Gitea REST /api/v1.

design: forge-interface (Task 1.3). Hermetic: one recording fake `urlopen` that
answers PER ENDPOINT (longest matching path suffix wins) and can inject a real
`HTTPError` / `URLError` by call index; no network, no `tea`, no real token. The
assertions are the shapes a real Gitea 1.22 answers — including `204 No Content`
(empty body) on a label DELETE — and the two invariants that matter on a real
instance: every request carries `Authorization: token …` over system-CA TLS, and
the token string appears in no result field.
Run with: python3 -m pytest skills/_shared/test_forge_gitea.py -q -n0
"""
from __future__ import annotations

import io
import json
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge_gitea  # noqa: E402
from forge import ForgeInfo  # noqa: E402

TOKEN = "t2"
INFO = ForgeInfo("gitea", "gitea.lan", "home", "lab", "https://gitea.lan",
                 "https://gitea.lan/api/v1", "")
LABELS = [{"id": 3, "name": "tp:needs-human-attention"}, {"id": 9, "name": "bug"}]
PR_BODY = {"number": 7, "state": "open", "merged": False,
           "html_url": "https://gitea.lan/home/lab/pulls/7",
           "head": {"ref": "tp/x", "sha": "abc123"}, "base": {"ref": "master"}}


class Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class Api:
    """Fake urlopen: records every request, answers per endpoint.

    `answers` maps a path suffix to a body — a dict/list (JSON-encoded) or raw
    bytes, where `b""` is what Gitea sends for `204 No Content`. The LONGEST
    matching suffix wins, so one fake can serve `/labels` (the list) and
    `/labels/3` (the DELETE) in the same op. `errors` raises the exception stored
    at a 0-based call index, as a real `HTTPError`/`URLError` would. An
    unmatched path is an assertion failure: a wrong URL must not pass silently.
    """

    def __init__(self, answers=None, errors=None) -> None:
        self.answers = dict(answers or {})
        self.errors = dict(errors or {})
        self.calls: list = []
        self.urls: list = []
        self.auth: list = []
        self.contexts: list = []
        self.timeouts: list = []

    def __call__(self, request, timeout=None, context=None):
        path = urlparse(request.full_url).path
        self.calls.append((request.get_method(), path,
                           json.loads(request.data) if request.data else None))
        self.urls.append(request.full_url)
        self.auth.append(request.get_header("Authorization"))
        self.contexts.append(context)
        self.timeouts.append(timeout)
        index = len(self.calls) - 1
        if index in self.errors:
            raise self.errors[index]
        for suffix in sorted(self.answers, key=len, reverse=True):
            if path.endswith(suffix):
                body = self.answers[suffix]
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                return Resp(raw)
        raise AssertionError(f"unexpected request path: {path}")


def http_error(code: int, body: bytes = b"{}") -> HTTPError:
    """A real HTTPError, with the response body as a file object."""
    return HTTPError(f"{INFO.api_base}/x", code, "error", {}, io.BytesIO(body))


# --- pr_create ---------------------------------------------------------------

def test_pr_create_posts_the_gitea_pulls_endpoint():
    api = Api({"/pulls": dict(PR_BODY, html_url="https://gitea.lan/home/lab/pulls/7")})
    res = forge_gitea.pr_create(INFO, base="master", head="tp/x", title="T",
                                body="B", token=TOKEN, urlopen=api)
    assert api.calls == [("POST", "/api/v1/repos/home/lab/pulls",
                          {"base": "master", "head": "tp/x", "title": "T",
                           "body": "B"})]
    assert res.status == "ok"
    assert res.payload == {"url": "https://gitea.lan/home/lab/pulls/7", "number": 7}
    assert res.note == ""


def test_pr_create_with_reviewers_notes_the_no_op():
    api = Api({"/pulls": PR_BODY})
    res = forge_gitea.pr_create(INFO, base="master", head="tp/x", title="T",
                                body="B", reviewers=["human"], token=TOKEN,
                                urlopen=api)
    assert res.status == "ok"
    assert res.note == "reviewers not requested on Gitea"
    assert [call[0] for call in api.calls] == ["POST"]  # no reviewer request


# --- pr_read -----------------------------------------------------------------

def test_pr_read_gets_the_pr_and_normalises_open():
    api = Api({"/pulls/7": PR_BODY})
    res = forge_gitea.pr_read(INFO, 7, token=TOKEN, urlopen=api)
    assert api.calls == [("GET", "/api/v1/repos/home/lab/pulls/7", None)]
    assert res.status == "ok"
    assert res.payload == {"number": 7, "head": "tp/x", "head_sha": "abc123",
                           "state": "OPEN", "url": "https://gitea.lan/home/lab/pulls/7"}


@pytest.mark.parametrize("state,merged,want", [
    ("open", False, "OPEN"),
    ("closed", True, "MERGED"),
    ("closed", False, "CLOSED"),
])
def test_pr_read_normalises_the_state(state, merged, want):
    api = Api({"/pulls/7": dict(PR_BODY, state=state, merged=merged)})
    assert forge_gitea.pr_read(INFO, 7, token=TOKEN, urlopen=api).payload["state"] == want


# --- comment post / edit -----------------------------------------------------

def test_comment_post_returns_id_and_url():
    api = Api({"/comments": {"id": 99,
                             "html_url": "https://gitea.lan/home/lab/issues/7"
                                         "#issuecomment-99"}})
    res = forge_gitea.comment_post(INFO, 7, "a body", token=TOKEN, urlopen=api)
    assert api.calls == [("POST", "/api/v1/repos/home/lab/issues/7/comments",
                          {"body": "a body"})]
    assert res.status == "ok"
    assert res.payload == {"id": 99,
                           "url": "https://gitea.lan/home/lab/issues/7#issuecomment-99"}


def test_comment_edit_patches_the_comment_endpoint():
    api = Api({"/comments/5": {"id": 5}})
    res = forge_gitea.comment_edit(INFO, 5, "new body", token=TOKEN, urlopen=api)
    assert api.calls == [("PATCH", "/api/v1/repos/home/lab/issues/comments/5",
                          {"body": "new body"})]
    assert res.status == "ok"


# --- labels (name -> id, because Gitea has no label-by-name endpoint) --------

def test_label_add_resolves_the_name_then_posts_the_id():
    api = Api({"/labels": LABELS})
    res = forge_gitea.label_add(INFO, 7, "tp:needs-human-attention", token=TOKEN,
                                urlopen=api)
    assert api.calls == [("GET", "/api/v1/repos/home/lab/labels", None),
                         ("POST", "/api/v1/repos/home/lab/issues/7/labels",
                          {"labels": [3]})]
    assert res.status == "ok"


def test_label_add_unknown_name_degrades_with_one_request():
    api = Api({"/labels": LABELS})
    res = forge_gitea.label_add(INFO, 7, "tp:nope", token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    assert "tp:nope" in res.line and "home/lab" in res.line
    assert len(api.calls) == 1  # no second request after the miss
    assert "\n" not in res.line


def test_label_remove_deletes_by_id_and_accepts_204_no_content():
    """The real-usage case: Gitea answers the DELETE with an EMPTY body."""
    api = Api({"/labels": LABELS, "/labels/3": b""})
    res = forge_gitea.label_remove(INFO, 7, "tp:needs-human-attention", token=TOKEN,
                                   urlopen=api)
    assert api.calls == [("GET", "/api/v1/repos/home/lab/labels", None),
                         ("DELETE", "/api/v1/repos/home/lab/issues/7/labels/3", None)]
    assert res.status == "ok"
    assert res.line == ""


def test_label_remove_unknown_name_degrades():
    api = Api({"/labels": LABELS})
    res = forge_gitea.label_remove(INFO, 7, "tp:nope", token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    assert "tp:nope" in res.line and "home/lab" in res.line
    assert [call[0] for call in api.calls] == ["GET"]


@pytest.mark.parametrize("body", [[], {}, {"message": "nope"}])
def test_a_labels_response_that_is_not_a_list_is_a_missing_label_not_a_crash(body):
    api = Api({"/labels": body})
    res = forge_gitea.label_add(INFO, 7, "bug", token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    assert "bug" in res.line


# --- an empty body is success, never a parse failure -------------------------

@pytest.mark.parametrize("body", [b"", b"   ", b"\n"])
def test_whitespace_or_empty_body_parses_as_no_payload(body):
    api = Api({"/comments/5": body})
    res = forge_gitea.comment_edit(INFO, 5, "b", token=TOKEN, urlopen=api)
    assert res.status == "ok" and res.line == ""


# --- errors degrade with one actionable line ---------------------------------

@pytest.mark.parametrize("code", [401, 403])
def test_auth_errors_degrade_with_the_setup_line(code):
    api = Api(errors={0: http_error(code, b'{"message": "token invalid"}')})
    res = forge_gitea.pr_read(INFO, 7, token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    assert "export GITEA_TOKEN=" in res.line
    assert "tea login add --url https://gitea.lan" in res.line


def test_the_401_response_body_is_never_echoed():
    """A real 401 body can name the token; no result field may repeat it."""
    api = Api(errors={0: http_error(401, b'{"message": "token t2 invalid"}')})
    res = forge_gitea.pr_create(INFO, base="master", head="tp/x", title="T",
                                body="B", token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    for field in (res.line, res.note, str(res.payload)):
        assert TOKEN not in field


def test_other_http_errors_name_the_call_and_code():
    api = Api(errors={0: http_error(500, b"")})
    res = forge_gitea.comment_post(INFO, 7, "b", token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    assert "POST" in res.line and "/api/v1/repos/home/lab/issues/7/comments" in res.line
    assert "500" in res.line


def test_unreachable_host_degrades_naming_the_host():
    api = Api(errors={0: URLError("connection refused")})
    res = forge_gitea.pr_read(INFO, 7, token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    assert "gitea.lan" in res.line


def test_os_error_degrades_like_an_unreachable_host():
    api = Api(errors={0: OSError("dns boom")})
    res = forge_gitea.comment_post(INFO, 7, "b", token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    assert "gitea.lan" in res.line


def test_unparsable_non_empty_body_degrades_one_line():
    api = Api({"/pulls/7": b"<html>502 Bad Gateway</html>"})
    res = forge_gitea.pr_read(INFO, 7, token=TOKEN, urlopen=api)
    assert res.status == "degraded"
    assert "could not parse" in res.line
    assert "/api/v1/repos/home/lab/pulls/7" in res.line
    assert "\n" not in res.line


# --- every request: token header + system-CA TLS -----------------------------

def test_every_request_carries_the_token_header_and_system_ca_tls():
    api = Api({"/labels": LABELS, "/labels/9": b"", "/pulls": PR_BODY,
               "/pulls/7": PR_BODY, "/comments": {"id": 1}})
    assert forge_gitea.pr_create(INFO, base="master", head="tp/x", title="T",
                                 body="B", token=TOKEN, urlopen=api).status == "ok"
    assert forge_gitea.pr_read(INFO, 7, token=TOKEN, urlopen=api).status == "ok"
    assert forge_gitea.comment_post(INFO, 7, "b", token=TOKEN, urlopen=api).status == "ok"
    assert forge_gitea.label_remove(INFO, 7, "bug", token=TOKEN, urlopen=api).status == "ok"
    assert len(api.calls) == 5
    assert api.auth == [f"token {TOKEN}"] * 5
    for context in api.contexts:  # verified, never `ssl._create_unverified_context()`
        assert context.verify_mode == ssl.CERT_REQUIRED
    assert api.timeouts == [10] * 5
    assert all(url.startswith("https://gitea.lan/api/v1/") for url in api.urls)


def test_urls_come_from_the_infos_api_base_not_a_hardcoded_host():
    info = ForgeInfo("gitea", "truenas.home.arpa", "scurtis", "Homelab",
                     "https://truenas.home.arpa:30008",
                     "https://truenas.home.arpa:30008/api/v1", "")
    api = Api({"/pulls/7": PR_BODY})
    assert forge_gitea.pr_read(info, 7, token=TOKEN, urlopen=api).status == "ok"
    assert api.urls == ["https://truenas.home.arpa:30008/api/v1/repos/scurtis"
                        "/Homelab/pulls/7"]
