#!/usr/bin/env python3
"""forge_gitea.py — the Gitea backend: token discovery and REST /api/v1.

design: forge-interface (Task 1.3)

Token precedence is `GITEA_TOKEN` > the `tea` login whose url matches the
instance's **web_base by hostname and port** (the live instance is
`https://truenas.home.arpa:30008`, so a login on `:3000` is not it) > none. The
tea config is read by a narrow stdlib line parser — no PyYAML — and a missing or
unparsable file is *no logins*, never an exception, because `read_tea_logins()`
is `forge.resolve`'s `tea_logins` seam default. Every op is a plain `/api/v1`
REST call with `Authorization: token …` over **system-CA TLS**
(`CERT_REQUIRED`, never `-k` / `sslVerify false`), so no `tea` binary is needed.
A 401/403 degrades with `setup_line()` naming both ways to supply a token, and
its response body is never read — it can echo the token, and the token appears
in no result field. An empty response body (Gitea answers a label DELETE with
`204 No Content`) is success with an empty payload, never a parse failure.
Seams: `token` and `urlopen`. Stdlib only.
"""
from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen as _stdlib_urlopen

from forge import ForgeInfo, Result

TOKEN_ENV = "GITEA_TOKEN"
DEFAULT_TEA_CONFIG = Path.home() / ".config" / "tea" / "config.yml"
REQUEST_TIMEOUT = 10


def setup_line(web_base: str) -> str:
    """The one line every missing / rejected-token degrade carries (Task 1.4 too)."""
    return (f"Gitea token needed: export {TOKEN_ENV}=… or "
            f"tea login add --url {web_base}")


# --- token discovery ---------------------------------------------------------

def _clean(value: str) -> str:
    """A YAML scalar as tea writes it: bare, with optional matching quotes."""
    value = (value or "").strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_logins(text: str) -> list:
    """The `logins:` entries of a tea `config.yml`, as dicts.

    Deliberately narrow (no YAML library): a column-0 `logins:` opens the list,
    any other column-0 key closes it, `- ` opens an entry (tea writes its list
    items flush left), `key: value` fills it. A line that is not that shape
    raises `ValueError`, so a config this parser cannot read yields **no**
    logins rather than a partial guess.
    """
    logins: list = []
    entry = None
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not raw[0].isspace() and not (inside and line.startswith("-")):
            inside = (line == "logins:")  # column 0: a top-level key, or the list
            entry = None
            continue
        if not inside:
            continue
        if line.startswith("-"):
            entry = {}
            logins.append(entry)
            line = line[1:].strip()
            if not line:
                continue
        elif entry is None:
            raise ValueError(f"unparsable tea config line: {raw!r}")
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            raise ValueError(f"unparsable tea config line: {raw!r}")
        entry[key.strip()] = _clean(value)
    return logins


def read_tea_logins(path=None) -> list:
    """The `logins:` entries of a tea config. Missing / unparsable -> `[]`."""
    cfg = Path(path) if path is not None else DEFAULT_TEA_CONFIG
    try:
        text = Path(cfg).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    try:
        return _parse_logins(text)
    except ValueError:
        return []


def _hostport(url: str) -> tuple:
    """`(hostname, port)` an instance url addresses — the token match key.

    A url with a port this parser cannot read addresses nothing, so it matches
    nothing rather than raising out of token discovery.
    """
    try:
        parsed = urlparse((url or "").strip())
        return ((parsed.hostname or "").lower(), parsed.port)
    except ValueError:
        return ("", None)


def token_for(web_base: str, *, env=None, tea_config_path=None):
    """The token for `web_base`: env > a matching tea login > None."""
    environ = os.environ if env is None else env
    token = (environ.get(TOKEN_ENV) or "").strip()
    if token:
        return token
    wanted = _hostport(web_base)
    if not wanted[0]:
        return None
    for login in read_tea_logins(tea_config_path):
        if _hostport(login.get("url", "")) == wanted:
            return (login.get("token") or "").strip() or None
    return None


# --- REST /api/v1 ------------------------------------------------------------

def _path_of(url: str) -> str:
    return urlparse(url).path


