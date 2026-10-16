"""Tests for forge_cli.py: one entry point, one exit-code contract.

design: forge-interface (Task 1.5). Everything runs in-process through
`forge.main(argv)` — no subprocess, no network, no git: `forge.resolve` is
monkeypatched to a fixed `ForgeInfo`, the forge ops are monkeypatched to recorders
returning fixed `Result`s, and `github_pr_author.main` is a recorder. The assertions
are the contract: exit 0 ok, 2 usage, 3 bot-auth-unavailable (github only), 4
degraded; stdout carries only machine-readable output (the ForgeInfo JSON, a payload
JSON, a PR URL or a compare URL) and **never** a `github.com` URL for a Gitea origin
or any guessed URL shape for kind `other`; every degrade is the one line on stderr.
Run with: python3 -m pytest skills/_shared/test_forge_cli.py -q -n0
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge  # noqa: E402
import github_pr_author  # noqa: E402

GITHUB = forge.ForgeInfo("github", "github.com", "o", "r", "https://github.com",
                         "https://api.github.com", "")
GITEA = forge.ForgeInfo("gitea", "gitea.lan", "o", "r", "https://gitea.lan",
                        "https://gitea.lan/api/v1", "")
GITEA_PORTED = forge.ForgeInfo("gitea", "gitea.lan", "o", "r",
                               "https://gitea.lan:3000",
                               "https://gitea.lan:3000/api/v1", "")
OTHER_ALIAS = forge.ForgeInfo("other", "gitea", "scurtis", "Homelab", "", "",
                              "no web base — " + forge.NO_WEB_BASE_LINE)
OTHER_HOST = forge.ForgeInfo("other", "git.example.com", "o", "r",
                             "https://git.example.com",
                             "https://git.example.com/api/v1",
                             "unsupported forge: git.example.com")


def _unsupported_line(info: forge.ForgeInfo) -> str:
    """The one stderr line; a reason that already says `unsupported forge` is not
    wrapped in a second `unsupported forge: X (…)`."""
    if info.reason.startswith("unsupported forge"):
        return info.reason
    return f"unsupported forge: {info.host} ({info.reason})"


def _info(monkeypatch, info: forge.ForgeInfo) -> None:
    monkeypatch.setattr(forge, "resolve", lambda repo, **kw: info)


def _op(monkeypatch, name: str, result: forge.Result) -> list:
    """Replace `forge.<name>` with a recorder of `(args, kwargs)`; return the log."""
    calls: list = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(forge, name, fake)
    return calls


# --- resolve --------------------------------------------------------------------


def test_resolve_prints_the_forge_info_json(monkeypatch, capsys, tmp_path):
    _info(monkeypatch, GITEA)
    rc = forge.main(["resolve", "--repo", str(tmp_path)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "kind": "gitea", "host": "gitea.lan", "owner": "o", "repo": "r",
        "web_base": "https://gitea.lan", "api_base": "https://gitea.lan/api/v1",
        "reason": "",
    }


# --- compare-url: built from web_base, never guessed ----------------------------


@pytest.mark.parametrize("info,url", [
    (GITHUB, "https://github.com/o/r/compare/B...H?expand=1"),
    (GITEA, "https://gitea.lan/o/r/compare/B...H"),
    (GITEA_PORTED, "https://gitea.lan:3000/o/r/compare/B...H"),
], ids=["github", "gitea", "ported"])
def test_compare_url_prints_the_kits_own_url(info, url, monkeypatch, capsys, tmp_path):
    _info(monkeypatch, info)
    rc = forge.main(["compare-url", "--base", "B", "--head", "H",
                     "--repo", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == url
    assert captured.err == ""


@pytest.mark.parametrize("info", [OTHER_ALIAS, OTHER_HOST], ids=["alias", "host"])
def test_compare_url_for_other_prints_no_url(info, monkeypatch, capsys, tmp_path):
    _info(monkeypatch, info)
    rc = forge.main(["compare-url", "--base", "B", "--head", "H",
                     "--repo", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 4
    assert captured.out == ""
    assert captured.err.strip() == _unsupported_line(info)


# --- pr-create: github keeps the PR-author chokepoint ---------------------------


@pytest.mark.parametrize("rc,expected", [(0, 0), (1, 1)],
                         ids=["author_ok", "author_fails"])
def test_github_pr_create_delegates_the_passthrough_verbatim(rc, expected, monkeypatch,
                                                            tmp_path):
    _info(monkeypatch, GITHUB)
    calls = []

    def record(argv):
        calls.append(list(argv))
        return rc

    monkeypatch.setattr(github_pr_author, "main", record)
    assert forge.main(["pr-create", "--context", "manual", "--repo", str(tmp_path),
                       "--", "--base", "main", "--head", "feat", "--title", "T",
                       "--body", "B"]) == expected
    assert calls == [["create", "--context", "manual", "--repo", str(tmp_path), "--",
                      "--base", "main", "--head", "feat", "--title", "T",
                      "--body", "B"]]


def test_github_pr_create_bot_auth_unavailable_is_exit_3(monkeypatch, capsys, tmp_path):
    _info(monkeypatch, GITHUB)

    def boom(argv):
        raise github_pr_author.BotAuthUnavailable("gh auth token --user bot failed")

    monkeypatch.setattr(github_pr_author, "main", boom)
    assert forge.main(["pr-create", "--repo", str(tmp_path), "--", "--base", "main",
                       "--head", "feat"]) == 3
    captured = capsys.readouterr()
    assert "gh auth token --user bot failed" in captured.err
    assert captured.out == ""


def test_gitea_pr_create_ok_prints_the_pr_url(monkeypatch, capsys, tmp_path):
    _info(monkeypatch, GITEA)
    calls = _op(monkeypatch, "pr_create",
                forge.Result.ok({"url": "https://gitea.lan/o/r/pulls/3", "number": 3},
                                "later pushes: re-run"))
    rc = forge.main(["pr-create", "--", "--base", "main", "--head", "feat",
                     "--title", "T", "--body", "B", "--repo", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "https://gitea.lan/o/r/pulls/3"
    assert "re-run" in captured.err
    assert calls[0][1]["base"] == "main" and calls[0][1]["info"] == GITEA


def test_gitea_pr_create_degraded_prints_the_compare_url(monkeypatch, capsys, tmp_path):
    _info(monkeypatch, GITEA_PORTED)
    _op(monkeypatch, "pr_create",
        forge.Result.degraded("AGit PR create failed (exit 1) — retry later"))
    body = tmp_path / "body.md"
    body.write_text("B\n", encoding="utf-8")
    rc = forge.main(["pr-create", "--", "--base", "main", "--head", "feat",
                     "--title", "T", "--body-file", str(body), "--repo", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 4
    assert captured.out.strip() == "https://gitea.lan:3000/o/r/compare/main...feat"
    assert captured.err.strip() == "AGit PR create failed (exit 1) — retry later"


@pytest.mark.parametrize("info", [OTHER_ALIAS, OTHER_HOST], ids=["alias", "host"])
def test_pr_create_for_other_prints_no_url(info, monkeypatch, capsys, tmp_path):
    _info(monkeypatch, info)
    rc = forge.main(["pr-create", "--", "--base", "main", "--head", "feat",
                     "--title", "T", "--body", "B", "--repo", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 4
    assert captured.out == ""
    assert captured.err.strip() == _unsupported_line(info)


# --- the payload ops ------------------------------------------------------------


PAYLOAD_OPS = [
    ("pr-read", "7", "pr_read"),
    ("comment-post", "7", "comment_post"),
    ("comment-edit", "99", "comment_edit"),
    ("label-add", "7", "bug", "label_add"),
    ("label-remove", "7", "bug", "label_remove"),
]


def _tail(name: str, spec: tuple, tmp_path) -> list:
    """The argv for one payload op, with `--body-file` filled in where it applies."""
    head, arg = spec[0], spec[1]
    tail = [head, arg]
    if name in ("comment_post", "comment_edit"):
        body = tmp_path / "body.md"
        body.write_text("héllo\nworld\n", encoding="utf-8")
        tail += ["--body-file", str(body)]
    if len(spec) == 4:
        tail.append(spec[2])
    return tail


@pytest.mark.parametrize("name", [spec[-1] for spec in PAYLOAD_OPS])
def test_payload_ops_print_the_payload_json(name, monkeypatch, capsys, tmp_path):
    _info(monkeypatch, GITEA)
    spec = next(s for s in PAYLOAD_OPS if s[-1] == name)
    calls = _op(monkeypatch, name, forge.Result.ok({"ok": 1}))
    rc = forge.main(_tail(name, spec, tmp_path) + ["--repo", str(tmp_path)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"ok": 1}
    args, kwargs = calls[0]
    assert args[0] == str(tmp_path) and args[1:] and kwargs["info"] == GITEA
    if name == "comment_post":
        assert args[2] == "héllo\nworld\n"


@pytest.mark.parametrize("name", [spec[-1] for spec in PAYLOAD_OPS])
def test_payload_ops_degrade_to_exit_4(name, monkeypatch, capsys, tmp_path):
    _info(monkeypatch, GITEA)
    spec = next(s for s in PAYLOAD_OPS if s[-1] == name)
    _op(monkeypatch, name, forge.Result.degraded("nope: tea login add --url x"))
    rc = forge.main(_tail(name, spec, tmp_path) + ["--repo", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 4
    assert captured.out == ""
    assert captured.err.strip() == "nope: tea login add --url x"


# --- github writes run as the configured bot -------------------------------------


def _bot_repo(tmp_path) -> Path:
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars" / "config.json").write_text(
        json.dumps({"github": {"pr_author_account": "CurtisTheBot"}}), encoding="utf-8")
    return tmp_path


def _fake_gh(monkeypatch, token_rc: int) -> list:
    """Patch `subprocess.run`: `gh auth token` answers `token_rc`; `gh api` records its env."""
    seen: list = []

    def fake(argv, **kwargs):
        if argv[:3] == ["gh", "auth", "token"]:
            return subprocess.CompletedProcess(argv, token_rc, "tok-bot\n", "no keyring")
        seen.append((list(argv), kwargs.get("env")))
        return subprocess.CompletedProcess(argv, 0, '{"id": 1, "html_url": "u"}', "")

    monkeypatch.setattr(subprocess, "run", fake)
    return seen


@pytest.mark.parametrize("name", ["comment_post", "comment_edit", "label_add", "label_remove"])
def test_github_write_with_an_unavailable_bot_token_is_exit_3(name, monkeypatch, capsys,
                                                              tmp_path):
    _info(monkeypatch, GITHUB)
    repo = _bot_repo(tmp_path)
    seen = _fake_gh(monkeypatch, token_rc=1)
    spec = next(s for s in PAYLOAD_OPS if s[-1] == name)
    rc = forge.main(_tail(name, spec, tmp_path) + ["--repo", str(repo)])
    captured = capsys.readouterr()
    assert rc == 3 and seen == []  # nothing posted as the wrong identity
    assert captured.out == ""
    assert "CurtisTheBot" in captured.err and "tok-bot" not in captured.err
    assert len(captured.err.strip().splitlines()) == 1


def test_github_write_posts_as_the_configured_bot(monkeypatch, capsys, tmp_path):
    _info(monkeypatch, GITHUB)
    repo = _bot_repo(tmp_path)
    seen = _fake_gh(monkeypatch, token_rc=0)
    spec = next(s for s in PAYLOAD_OPS if s[-1] == "comment_post")
    assert forge.main(_tail("comment_post", spec, tmp_path) + ["--repo", str(repo)]) == 0
    assert seen[0][0][:3] == ["gh", "api", "repos/o/r/issues/7/comments"]
    assert seen[0][1]["GH_TOKEN"] == "tok-bot"
    assert "tok-bot" not in capsys.readouterr().out


# --- usage ----------------------------------------------------------------------


@pytest.mark.parametrize("argv", [
    ["frobnicate"],
    ["compare-url", "--base", "B"],
    ["pr-read"],
    ["resolve", "--nope"],
], ids=["bad_subcommand", "missing_head", "missing_number", "bad_flag"])
def test_usage_errors_are_exit_2(argv, monkeypatch, capsys, tmp_path):
    _info(monkeypatch, GITEA)
    assert forge.main(argv + ["--repo", str(tmp_path)]) == 2
