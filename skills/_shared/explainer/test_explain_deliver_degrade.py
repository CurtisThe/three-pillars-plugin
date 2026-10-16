"""test_explain_deliver_degrade.py — refresh check, bot authorship and the visible degrade line.

Covers explainer-agent plan Task 8.4 (detailed-design §Interfaces, the explain_deliver
bullet, the CLI degrade line, and decisions.md "Comment authorship and degrade lines"):
  - `refresh_needed(root, slug, pr, forge_mod=...)` is True when the PR head commit
    (`head_sha`) from `forge.pr_read` differs from the stored marker head (`posted_head`),
    False when equal;
  - `post_or_edit` hands the forge no runner (the forge owns the write identity, see
    test_explain_deliver_forge_identity.py), and a `BotAuthUnavailable` from the forge prints
    one `explainer: <reason> — see <path>` line (stderr) and returns a degraded Result with
    nothing posted;
  - a forge degrade (Gitea without a token) is reported by `degrade_line`: one line on
    stderr, the reason stored once in `delivery.degraded`, and `brief.md` still on disk;
  - a refresh edits a comment and runs no `git commit`.

Every test builds a tmp git repo under `tmp_path`, passes a fake forge module, so nothing touches the network, a keyring, or the real repo's
`.git/three-pillars/explainer/`. Assertions read parsed values (the printed line's parts,
JSON state, the fake forge's recorded calls), never pinned markup
(skills/_shared/test-fragility.md).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import automation_identity  # noqa: E402
import explain_deliver  # noqa: E402
import explain_envelope  # noqa: E402
import explain_state  # noqa: E402
import explainer_marker  # noqa: E402
import forge  # noqa: E402
import forge_gitea  # noqa: E402
from forge import Result  # noqa: E402

SLUG = "demo"
STORED_HEAD = "abc123"
_REAL_RUN = subprocess.run
_LINE = re.compile(r"^explainer: (?P<reason>.+) — see (?P<path>.+)$")


def _git(cwd, *args) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    out = _REAL_RUN(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                    cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    return root


def _env() -> dict:
    sections = [{"id": sid, "title": f"Title {sid}",
                 "items": [{"text": f"Item for {sid}.", "refs": ["diffstat"]}]}
                for sid in explain_envelope.REQUIRED_SECTIONS["pr-brief"]]
    return {"schema": explain_envelope.SCHEMA, "kind": "pr-brief",
            "ste_summary": {"text": "The change adds a brief.", "refs": ["diffstat"]},
            "sections": sections, "diagram_specs": [],
            "confidence_note": {"text": "The evidence is the diff.", "refs": ["diffstat"]}}


def _body(kind="pr-brief", head="new111") -> str:
    return explainer_marker.marker(kind, SLUG, head) + "\n\nBody text.\n"


def _entry(repo, kind="pr-brief") -> dict:
    return explain_state.delivery(repo, SLUG, kind)


def _lines(captured_text) -> list:
    return [ln for ln in captured_text.splitlines() if ln.strip()]


class FakeForge:
    """A forge module stand-in: records each call and the `runner` it was given."""

    def __init__(self, *, pr_head="def456", comments=None, fail=(), bot_error=None):
        self.bot_error = bot_error
        self.pr_head = pr_head
        self.comments = list(comments or [])
        self.fail = set(fail)
        self.calls: list = []
        self.runners: dict = {}
        self.kwargs: list = []

    def _note(self, op, kw):
        self.calls.append(op)
        self.runners.setdefault(op, kw.get("runner"))
        self.kwargs.append(dict(kw))
        if self.bot_error is not None:
            raise self.bot_error

    def pr_read(self, repo, number, **kw):
        self._note("pr_read", kw)
        if "pr_read" in self.fail:
            return Result.degraded("pr read refused")
        return Result.ok({"number": number, "head": "tp/demo", "head_sha": self.pr_head,
                          "state": "OPEN", "url": "u"})

    def comment_list(self, repo, number, **kw):
        self._note("list", kw)
        return Result.ok({"comments": list(self.comments)})

    def comment_edit(self, repo, comment_id, body, **kw):
        self._note("edit", kw)
        return Result.ok({})

    def comment_post(self, repo, number, body, **kw):
        self._note("post", kw)
        return Result.ok({"id": 101, "url": "https://example.invalid/101"})


class RunSpy:
    """Stands in for `subprocess.run`: real for git, recorded and faked for anything else."""

    def __init__(self):
        self.git_verbs: list = []
        self.other: list = []

    def __call__(self, argv, *args, **kw):
        if argv and argv[0] == "git":
            self.git_verbs.append(argv[1] if len(argv) > 1 else "")
            return _REAL_RUN(argv, *args, **kw)
        self.other.append((list(argv), kw.get("env")))
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")


def _deliver(repo, fake, *, kind="pr-brief", context="manual"):
    return explain_deliver.post_or_edit(repo, SLUG, 7, _body(kind), kind=kind,
                                        context=context, forge_mod=fake)


# ----------------------------------------------------------------- refresh_needed

def test_refresh_is_needed_when_the_pr_head_differs_from_the_marker_head(repo):
    explain_state.delivery(repo, SLUG, "pr-brief", update={"posted_head": STORED_HEAD})
    fake = FakeForge(pr_head="def456")
    assert explain_deliver.refresh_needed(repo, SLUG, 7, forge_mod=fake) is True
    assert fake.calls == ["pr_read"]


def test_refresh_is_not_needed_when_the_heads_are_equal(repo):
    explain_state.delivery(repo, SLUG, "pr-brief", update={"posted_head": STORED_HEAD})
    assert explain_deliver.refresh_needed(
        repo, SLUG, 7, forge_mod=FakeForge(pr_head=STORED_HEAD)) is False


def test_refresh_is_needed_when_no_brief_was_ever_posted(repo):
    fake = FakeForge(pr_head=STORED_HEAD)
    assert explain_deliver.refresh_needed(repo, SLUG, 7, forge_mod=fake) is True
    assert fake.calls == []  # nothing stored, so nothing to compare and no forge call


def test_refresh_reads_only_the_brief_kind_entry(repo):
    explain_state.delivery(repo, SLUG, "rulings", update={"posted_head": STORED_HEAD})
    explain_state.delivery(repo, SLUG, "pr-brief", update={"posted_head": "old999"})
    assert explain_deliver.refresh_needed(
        repo, SLUG, 7, forge_mod=FakeForge(pr_head=STORED_HEAD)) is True


def test_refresh_with_an_unreadable_pr_prints_one_line_and_counts_as_stale(repo, capsys):
    explain_state.delivery(repo, SLUG, "pr-brief", update={"posted_head": STORED_HEAD})
    fake = FakeForge(fail={"pr_read"})
    assert explain_deliver.refresh_needed(repo, SLUG, 7, forge_mod=fake) is True
    err = _lines(capsys.readouterr().err)
    assert len(err) == 1 and _LINE.match(err[0]).group("reason") == "pr read refused"
    assert _entry(repo)["degraded"] == ["pr read refused"]


# ----------------------------------------------- the forge owns the write identity

def test_the_forge_calls_carry_no_runner(repo):
    fake = FakeForge()
    assert _deliver(repo, fake).status == "ok"
    assert fake.runners == {"list": None, "post": None}
    assert all("runner" not in kw for kw in fake.kwargs)


def test_an_unavailable_bot_prints_one_line_and_posts_nothing(repo, capsys):
    error = automation_identity.BotAuthUnavailable("account ci-bot is not logged in")
    brief = explain_deliver.write_brief(repo, SLUG, _env(), evidence_head="abc123")
    fake = FakeForge(bot_error=error)
    result = _deliver(repo, fake)
    captured = capsys.readouterr()
    assert result.status == "degraded" and fake.calls == ["list"]
    assert captured.out == ""
    lines = _lines(captured.err)
    assert len(lines) == 1
    parts = _LINE.match(lines[0])
    assert parts and Path(parts.group("path")) == brief
    assert _entry(repo)["degraded"] == [parts.group("reason")]
    assert _entry(repo).get("comment_id") is None  # nothing was posted, so nothing stored


# ------------------------------------------------------------------ forge degrade

class GiteaNoToken:
    """The real forge dispatch for a Gitea host with no token (the no-REST-path case)."""

    def __getattr__(self, op):
        fn = getattr(forge, op)
        info = forge.ForgeInfo("gitea", "gitea.lan", "o", "r", "https://gitea.lan",
                               "https://gitea.lan/api/v1", "")
        return lambda *a, **kw: fn(*a, info=info, env={}, **kw)


def test_a_gitea_forge_without_a_token_prints_one_line_and_keeps_brief_md(
        repo, monkeypatch, capsys):
    monkeypatch.setattr(forge_gitea, "read_tea_logins", lambda *a, **kw: [])
    brief = explain_deliver.write_brief(repo, SLUG, _env(), evidence_head="abc123")
    result = explain_deliver.post_or_edit(repo, SLUG, 7, _body(), kind="pr-brief",
                                          context="manual", forge_mod=GiteaNoToken())
    assert result.status == "degraded"
    line = explain_deliver.degrade_line(repo, SLUG, "pr-brief", result.line)
    captured = capsys.readouterr()
    assert captured.out == "" and _lines(captured.err) == [line]
    parts = _LINE.match(line)
    assert parts and parts.group("reason") == result.line
    assert Path(parts.group("path")) == brief and brief.is_file()
    assert _entry(repo)["degraded"] == [result.line]


def test_the_same_reason_is_recorded_once_and_the_line_is_always_one_line(repo, capsys):
    explain_deliver.degrade_line(repo, SLUG, "pr-brief", "post refused")
    line = explain_deliver.degrade_line(repo, SLUG, "pr-brief", "post refused")
    explain_deliver.degrade_line(repo, SLUG, "pr-brief", "first\nsecond")
    assert _entry(repo)["degraded"] == ["post refused", "first second"]
    printed = _lines(capsys.readouterr().err)
    assert len(printed) == 3 and all(_LINE.match(ln) for ln in printed) and printed[1] == line


def test_a_rulings_degrade_points_at_its_html_page_when_one_is_stored(repo, tmp_path, capsys):
    page = str(tmp_path / "rulings.html")
    explain_state.delivery(repo, SLUG, "rulings", update={"html": page})
    explain_deliver.degrade_line(repo, SLUG, "rulings", "post refused")
    parts = _LINE.match(_lines(capsys.readouterr().err)[0])
    assert parts.group("path") == page
    assert _entry(repo, "pr-brief") == {}  # recorded under its own kind only


def test_degrade_line_refuses_an_unknown_kind_and_prints_nothing(repo, capsys):
    with pytest.raises(ValueError):
        explain_deliver.degrade_line(repo, SLUG, "digest", "x")
    assert capsys.readouterr().err == ""


# ------------------------------------------------------------- a refresh never commits

def test_a_refresh_edits_the_comment_and_runs_no_commit(repo, monkeypatch):
    explain_deliver.write_brief(repo, SLUG, _env(), evidence_head=STORED_HEAD)
    explain_state.delivery(repo, SLUG, "pr-brief",
                           update={"comment_id": 55, "posted_head": STORED_HEAD})
    head_before = _git(repo, "rev-parse", "HEAD")
    fake = FakeForge(pr_head="def456", comments=[{"id": 55, "body": _body(head=STORED_HEAD)}])
    spy = RunSpy()
    monkeypatch.setattr(subprocess, "run", spy)
    assert explain_deliver.refresh_needed(repo, SLUG, 7, forge_mod=fake) is True
    explain_deliver.write_brief(repo, SLUG, _env(), evidence_head="def456")
    result = _deliver(repo, fake)
    monkeypatch.undo()
    assert result.status == "ok" and fake.calls == ["pr_read", "edit"]
    assert not set(spy.git_verbs) & {"commit", "add", "push", "stash", "reset"}
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert _git(repo, "diff", "--cached", "--name-only") == ""
    assert _entry(repo)["posted_head"] == "new111"
