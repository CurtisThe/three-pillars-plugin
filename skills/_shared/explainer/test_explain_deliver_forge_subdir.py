"""test_explain_deliver_forge_subdir.py - forge finds the bot config from a repo subdirectory.

design: review-proof-ambient-gh-identity, phase-check F3.

forge._dispatch reads the automation config for a comment or label write. When `repo` is a
subdirectory of the configured repo (repo="." from a subdirectory), a raw Path(repo) read
finds no config and the write would run as the ambient login. The config is read from the
repo's toplevel, as automation_identity._default_repo_root resolves it.

Run with: pytest skills/_shared/explainer/test_explain_deliver_forge_subdir.py -q
"""
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE.parent, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge  # noqa: E402
from test_explain_deliver_forge_identity import TOKEN, GhSpy, bot_repo  # noqa: E402,F401


def test_a_write_from_a_subdirectory_still_runs_as_the_configured_bot(bot_repo, monkeypatch):
    sub = bot_repo / "pkg" / "deep"
    sub.mkdir(parents=True)
    spy = GhSpy()
    monkeypatch.setattr(subprocess, "run", spy)
    result = forge.comment_post(sub, 7, "a body")
    assert result.status == "ok", result
    posts = [env for argv, env in spy.api_calls if "--paginate" not in argv]
    assert len(posts) == 1
    assert posts[0]["GH_TOKEN"] == TOKEN
