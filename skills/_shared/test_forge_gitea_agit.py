"""Tests for forge_gitea_agit.py: no-token PR create over AGit, setup-line degrades.

design: forge-interface (Task 1.4). Hermetic: one recording fake `runner` (argv ->
CompletedProcess-like) answering with the stderr a real Gitea prints on an AGit push;
no `git`, no network, no token. The assertions are the shapes a real Gitea 1.22
answers — the PR URL arrives in the push's remote: output, an update push for the same
topic returns the SAME PR, and a failure is a degrade naming a compare URL built from
`web_base` (a Gitea on a custom port behind an ssh alias keeps its port; `github.com`
appears in no field). The comment/label degrades carry the one setup line from
`forge_gitea.setup_line`.
Run with: python3 -m pytest skills/_shared/test_forge_gitea_agit.py -q -n0
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge_gitea_agit  # noqa: E402
from forge import ForgeInfo  # noqa: E402

INFO = ForgeInfo("gitea", "gitea.lan", "home", "lab", "https://gitea.lan",
                 "https://gitea.lan/api/v1", "")
# The ssh-alias case Task 1.1 records: the ssh host (`gitea`) is not the web host,
# and the instance is on a custom port only `forge.web_base` knows.
ALIAS = ForgeInfo("gitea", "gitea", "scurtis", "Homelab",
                  "https://truenas.home.arpa:30008",
                  "https://truenas.home.arpa:30008/api/v1", "")
PUSH = ["git", "push", "origin", "tp/x:refs/for/master", "-o", "topic=tp/x",
        "-o", "title=T", "-o", "description=a b"]
REMOTE_OK = "remote:   https://gitea.lan/home/lab/pulls/7\n"
RERUN_NOTE = "later pushes: re-run `forge.py pr-create` to update the PR"
FLAT_NOTE = "description flattened (AGit push options are single-line)"
TRUNC_NOTE = "description truncated to 1000 chars"
REVIEWER_NOTE = "reviewers not requested on Gitea"
OPS = ("comment-post", "comment-edit", "label-add", "label-remove")


class FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Recorder:
    """Fake runner: records every argv and the kwargs, answers from a queue.

    The LAST scripted proc repeats, so a re-run test scripts the create push and
    the update push separately and still sees the update's output. `missing=True`
    raises what a machine without `git` raises.
    """

    def __init__(self, *procs: FakeProc, missing: bool = False) -> None:
        self.calls: list[list] = []
        self.kwargs: list[dict] = []
        self.procs = list(procs) or [FakeProc()]
        self.missing = missing

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        if self.missing:
            raise FileNotFoundError(2, "No such file or directory: 'git'")
        return self.procs[-1] if len(self.procs) == 1 else self.procs.pop(0)


def agit(info, *, body="a\nb", **kw):
    """`pr_create_agit` with the plan's example inputs."""
    return forge_gitea_agit.pr_create_agit(info, base="master", head="tp/x",
                                           title="T", body=body, **kw)


# --- the AGit push: one argv, the PR URL from its remote: output --------------

def test_agit_push_argv_and_captured_pr():
    """A multi-line body flattens into one `-o description=` push option."""
    rec = Recorder(FakeProc(0, "", REMOTE_OK))
    res = agit(INFO, runner=rec)
    assert rec.calls == [PUSH]
    assert res.status == "ok"
    assert res.payload == {"url": "https://gitea.lan/home/lab/pulls/7", "number": 7}
    assert FLAT_NOTE in res.note and RERUN_NOTE in res.note


def test_agit_reads_the_url_from_stdout_too():
    rec = Recorder(FakeProc(0, REMOTE_OK, ""))
    res = agit(INFO, runner=rec)
    assert res.status == "ok"
    assert res.payload == {"url": "https://gitea.lan/home/lab/pulls/7", "number": 7}


def test_agit_one_line_body_notes_only_the_rerun():
    """The re-run note is on EVERY AGit ok; the flatten note only when it happened."""
    rec = Recorder(FakeProc(0, "", REMOTE_OK))
    res = forge_gitea_agit.pr_create_agit(INFO, base="master", head="tp/x",
                                          title="T", body="one line", runner=rec)
    assert res.status == "ok"
    assert res.note == RERUN_NOTE
    assert rec.calls[0][-2:] == ["-o", "description=one line"]


def test_agit_description_collapses_and_caps():
    """Newlines collapse to spaces; the push option is capped at 1000 chars."""
    rec = Recorder(FakeProc(0, "", REMOTE_OK))
    res = agit(INFO, body="x" * 1200, runner=rec)
    desc = rec.calls[0][-1]
    assert desc == "description=" + "x" * 1000
    assert TRUNC_NOTE in res.note and RERUN_NOTE in res.note
    rec2 = Recorder(FakeProc(0, "", REMOTE_OK))
    res2 = agit(INFO, body="a\nb\nc", runner=rec2)
    assert rec2.calls[0][-1] == "description=a b c"


def test_agit_pushes_in_the_repo_it_was_given(monkeypatch):
    """The DEFAULT runner (no seam) pushes inside `repo` — that is where origin is."""
    seen: dict = {}

    class FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            seen.update(kwargs, argv=list(argv))
            return FakeProc(0, "", REMOTE_OK)

    monkeypatch.setattr(forge_gitea_agit, "subprocess", FakeSubprocess)
    res = agit(INFO, repo="/home/op/lab")
    assert res.status == "ok"
    assert seen["cwd"] == "/home/op/lab"
    assert seen["argv"] == PUSH


