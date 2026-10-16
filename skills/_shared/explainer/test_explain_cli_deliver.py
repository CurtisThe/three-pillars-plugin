"""test_explain_cli_deliver.py — the CLI's delivery subcommands and the fail-open degrade line.

Covers explainer-agent plan Task 9.2 (detailed-design §Interfaces, the CLI bullet: `brief`,
`headline` (the byte-identical off switch), `post` with the optional `--envelope` refresh
form, `refresh-needed` (exit 0 when stale, 1 when current), `ruling-append`, `rulings-sync`,
`rulings-fold`, `record-artifact`; every forge degrade prints one `explainer: <reason> — see
<path>` line), plus the head-vs-sha fix: `pr_read` carries the PR head commit as `head_sha`
beside `head`, the branch name. A fake forge is injected as `explain_cli_deliver.FORGE`; every
call passes `--root <tmp git repo>` as in Task 9.1. Assertions read parsed values, never
pinned markup (skills/_shared/test-fragility.md).
"""
import io
import json
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

import explain_card  # noqa: E402
import explain_cli  # noqa: E402
import explain_deliver  # noqa: E402
import explain_envelope  # noqa: E402
import explain_sources  # noqa: E402
import explain_state  # noqa: E402
import explainer_marker  # noqa: E402
import forge_gitea  # noqa: E402
import forge_github  # noqa: E402
from forge import ForgeInfo, Result  # noqa: E402
from task_scope import _git_env  # noqa: E402 — git_env is dev-only

SLUG = "demo"
PR = 7
POSTED_SHA = "abc123"
SHA = "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"
_ENV = _git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
_LINE = re.compile(r"^explainer: (?P<reason>.+) — see (?P<path>.+)$")
_GH_INFO = ForgeInfo("github", "github.com", "octo", "repo", "https://github.com",
                     "https://api.github.com", "")
_GITEA_INFO = ForgeInfo("gitea", "gitea.lan", "home", "lab", "https://gitea.lan",
                        "https://gitea.lan/api/v1", "")


def _git(cwd, *args) -> str:
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                          *args], cwd=str(cwd), env=_ENV, check=True, capture_output=True,
                         text=True)
    return out.stdout.strip()


def write_json(path, data) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _envelope(kind, summary, label):
    """A validate-clean envelope: every required section, one cited item each."""
    sections = [{"id": sid, "title": f"Title {sid}",
                 "items": [{"text": f"{label} {sid} item.", "refs": ["diffstat"]}]}
                for sid in explain_envelope.REQUIRED_SECTIONS[kind]]
    env = {"schema": explain_envelope.SCHEMA, "kind": kind,
           "ste_summary": {"text": summary, "refs": ["diffstat"]},
           "sections": sections, "diagram_specs": [],
           "confidence_note": {"text": "The evidence is the diff.", "refs": ["diffstat"]}}
    assert explain_envelope.validate_envelope(env, kind) == []
    return env


def _brief_env(summary="The change adds an explainer brief to each PR.") -> dict:
    return _envelope("pr-brief", summary, "Brief")


@pytest.fixture
def repo(tmp_path) -> Path:
    """A tmp git repo with one commit; every CLI call below passes it as `--root`."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    return root


@pytest.fixture
def envelope_file(tmp_path):
    return write_json(tmp_path / "envelope.json", _brief_env())


@pytest.fixture
def ruling_file(tmp_path):
    return write_json(tmp_path / "ruling.json", _envelope("auto-ruling", "Fable chose 1.", "R"))


@pytest.fixture
def inject_forge(monkeypatch):
    """Install a fake forge module as the CLI's forge; return it."""
    import explain_cli_deliver  # lazy: a missing module fails the tests, not the collection

    def inject(**kw) -> "FakeForge":
        fake = FakeForge(**kw)
        monkeypatch.setattr(explain_cli_deliver, "FORGE", fake)
        return fake
    return inject


class FakeForge:
    """A forge module stand-in. `pr_read` answers the real payload shape: `head` is the
    branch name and `head_sha` the commit the brief was posted at."""

    def __init__(self, *, pr_head_sha=POSTED_SHA, fail=()):
        self.pr_head_sha = pr_head_sha
        self.fail = set(fail)
        self.calls: list = []  # (op, ...) of every call
        self.posts: list = []  # (id, body) of every accepted comment_post
        self.comments: dict = {}  # id -> body

    def _calls(self, op):
        return [c for c in self.calls if c[0] == op]

    def _refused(self, op, *detail):
        self.calls.append((op, *detail))
        return Result.degraded(f"{op} refused") if op in self.fail else None

    def pr_read(self, root, number, **_kw):
        bad = self._refused("pr_read", number)
        return bad or Result.ok({"number": number, "head": "tp/demo", "state": "OPEN",
                                 "head_sha": self.pr_head_sha, "url": "https://x.invalid/7"})

    def comment_list(self, root, number, **_kw):
        return self._refused("list") or Result.ok(
            {"comments": [{"id": i, "body": b} for i, b in self.comments.items()]})

    def comment_edit(self, root, comment_id, body, **_kw):
        bad = self._refused("edit", comment_id, body)
        if bad is None:
            self.comments[comment_id] = body
        return bad or Result.ok({})

    def comment_post(self, root, number, body, **_kw):
        bad = self._refused("post")
        if bad is None:
            cid = 100 + len(self.posts) + 1
            self.posts.append((cid, body))
            self.comments[cid] = body
        return bad or Result.ok({"id": cid, "url": f"https://x.invalid/c{cid}"})


