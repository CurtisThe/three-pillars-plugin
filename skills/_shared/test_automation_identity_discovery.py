"""test_automation_identity_discovery.py — a write helper finds the repo config itself.

design: review-proof-ambient-gh-identity, Task 1.1 (behaviour B6 at the core)

`run_gh_write` defaults `config=DISCOVER`: it loads `.three-pillars/config.json` from the git
toplevel via `load_repo_config(_default_repo_root())`, so a prompt never has to name the
identity. An explicit `config=None` or `{}` stays the byte-identical ambient path. The shipped
autouse fixture in `skills/conftest.py` pins `_default_repo_root` to an empty dir so every other
test stays hermetic; the tests here opt back in by patching `_default_repo_root` to a tmp repo.

Run with: pytest skills/_shared/test_automation_identity_discovery.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import automation_identity as ai  # noqa: E402

WRITE = ["gh", "api", "repos/o/r/issues/7/comments", "-f", "body=x"]
BOT_CFG = {"github": {"pr_author_account": "CurtisTheBot", "used_for": "all-prs"}}


class Rec:
    def __init__(self):
        self.calls: list = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class Tok:
    def __init__(self):
        self.calls: list = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="tok-bot\n", stderr="")


def _repo(tmp_path, config_text=None) -> Path:
    repo = tmp_path / "repo"
    (repo / ".three-pillars").mkdir(parents=True)
    if config_text is not None:
        (repo / ".three-pillars" / "config.json").write_text(config_text, encoding="utf-8")
    return repo


@pytest.fixture
def discovered(monkeypatch):
    """Opt back in to discovery: `_default_repo_root` answers the repo the test names."""
    def point_at(repo):
        monkeypatch.setattr(ai, "_default_repo_root", lambda: repo)
    return point_at


def test_a_call_with_no_config_posts_as_the_bot_the_repo_config_names(tmp_path, discovered):
    discovered(_repo(tmp_path, json.dumps(BOT_CFG)))
    rec, tok = Rec(), Tok()
    ai.run_gh_write(WRITE, runner=rec, env={"PATH": "/bin"}, token_runner=tok)
    assert tok.calls == [["gh", "auth", "token", "--user", "CurtisTheBot"]]
    assert len(rec.calls) == 1
    assert rec.calls[0][1]["env"]["GH_TOKEN"] == "tok-bot"


def test_the_discover_sentinel_is_the_default_and_can_be_passed_explicitly(tmp_path, discovered):
    discovered(_repo(tmp_path, json.dumps(BOT_CFG)))
    rec, tok = Rec(), Tok()
    ai.run_gh_write(WRITE, config=ai.DISCOVER, runner=rec, env={}, token_runner=tok)
    assert rec.calls[0][1]["env"]["GH_TOKEN"] == "tok-bot"


def test_a_repo_with_no_config_file_is_ambient(tmp_path, discovered):
    discovered(_repo(tmp_path))
    rec, tok = Rec(), Tok()
    ai.run_gh_write(WRITE, runner=rec, token_runner=tok, capture_output=True)
    assert rec.calls == [(WRITE, {"capture_output": True})]  # no env key
    assert tok.calls == []


def test_an_unparseable_config_file_refuses_before_anything_runs(tmp_path, discovered):
    discovered(_repo(tmp_path, "{not json"))
    rec, tok = Rec(), Tok()
    with pytest.raises(ai.BotAuthUnavailable):
        ai.run_gh_write(WRITE, runner=rec, token_runner=tok)
    assert rec.calls == [] and tok.calls == []


@pytest.mark.parametrize("config", [None, {}])
def test_an_explicit_empty_config_never_discovers(tmp_path, discovered, config):
    discovered(_repo(tmp_path, json.dumps(BOT_CFG)))  # a bot IS discoverable, and is ignored
    rec, tok = Rec(), Tok()
    ai.run_gh_write(WRITE, config=config, runner=rec, token_runner=tok)
    assert rec.calls == [(WRITE, {})]
    assert tok.calls == []


def test_the_shipped_fixture_makes_a_no_config_call_ambient_without_any_opt_in():
    """No opt-in here: the autouse fixture in `skills/conftest.py` pinned discovery to an empty
    dir, so a no-config call is ambient even when cwd is a repo whose config names a bot."""
    pinned = ai._default_repo_root
    assert getattr(pinned, "__wrapped__", None) is not None, "the autouse pin is not applied"
    assert ai.load_repo_config(pinned()) == {}
    rec, tok = Rec(), Tok()
    ai.run_gh_write(WRITE, runner=rec, token_runner=tok)
    assert rec.calls == [(WRITE, {})]
    assert tok.calls == []
