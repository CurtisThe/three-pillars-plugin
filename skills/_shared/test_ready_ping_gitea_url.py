"""Gitea PR URLs (`/pulls/<n>`) keep the PR number in the operator pings.

Forge parity: on Gitea the ping must name the PR, never silently drop `#N`.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ready_ping import ping_ready, ping_stop, pr_number  # noqa: E402

GITEA_URL = "https://gitea.example.com/o/r/pulls/12"


def test_pr_number_reads_gitea_pulls_url():
    assert pr_number(GITEA_URL) == 12


def test_pr_number_still_reads_github_pull_url():
    assert pr_number("https://github.com/o/r/pull/7") == 7


def test_pr_number_ignores_gitea_trailing_segment():
    assert pr_number(GITEA_URL + "/files") == 12


def test_gitea_ready_ping_keeps_pr_number(tmp_path):
    sent = ping_ready(GITEA_URL, "abc123", info_fn=lambda u: {},
                      ledger=tmp_path / "l.ndjson", out=io.StringIO())
    assert "#12" in sent["message"]


def test_gitea_stop_ping_names_pr(tmp_path):
    stop = {"source": "pr-iterate", "signal": "cap-reached", "target": GITEA_URL}
    sent = ping_stop(stop, info_fn=lambda u: {}, ledger=tmp_path / "s.ndjson",
                     out=io.StringIO())
    assert "#12" in sent.get("message", "")