def run(capsys, root, *argv):
    """`main(--root <root> argv)` -> (exit code, stdout, stderr)."""
    code = explain_cli.main(["--root", str(root), *[str(a) for a in argv]])
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def json_line(stdout) -> dict:
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one JSON line, got {stdout!r}"
    return json.loads(lines[0])


def err_lines(stderr) -> list:
    return [ln for ln in stderr.splitlines() if ln.strip()]


def design(root, tree="tp-designs") -> Path:
    """The design dir for SLUG in `tree`, created; where the rulings ledger lives."""
    path = root / "three-pillars-docs" / tree / SLUG
    path.mkdir(parents=True)
    (path / "design.md").write_text("# demo\n", encoding="utf-8")
    return path


def brief_path(root) -> Path:
    return root / "three-pillars-docs" / "tp-designs" / SLUG / "brief.md"


def state_text(root, name) -> str:
    return (explain_state.state_root(root) / SLUG / name).read_text(encoding="utf-8")


def entry(root, kind="pr-brief") -> dict:
    return explain_state.delivery(root, SLUG, kind)


def ledger_ids(path) -> list:
    return [row["id"] for row in explain_sources.ledger_rows(path.read_text(encoding="utf-8"))]


def make_brief(capsys, root, envelope_file):
    return run(capsys, root, "brief", "--slug", SLUG, "--envelope", envelope_file,
               "--head", POSTED_SHA)


# ------------------------------------------------------------------------ brief

def test_brief_writes_brief_md_the_html_and_the_envelope(capsys, repo, envelope_file):
    code, out, err = make_brief(capsys, repo, envelope_file)
    assert (code, err) == (0, "")
    assert json_line(out) == {"brief": str(brief_path(repo))}
    assert explainer_marker.parse(brief_path(repo).read_text(encoding="utf-8")) == \
        {"kind": "pr-brief", "slug": SLUG, "head": POSTED_SHA}
    assert POSTED_SHA in state_text(repo, "pr-brief.html")
    assert json.loads(state_text(repo, "pr-brief.envelope.json")) == _brief_env()
    assert entry(repo)["html"] == str(explain_state.state_root(repo) / SLUG / "pr-brief.html")


# --------------------------------------------------------------------- headline

def test_headline_prints_one_line_ending_with_the_brief_path(capsys, repo, envelope_file):
    make_brief(capsys, repo, envelope_file)
    code, out, err = run(capsys, repo, "headline", "--slug", SLUG)
    assert (code, err) == (0, "")
    assert out.splitlines() == [explain_card.headline(_brief_env(), str(brief_path(repo)))]


def test_headline_prints_nothing_when_the_explainer_is_off(capsys, repo, envelope_file):
    """The byte-identical off switch: an empty headline leaves the PR body unchanged."""
    write_json(repo / ".three-pillars" / "config.json", {"explainer": {"enabled": False}})
    make_brief(capsys, repo, envelope_file)
    code, out, err = run(capsys, repo, "headline", "--slug", SLUG)
    assert (code, out, err) == (0, "", "")
    rest = "\n\n## What is merging\n\nThe brief explains the change.\n"
    assert out + rest == rest


# ----------------------------------------------------------------------- post

def test_post_posts_the_stored_envelope_and_records_the_comment(capsys, repo, inject_forge,
                                                                envelope_file):
    fake = inject_forge()
    make_brief(capsys, repo, envelope_file)
    code, out, err = run(capsys, repo, "post", "--slug", SLUG, "--pr", PR, "--kind", "pr-brief")
    assert (code, err) == (0, "")
    assert json_line(out) == {"posted": True, "comment_id": entry(repo)["comment_id"]}
    assert explainer_marker.parse(fake.posts[0][1]) == \
        {"kind": "pr-brief", "slug": SLUG, "head": POSTED_SHA}
    assert entry(repo)["posted_head"] == POSTED_SHA
    assert fake._calls("edit") == []