def _origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _request(method: str, url: str, token, body, open_):
    """`(payload, None)` when Gitea answered, `(None, Result)` when it did not.

    One request shape for all six ops: `Authorization: token …`, JSON in and out,
    `timeout=10`, and a system-CA context. An empty body is a success with no
    payload (`204 No Content` on a label DELETE). On 401/403 the body is not read
    at all — it can carry the token — and the degrade is the setup line.
    """
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, data=data, method=method, headers={
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with open_(request, timeout=REQUEST_TIMEOUT,
                   context=ssl.create_default_context()) as resp:
            raw = resp.read()
    except HTTPError as exc:
        if exc.code in (401, 403):
            return None, Result.degraded(setup_line(_origin_of(url)))
        return None, Result.degraded(
            f"Gitea {method} {_path_of(url)} failed (HTTP {exc.code})")
    except (URLError, OSError):
        return None, Result.degraded(
            f"could not reach Gitea at {urlparse(url).hostname}")
    if not raw or not raw.strip():
        return {}, None
    try:
        return json.loads(raw.decode("utf-8")), None
    except (ValueError, UnicodeDecodeError):
        return None, Result.degraded(
            f"could not parse Gitea response for {_path_of(url)}")


def _api(info: ForgeInfo, path: str) -> str:
    return f"{info.api_base}/{path}"


def _repo_api(info: ForgeInfo, suffix: str) -> str:
    return _api(info, f"repos/{info.owner}/{info.repo}/{suffix}")


def _state(payload: dict) -> str:
    """Gitea's `state` + `merged` -> the one state vocabulary forge callers see."""
    if payload.get("merged"):
        return "MERGED"
    return "OPEN" if payload.get("state") == "open" else "CLOSED"


def pr_create(info: ForgeInfo, *, base: str, head: str, title: str, body: str,
              reviewers=None, token, urlopen=None) -> Result:
    """POST `pulls` -> `{url, number}`. Reviewers are a visible no-op on Gitea."""
    payload, bad = _request("POST", _repo_api(info, "pulls"), token, {
        "base": base, "head": head, "title": title, "body": body,
    }, urlopen or _stdlib_urlopen)
    if bad is not None:
        return bad
    return Result.ok({"url": payload.get("html_url"), "number": payload.get("number")},
                     "reviewers not requested on Gitea" if reviewers else "")


def pr_read(info: ForgeInfo, number, *, token, urlopen=None) -> Result:
    """GET `pulls/<n>` -> `{number, head, head_sha, state, url}` with a normalised state.

    `head` is the branch name (`head.ref`); `head_sha` is the head commit (`head.sha`).
    """
    payload, bad = _request("GET", _repo_api(info, f"pulls/{number}"), token, None,
                            urlopen or _stdlib_urlopen)
    if bad is not None:
        return bad
    return Result.ok({
        "number": payload.get("number"),
        "head": (payload.get("head") or {}).get("ref"),
        "head_sha": (payload.get("head") or {}).get("sha"),
        "state": _state(payload),
        "url": payload.get("html_url"),
    })


def comment_post(info: ForgeInfo, number, body: str, *, token,
                 urlopen=None) -> Result:
    """POST `issues/<n>/comments` -> `{id, url}`."""
    payload, bad = _request("POST", _repo_api(info, f"issues/{number}/comments"),
                            token, {"body": body}, urlopen or _stdlib_urlopen)
    if bad is not None:
        return bad
    return Result.ok({"id": payload.get("id"), "url": payload.get("html_url")})


def comment_list(info: ForgeInfo, number, *, token, urlopen=None) -> Result:
    """GET `issues/<n>/comments` -> `{"comments": [{id, body}]}`."""
    payload, bad = _request("GET", _repo_api(info, f"issues/{number}/comments"),
                            token, None, urlopen or _stdlib_urlopen)
    if bad is not None:
        return bad
    if not isinstance(payload, list):
        return Result.degraded(
            f"unexpected Gitea response for issues/{number}/comments")
    return Result.ok({"comments": [
        {"id": item.get("id"), "body": item.get("body")}
        for item in payload if isinstance(item, dict) and item.get("id") is not None]})


def comment_edit(info: ForgeInfo, comment_id, body: str, *, token,
                 urlopen=None) -> Result:
    """PATCH `issues/comments/<id>`."""
    _, bad = _request("PATCH", _repo_api(info, f"issues/comments/{comment_id}"),
                      token, {"body": body}, urlopen or _stdlib_urlopen)
    return bad if bad is not None else Result.ok({})


def _label_id(info: ForgeInfo, name: str, token, open_):
    """`(id, None)` for an existing label, `(None, Result)` naming a missing one.

    One GET only: Gitea has no label-by-name endpoint, and a second request
    after it said the label is not there would be a wasted round trip.
    """
    payload, bad = _request("GET", _repo_api(info, "labels"), token, None, open_)
    if bad is not None:
        return None, bad
    items = payload if isinstance(payload, list) else []
    for item in items:
        if isinstance(item, dict) and item.get("name") == name:
            return item.get("id"), None
    return None, Result.degraded(
        f'label "{name}" does not exist in {info.owner}/{info.repo} — '
        "create it on the Gitea instance first")


def label_add(info: ForgeInfo, number, name: str, *, token, urlopen=None) -> Result:
    """Resolve `name` to its id, then POST `issues/<n>/labels {"labels": [id]}`."""
    open_ = urlopen or _stdlib_urlopen
    label, bad = _label_id(info, name, token, open_)
    if bad is not None:
        return bad
    _, bad = _request("POST", _repo_api(info, f"issues/{number}/labels"), token,
                      {"labels": [label]}, open_)
    return bad if bad is not None else Result.ok({})


def label_remove(info: ForgeInfo, number, name: str, *, token,
                 urlopen=None) -> Result:
    """Resolve `name`, then DELETE `issues/<n>/labels/<id>` (Gitea answers 204)."""
    open_ = urlopen or _stdlib_urlopen
    label, bad = _label_id(info, name, token, open_)
    if bad is not None:
        return bad
    _, bad = _request("DELETE", _repo_api(info, f"issues/{number}/labels/{label}"),
                      token, None, open_)
    return bad if bad is not None else Result.ok({})
