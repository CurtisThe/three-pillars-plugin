"""Tests for forge.py's dispatch layer: one op per kind, no `None`, no raise.

design: forge-interface (Task 1.5). Hermetic: `forge.resolve` is monkeypatched to a
fixed `ForgeInfo`, and the three backends (`forge_github`, `forge_gitea`,
`forge_gitea_agit`) are monkeypatched to recorders returning fixed `Result`s — so no
`git`, no network, no token. The assertions are the contract: kind `other` degrades on
every op naming `unsupported forge`, the host and the resolve `reason` (for an ssh
alias with no web base, that reason carries the `forge.web_base` setup line); gitea
with a token goes to the REST backend, gitea without one to AGit (`pr-create`) or the
setup-line degrade (every other op); github's `pr-create` reaches the PR-author
chokepoint through `forge_github.pr_create` with the gh argv built from the kwargs.
Run with: python3 -m pytest skills/_shared/test_forge_dispatch.py -q -n0
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import automation_identity  # noqa: E402
import forge  # noqa: E402
import forge_gitea  # noqa: E402
import forge_gitea_agit  # noqa: E402
import forge_github  # noqa: E402

GITHUB = forge.ForgeInfo("github", "github.com", "o", "r", "https://github.com",
                         "https://api.github.com", "")
GITEA = forge.ForgeInfo("gitea", "gitea.lan", "o", "r", "https://gitea.lan",
                        "https://gitea.lan/api/v1", "")
GITEA_PORTED = forge.ForgeInfo("gitea", "gitea.lan", "o", "r",
                               "https://gitea.lan:3000",
                               "https://gitea.lan:3000/api/v1", "")
# An ssh-config alias with no derivable web base — the first-run case.
OTHER_ALIAS = forge.ForgeInfo("other", "gitea", "scurtis", "Homelab", "", "",
                              "no web base — " + forge.NO_WEB_BASE_LINE)
# A web base that answered the probe with something that is not Gitea.
OTHER_HOST = forge.ForgeInfo("other", "git.example.com", "o", "r",
                             "https://git.example.com",
                             "https://git.example.com/api/v1",
                             "unsupported forge: git.example.com")

REST_OPS = ["pr_read", "comment_post", "comment_edit", "label_add", "label_remove"]
GH_WRITES = ["comment_post", "comment_edit", "label_add", "label_remove"]

# The positional args after `info` that each REST op forwards to its backend.
FORWARD = {"pr_read": (7,), "comment_post": (7, "body"), "comment_edit": (99, "body"),
           "label_add": (7, "bug"), "label_remove": (7, "bug")}


def _call(op: str, repo, info, **kw):
    """One op, positional args fixed: `7`/`99` are ids, `"body"`/`"bug"` payloads."""
    if op == "pr_create":
        return forge.pr_create(repo, base="main", head="feat", title="T", body="B",
                               info=info, **kw)
    if op == "pr_read":
        return forge.pr_read(repo, 7, info=info, **kw)
    if op == "comment_post":
        return forge.comment_post(repo, 7, "body", info=info, **kw)
    if op == "comment_edit":
        return forge.comment_edit(repo, 99, "body", info=info, **kw)
    if op == "label_add":
        return forge.label_add(repo, 7, "bug", info=info, **kw)
    return forge.label_remove(repo, 7, "bug", info=info, **kw)


def _spy(monkeypatch, module, name: str, result: forge.Result) -> list:
    """Replace `module.name` with a recorder of `(args, kwargs)`; return the log."""
    calls: list = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(module, name, fake)
    return calls


# --- kind `other`: every op degrades, and says why --------------------------------


@pytest.mark.parametrize("op", ["pr_create"] + REST_OPS)
@pytest.mark.parametrize("info", [OTHER_ALIAS, OTHER_HOST], ids=["alias", "host"])
def test_other_degrades_naming_host_and_reason(op, info, tmp_path):
    result = _call(op, tmp_path, info)
    assert isinstance(result, forge.Result)
    assert result.status == "degraded"
    assert "unsupported forge" in result.line
    assert info.host in result.line
    assert info.reason in result.line


def test_other_reason_carries_the_web_base_setup_line(tmp_path):
    result = forge.pr_read(tmp_path, 7, info=OTHER_ALIAS)
    assert "forge.web_base" in result.line
    assert result.line == result.line.strip() and "\n" not in result.line


# --- gitea: token decides REST vs AGit / setup line -------------------------------


@pytest.mark.parametrize("op", REST_OPS)
def test_gitea_with_token_uses_the_rest_backend(op, monkeypatch, tmp_path):
    monkeypatch.setattr(forge_gitea, "token_for", lambda web_base, **kw: "tk")
    calls = _spy(monkeypatch, forge_gitea, op, forge.Result.ok({"op": op}))
    result = _call(op, tmp_path, GITEA)
    assert result.status == "ok"
    assert result.payload == {"op": op}
    args, kwargs = calls[0]
    assert args[0] == GITEA
    assert kwargs["token"] == "tk"


@pytest.mark.parametrize("op", REST_OPS)
def test_gitea_without_token_degrades_with_the_setup_line(op, monkeypatch, tmp_path):
    monkeypatch.setattr(forge_gitea, "token_for", lambda web_base, **kw: None)
    result = _call(op, tmp_path, GITEA)
    assert result.status == "degraded"
    assert op.replace("_", "-") in result.line
    assert "tea login add --url https://gitea.lan" in result.line


def test_gitea_token_is_looked_up_from_the_web_base(monkeypatch, tmp_path):
    seen = {}

    def fake_token(web_base, **kw):
        seen["web_base"] = web_base
        return None

    monkeypatch.setattr(forge_gitea, "token_for", fake_token)
    _call("pr_read", tmp_path, GITEA_PORTED)
    assert seen["web_base"] == "https://gitea.lan:3000"


def test_gitea_without_token_pr_create_pushes_agit(monkeypatch, tmp_path):
    monkeypatch.setattr(forge_gitea, "token_for", lambda web_base, **kw: None)
    calls = _spy(monkeypatch, forge_gitea_agit, "pr_create_agit",
                 forge.Result.ok({"url": "https://gitea.lan/o/r/pulls/3", "number": 3}))
    result = _call("pr_create", tmp_path, GITEA)
    assert result.status == "ok"
    assert result.payload["number"] == 3
    args, kwargs = calls[0]
    assert args[0] == GITEA
    assert (kwargs["base"], kwargs["head"]) == ("main", "feat")
    assert (kwargs["title"], kwargs["body"]) == ("T", "B")
    assert kwargs["repo"] == tmp_path


def test_gitea_with_token_pr_create_uses_the_rest_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(forge_gitea, "token_for", lambda web_base, **kw: "tk")
    calls = _spy(monkeypatch, forge_gitea, "pr_create",
                 forge.Result.ok({"url": "https://gitea.lan/o/r/pulls/4", "number": 4}))
    result = forge.pr_create(tmp_path, base="main", head="feat", title="T", body="B",
                             reviewers="bot", info=GITEA)
    assert result.status == "ok"
    args, kwargs = calls[0]
    assert args[0] == GITEA
    assert kwargs["token"] == "tk"
    assert kwargs["reviewers"] == "bot"


# --- github: the gh backend, and the PR-author chokepoint for create --------------


@pytest.mark.parametrize("op", REST_OPS)
def test_github_uses_the_gh_backend(op, monkeypatch, tmp_path):
    calls = _spy(monkeypatch, forge_github, op, forge.Result.ok({"op": op}))
    result = _call(op, tmp_path, GITHUB)
    assert result.status == "ok"
    args, kwargs = calls[0]
    assert args[0] == GITHUB
    assert args[1:] == FORWARD[op]
    assert "runner" in kwargs
    if op in GH_WRITES:  # only the four writes carry the identity inputs
        assert (kwargs["config"], kwargs["env"]) == ({}, None)
    else:
        assert "config" not in kwargs and "env" not in kwargs


def _repo_naming_the_bot(tmp_path) -> dict:
    cfg = {"github": {"pr_author_account": "CurtisTheBot"}}
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


@pytest.mark.parametrize("op", GH_WRITES)
def test_github_writes_forward_the_repo_config_and_env(op, monkeypatch, tmp_path):
    cfg = _repo_naming_the_bot(tmp_path)
    calls = _spy(monkeypatch, forge_github, op, forge.Result.ok({}))
    assert _call(op, tmp_path, GITHUB, env={"PATH": "/bin"}).status == "ok"
    kwargs = calls[0][1]
    assert kwargs["config"] == cfg and kwargs["env"] == {"PATH": "/bin"}


def test_github_write_config_is_the_strict_load(monkeypatch, tmp_path):
    """An unparseable config is fail-loud on a write (lenient `_read_config` says `{}`)."""
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars" / "config.json").write_text("{nope", encoding="utf-8")
    _spy(monkeypatch, forge_github, "pr_read", forge.Result.ok({}))
    assert forge.pr_read(tmp_path, 7, info=GITHUB).status == "ok"  # a read never loads it
    with pytest.raises(automation_identity.BotAuthUnavailable):
        forge.comment_post(tmp_path, 7, "b", info=GITHUB)


def test_github_comment_post_runs_as_the_configured_bot(monkeypatch, tmp_path):
    _repo_naming_the_bot(tmp_path)
    monkeypatch.setattr(automation_identity, "bot_token", lambda account, runner=None: "tok-bot")
    seen = []

    def rec(argv, env=None):
        seen.append((list(argv), env))
        return type("P", (), {"returncode": 0, "stdout": '{"id": 1}', "stderr": ""})()

    assert forge.comment_post(tmp_path, 7, "b", info=GITHUB, runner=rec).status == "ok"
    assert seen[0][0][:3] == ["gh", "api", "repos/o/r/issues/7/comments"]
    assert seen[0][1]["GH_TOKEN"] == "tok-bot"


@pytest.mark.parametrize("op", GH_WRITES)
def test_gitea_writes_get_no_identity_inputs_and_no_token_runner(op, monkeypatch, tmp_path):
    _repo_naming_the_bot(tmp_path)
    monkeypatch.setattr(forge_gitea, "token_for", lambda web_base, **kw: "tk")

    def boom(*_a, **_k):
        raise AssertionError("Gitea must never fetch a gh bot token")

    monkeypatch.setattr(automation_identity, "bot_token", boom)
    calls = _spy(monkeypatch, forge_gitea, op, forge.Result.ok({}))
    assert _call(op, tmp_path, GITEA).status == "ok"
    assert "config" not in calls[0][1] and "env" not in calls[0][1]
    assert calls[0][1]["token"] == "tk"


def test_github_pr_create_builds_the_gh_args(monkeypatch, tmp_path):
    calls = _spy(monkeypatch, forge_github, "pr_create",
                 forge.Result.ok({"returncode": 0}))
    result = forge.pr_create(tmp_path, base="main", head="feat", title="T", body="B",
                             info=GITHUB)
    assert result.status == "ok"
    args, kwargs = calls[0]
    assert args[0] == GITHUB
    assert args[1] == ["--base", "main", "--head", "feat", "--title", "T",
                       "--body", "B"]
    assert args[2] == {} and args[3] == "manual"
    assert kwargs.get("runner") is None


def test_github_pr_create_passes_a_reviewer(monkeypatch, tmp_path):
    calls = _spy(monkeypatch, forge_github, "pr_create",
                 forge.Result.ok({"returncode": 0}))
    forge.pr_create(tmp_path, base="main", head="feat", title="T", body="B",
                    reviewers="bot", info=GITHUB)
    assert calls[0][0][1][-2:] == ["--reviewer", "bot"]


def test_gitea_without_token_pr_create_passes_the_reviewer_to_agit(monkeypatch, tmp_path):
    monkeypatch.setattr(forge_gitea, "token_for", lambda web_base, **kw: None)
    calls = _spy(monkeypatch, forge_gitea_agit, "pr_create_agit",
                 forge.Result.ok({"url": "https://gitea.lan/o/r/pulls/3", "number": 3}))
    forge.pr_create(tmp_path, base="main", head="feat", title="T", body="B",
                    reviewers="bot", info=GITEA)
    assert calls[0][1]["reviewers"] == "bot"


# --- resolve is the shared front door --------------------------------------------


def test_ops_resolve_when_info_is_not_supplied(monkeypatch, tmp_path):
    seen = []

    def fake_resolve(repo, **kw):
        seen.append(repo)
        return OTHER_ALIAS

    monkeypatch.setattr(forge, "resolve", fake_resolve)
    for op in ["pr_create", "pr_read", "comment_post", "comment_edit", "label_add",
               "label_remove"]:
        assert _call(op, tmp_path, None).status == "degraded"
    assert seen == [tmp_path] * 6