def test_post_with_an_envelope_refreshes_in_place_and_commits_nothing(
        capsys, repo, inject_forge, envelope_file, tmp_path):
    fake = inject_forge()
    make_brief(capsys, repo, envelope_file)
    run(capsys, repo, "post", "--slug", SLUG, "--pr", PR, "--kind", "pr-brief")
    posted = fake.posts[0][1]
    brief_before = brief_path(repo).read_text(encoding="utf-8")
    head_before = _git(repo, "rev-parse", "HEAD")
    summary = "The brief now covers the review fixes."
    refreshed = write_json(tmp_path / "refreshed.json", _brief_env(summary))
    code, out, err = run(capsys, repo, "post", "--slug", SLUG, "--pr", PR, "--kind", "pr-brief",
                         "--envelope", refreshed)
    assert (code, err) == (0, "")
    assert json_line(out)["posted"] is True
    edits = fake._calls("edit")
    assert len(fake.posts) == 1 and len(edits) == 1  # edited in place, no second comment
    assert edits[0][1] == entry(repo)["comment_id"]
    assert edits[0][2] != posted and summary in edits[0][2]
    assert json.loads(state_text(repo, "pr-brief.envelope.json")) == _brief_env(summary)
    assert summary in state_text(repo, "pr-brief.html")
    assert brief_path(repo).read_text(encoding="utf-8") == brief_before
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_post_with_kind_rulings_posts_the_ledger_comment(capsys, repo, inject_forge,
                                                         ruling_file):
    fake = inject_forge()
    design(repo)
    run(capsys, repo, "ruling-append", "--slug", SLUG, "--envelope", ruling_file)
    code, out, err = run(capsys, repo, "post", "--slug", SLUG, "--pr", PR, "--kind", "rulings")
    assert (code, err) == (0, "")
    assert json_line(out)["posted"] is True
    parsed = explainer_marker.parse(fake.posts[0][1])
    assert (parsed["kind"], parsed["slug"]) == ("rulings", SLUG)
    assert entry(repo, "rulings")["comment_id"] == fake.posts[0][0]
    assert entry(repo) == {}  # the brief kind keeps its own comment id


# ------------------------------------------------------------- refresh-needed

def test_refresh_needed_exits_0_when_the_pr_head_sha_moved(capsys, repo, inject_forge):
    inject_forge(pr_head_sha="dee1111")
    explain_state.delivery(repo, SLUG, "pr-brief", update={"posted_head": SHA})
    code, out, err = run(capsys, repo, "refresh-needed", "--slug", SLUG, "--pr", PR)
    assert (code, err) == (0, "")
    assert json_line(out) == {"stale": True}


def test_refresh_needed_exits_1_when_the_pr_head_sha_is_the_posted_head(
        capsys, repo, inject_forge):
    """A real `pr_read` payload: `head` is the branch name, `head_sha` the posted commit."""
    inject_forge(pr_head_sha=SHA)
    explain_state.delivery(repo, SLUG, "pr-brief", update={"posted_head": SHA})
    code, out, err = run(capsys, repo, "refresh-needed", "--slug", SLUG, "--pr", PR)
    assert (code, err) == (1, "")
    assert json_line(out) == {"stale": False}


def test_refresh_needed_compares_the_sha_not_the_branch_name(repo):
    explain_state.delivery(repo, SLUG, "pr-brief", update={"posted_head": SHA})
    fake = FakeForge(pr_head_sha=SHA)
    assert fake.pr_read(repo, PR).payload["head"] == "tp/demo"
    assert explain_deliver.refresh_needed(repo, SLUG, PR, forge_mod=fake) is False


# --------------------------------------------------------- the forges' head sha

def test_github_pr_read_reports_the_head_sha_beside_the_branch_name():
    gh_json = ('{"number": 7, "headRefName": "tp/demo", "state": "OPEN",'
               f' "headRefOid": "{SHA}", "url": "https://github.com/octo/repo/pull/7"}}')

    def gh(argv, **_kw):
        return subprocess.CompletedProcess(argv, 0, stdout=gh_json, stderr="")

    res = forge_github.pr_read(_GH_INFO, 7, runner=gh)
    assert res.status == "ok"
    assert (res.payload["head"], res.payload["head_sha"]) == ("tp/demo", SHA)


def test_gitea_pr_read_reports_the_head_sha_beside_the_branch_name():
    payload = {"number": 7, "state": "open", "merged": False,
               "html_url": "https://gitea.lan/home/lab/pulls/7",
               "head": {"ref": "tp/demo", "sha": SHA}, "base": {"ref": "master"}}

    def api(request, timeout=None, context=None):
        return io.BytesIO(json.dumps(payload).encode())

    res = forge_gitea.pr_read(_GITEA_INFO, 7, token="t2", urlopen=api)
    assert res.status == "ok"
    assert (res.payload["head"], res.payload["head_sha"]) == ("tp/demo", SHA)