def test_agit_runner_seam_takes_argv_only():
    """A positional-only fake runner is honored — no kwargs forced on the seam."""
    rec = Recorder(FakeProc(0, "", REMOTE_OK))
    assert agit(INFO, runner=lambda argv: rec(argv), repo="/x").status == "ok"
    assert rec.calls == [PUSH]


# --- idempotent per topic: the re-run updates the same PR --------------------

def test_agit_rerun_for_same_head_is_the_same_push_and_the_same_pr():
    rec = Recorder(FakeProc(0, "", REMOTE_OK), FakeProc(0, "", REMOTE_OK))
    first = agit(INFO, runner=rec)
    second = agit(INFO, runner=rec)
    assert len(rec.calls) == 2
    assert rec.calls[0] == rec.calls[1] == PUSH  # no new topic, no branch delete
    assert first.payload == second.payload == {
        "url": "https://gitea.lan/home/lab/pulls/7", "number": 7}


def test_agit_rerun_updates_a_pr_numbered_differently():
    """The URL is captured per push, so an update naming another PR returns it."""
    rec = Recorder(FakeProc(0, "", REMOTE_OK),
                   FakeProc(0, "", "remote:   https://gitea.lan/home/lab/pulls/9\n"))
    agit(INFO, runner=rec)
    second = agit(INFO, runner=rec)
    assert second.status == "ok"
    assert second.payload == {"url": "https://gitea.lan/home/lab/pulls/9",
                              "number": 9}


# --- failure degrades with the Gitea compare URL, never a github.com one -----

def test_agit_nonzero_rc_degrades_with_compare_url():
    rec = Recorder(FakeProc(1, "", "remote: fail to find base commit\n"))
    res = agit(INFO, runner=rec)
    assert res.status == "degraded"
    assert res.payload == {}
    assert res.line == res.line.strip() and "\n" not in res.line
    assert "https://gitea.lan/home/lab/compare/master...tp/x" in res.line


def test_agit_rc_zero_without_a_pr_url_degrades():
    rec = Recorder(FakeProc(0, "Everything up-to-date\n", ""))
    res = agit(INFO, runner=rec)
    assert res.status == "degraded"
    assert "https://gitea.lan/home/lab/compare/master...tp/x" in res.line


def test_agit_without_git_degrades_with_compare_url():
    rec = Recorder(missing=True)
    res = agit(INFO, runner=rec)
    assert res.status == "degraded"
    assert "https://gitea.lan/home/lab/compare/master...tp/x" in res.line


def test_agit_failure_on_an_ssh_alias_keeps_the_web_base_port():
    rec = Recorder(FakeProc(1, "", "Permission denied (publickey)\n"))
    res = agit(ALIAS, runner=rec)
    assert res.status == "degraded"
    assert ("https://truenas.home.arpa:30008/scurtis/Homelab"
            "/compare/master...tp/x") in res.line
    assert "gitea:scurtis" not in res.line  # never ssh-style addressing


@pytest.mark.parametrize("proc", [
    FakeProc(1, "", "remote: fail to find base commit\n"),
    FakeProc(0, "", ""),
    FakeProc(0, "", REMOTE_OK),
])
def test_github_com_appears_in_no_field(proc):
    rec = Recorder(proc)
    for res in (agit(INFO, runner=rec), agit(ALIAS, runner=rec),
                forge_gitea_agit.no_token("label-add", ALIAS)):
        fields = [res.status, res.line, res.note] + [str(v) for v in res.payload.values()]
        assert all("github.com" not in f for f in fields)


def test_compare_url_is_web_base_owned_repo_base_dot_dot_dot_head():
    assert forge_gitea_agit.compare_url(ALIAS, "master", "tp/x") == (
        "https://truenas.home.arpa:30008/scurtis/Homelab/compare/master...tp/x")


# --- comment / edit / label with no token: the setup line, visibly -----------

@pytest.mark.parametrize("op", OPS)
def test_no_token_degrades_with_the_setup_line(op):
    res = forge_gitea_agit.no_token(op, INFO)
    assert res.status == "degraded"
    assert res.payload == {}
    assert res.line == res.line.strip() and "\n" not in res.line
    assert op in res.line
    assert "export GITEA_TOKEN=" in res.line
    assert "tea login add --url https://gitea.lan" in res.line


def test_no_token_setup_line_names_the_instance_web_base():
    res = forge_gitea_agit.no_token("comment-post", ALIAS)
    assert "tea login add --url https://truenas.home.arpa:30008" in res.line


# --- never silent: a dropped reviewer / a cut description say so ---------------

def test_agit_reviewer_is_a_visible_no_op():
    """AGit has no reviewer slot; like the REST path it says so instead of dropping it."""
    rec = Recorder(FakeProc(0, "", REMOTE_OK))
    res = agit(INFO, runner=rec, reviewers="copilot")
    assert res.status == "ok"
    assert REVIEWER_NOTE in res.note and RERUN_NOTE in res.note
    assert "copilot" not in " ".join(rec.calls[0])  # nothing leaks into the push


def test_agit_without_a_reviewer_has_no_reviewer_note():
    res = agit(INFO, body="one line", runner=Recorder(FakeProc(0, "", REMOTE_OK)))
    assert REVIEWER_NOTE not in res.note


def test_agit_truncation_note_is_separate_from_the_flatten_note():
    res = agit(INFO, body="a\n" + "x" * 1200, runner=Recorder(FakeProc(0, "", REMOTE_OK)))
    assert FLAT_NOTE in res.note and TRUNC_NOTE in res.note
    exact = agit(INFO, body="x" * 1000, runner=Recorder(FakeProc(0, "", REMOTE_OK)))
    assert TRUNC_NOTE not in exact.note  # exactly at the cap loses nothing
