"""test_explain_deliver_forge_identity.py - explainer posts run the REAL forge as the bot.

design: review-proof-ambient-gh-identity, phase-check F1.

forge owns the identity of comment writes (automation_identity.run_gh_write calls
runner(argv, env=...) when a bot is configured), so explain_deliver.post_or_edit must work
against the real forge with a bot configured: it must not hand the forge a runner that
rejects env, and the bot token is fetched once per write. Hermetic: subprocess.run is
patched for gh (the vcs stays real), so no live gh, no keyring, no token, no network.

Run with: pytest skills/_shared/explainer/test_explain_deliver_forge_identity.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE.parent, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_deliver  # noqa: E402
import explainer_marker  # noqa: E402
from test_explain_deliver_degrade import _git as _vcs  # noqa: E402

BOT = "CurtisTheBot"
TOKEN = "tok-forge-identity"
SLUG = "demo"
CONFIG_DIR = ".three-pillars"  # the repo config dir
_REAL_RUN = subprocess.run


@pytest.fixture
def bot_repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _vcs(root, "init", "-q")
    _vcs(root, "commit", "-q", "--allow-empty", "-m", "init")
    _vcs(root, "remote", "add", "origin", "https://github.com/octo/repo.git")
    (root / CONFIG_DIR).mkdir()
    cfg = dict(github=dict(pr_author_account=BOT, used_for="all-prs"))
    (root / CONFIG_DIR / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root


class GhSpy:
    """subprocess.run stand-in: real vcs calls, canned gh; records each gh call."""

    def __init__(self):
        self.token_probes: list = []
        self.api_calls: list = []

    def __call__(self, argv, *args, **kw):
        if argv and argv[0] != "gh":
            return _REAL_RUN(argv, *args, **kw)
        if argv[1:3] == ["auth", "token"]:
            self.token_probes.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout=TOKEN + "\n", stderr="")
        self.api_calls.append((list(argv), kw.get("env")))
        if "--paginate" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")
        reply = json.dumps(dict(id=77, html_url="https://github.com/octo/repo/issues/7#c77"))
        return subprocess.CompletedProcess(argv, 0, stdout=reply, stderr="")


def test_post_or_edit_with_a_bot_configured_posts_through_the_real_forge(
        bot_repo, monkeypatch, capsys):
    spy = GhSpy()
    monkeypatch.setattr(subprocess, "run", spy)
    body = explainer_marker.marker("pr-brief", SLUG, "abc123") + "\n\nBody text.\n"
    result = explain_deliver.post_or_edit(bot_repo, SLUG, 7, body, kind="pr-brief",
                                          context="manual")
    assert result.status == "ok", result
    assert result.payload.get("id") == 77
    posts = [(argv, env) for argv, env in spy.api_calls if "--paginate" not in argv]
    assert len(posts) == 1
    assert posts[0][1]["GH_TOKEN"] == TOKEN  # the write ran as the bot
    assert len(spy.token_probes) == 1  # fetched once for the one write, not twice
    assert capsys.readouterr().out == ""