# --------------------------------------------------------- the rulings ledger

def test_ruling_append_prints_the_id_and_writes_the_ledger(capsys, repo, ruling_file):
    live = design(repo)
    code, out, err = run(capsys, repo, "ruling-append", "--slug", SLUG, "--envelope", ruling_file)
    assert (code, err) == (0, "")
    assert json_line(out) == {"ruling": "r1"}
    assert ledger_ids(live / explain_sources.LEDGER_FILE) == ["r1"]
    assert "Ruling r1" in (live / "decisions.md").read_text(encoding="utf-8")


def test_rulings_sync_is_a_noop_on_an_empty_ledger_then_posts(capsys, repo, inject_forge,
                                                              ruling_file):
    fake = inject_forge()
    design(repo)
    code, out, err = run(capsys, repo, "rulings-sync", "--slug", SLUG, "--pr", PR)
    assert (code, err) == (0, "")
    assert json_line(out) == {"rulings": 0, "posted": False}
    assert fake.calls == [] and entry(repo, "rulings") == {}
    run(capsys, repo, "ruling-append", "--slug", SLUG, "--envelope", ruling_file)
    code, out, err = run(capsys, repo, "rulings-sync", "--slug", SLUG, "--pr", PR)
    assert (code, err) == (0, "")
    assert json_line(out) == {"rulings": 1, "posted": True, "comment_id": fake.posts[0][0]}
    parsed = explainer_marker.parse(fake.posts[0][1])
    assert (parsed["kind"], parsed["slug"]) == ("rulings", SLUG)


def test_rulings_fold_moves_the_late_rows_into_the_archived_ledger(capsys, repo, ruling_file):
    archived = design(repo, tree="completed-tp-designs")
    run(capsys, repo, "ruling-append", "--slug", SLUG, "--envelope", ruling_file)
    late = explain_state.state_root(repo) / SLUG / "rulings-late.ndjson"
    assert ledger_ids(late) == ["r1"]
    code, out, err = run(capsys, repo, "rulings-fold", "--slug", SLUG)
    assert (code, err) == (0, "")
    assert json_line(out) == {"folded": 1}
    assert ledger_ids(archived / explain_sources.LEDGER_FILE) == ["r1"]
    assert late.read_text(encoding="utf-8") == ""


# ----------------------------------------------------------- record-artifact

def test_record_artifact_stores_the_url_under_its_kind(capsys, repo):
    url = "https://example.invalid/artifact"
    code, out, err = run(capsys, repo, "record-artifact", "--slug", SLUG, "--kind", "pr-brief",
                         "--url", url)
    assert (code, err) == (0, "")
    assert json_line(out) == {"artifact_url": url}
    assert entry(repo)["artifact_url"] == url
    assert entry(repo, "rulings") == {}


# ------------------------------------------------------- the degrade line

def test_a_degraded_post_prints_one_line_and_exits_0(capsys, repo, inject_forge, envelope_file):
    inject_forge(fail={"post"})
    make_brief(capsys, repo, envelope_file)
    code, out, err = run(capsys, repo, "post", "--slug", SLUG, "--pr", PR, "--kind", "pr-brief")
    assert code == 0
    assert json_line(out) == {"posted": False, "comment_id": None}
    lines = err_lines(err)
    assert len(lines) == 1
    parts = _LINE.match(lines[0])
    assert parts and parts.group("reason") == "post refused"
    assert Path(parts.group("path")) == brief_path(repo)
    assert entry(repo)["degraded"] == ["post refused"]


def test_a_degraded_rulings_sync_prints_one_line_and_exits_0(capsys, repo, inject_forge,
                                                             ruling_file):
    inject_forge(fail={"post"})
    design(repo)
    run(capsys, repo, "ruling-append", "--slug", SLUG, "--envelope", ruling_file)
    code, out, err = run(capsys, repo, "rulings-sync", "--slug", SLUG, "--pr", PR)
    assert code == 0
    assert json_line(out)["posted"] is False
    lines = err_lines(err)
    assert len(lines) == 1 and _LINE.match(lines[0]).group("reason") == "post refused"
    assert entry(repo, "rulings")["degraded"] == ["post refused"]


def test_a_degraded_pr_read_prints_one_line_and_counts_as_stale(capsys, repo, inject_forge):
    inject_forge(fail={"pr_read"})
    explain_state.delivery(repo, SLUG, "pr-brief", update={"posted_head": SHA})
    code, out, err = run(capsys, repo, "refresh-needed", "--slug", SLUG, "--pr", PR)
    assert code == 0
    assert json_line(out) == {"stale": True}
    lines = err_lines(err)
    assert len(lines) == 1 and _LINE.match(lines[0]).group("reason") == "pr_read refused"
    assert entry(repo)["degraded"] == ["pr_read refused"]
