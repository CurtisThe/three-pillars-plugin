"""test_explain_cli_deliver_archive.py — the brief after the archive, and the delivery degrade.

Covers explainer-agent plan Task 11.1 (finding F1): once `/tp-design-complete` runs
`git mv tp-designs/<slug> completed-tp-designs/<slug>`, `post` and `headline` still find
`brief.md` (now under `completed-tp-designs/<slug>/`) and point at that path; and a
`CliError` / `ValueError` on any delivery subcommand is one `explainer: <reason> — see <path>`
stderr line, nothing on stdout, exit 0, while a pipeline subcommand keeps exit 2 and the JSON
error. The tmp git repo and the fake forge are small copies of the helpers in
`test_explain_cli_deliver.py` (that module is not imported). Assertions read parsed values,
never pinned markup (skills/_shared/test-fragility.md).
"""
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

import explain_cli  # noqa: E402
import explain_deliver  # noqa: E402
import explain_envelope  # noqa: E402
from forge import Result  # noqa: E402
from task_scope import _git_env  # noqa: E402 — git_env is dev-only

SLUG = "demo"
PR = 7
HEAD = "abc123"
DOCS = "three-pillars-docs"
_ENV = _git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
_LINE = re.compile(r"^explainer: .+ — see .+$")


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


def _envelope(kind, summary) -> dict:
    """A validate-clean envelope: every required section, one cited item each."""
    sections = [{"id": sid, "title": f"Title {sid}",
                 "items": [{"text": f"Item for {sid}.", "refs": ["diffstat"]}]}
                for sid in explain_envelope.REQUIRED_SECTIONS[kind]]
    env = {"schema": explain_envelope.SCHEMA, "kind": kind,
           "ste_summary": {"text": summary, "refs": ["diffstat"]},
           "sections": sections, "diagram_specs": [],
           "confidence_note": {"text": "The evidence is the diff.", "refs": ["diffstat"]}}
    assert explain_envelope.validate_envelope(env, kind) == []
    return env


class FakeForge:
    """A forge module stand-in: every posted comment body is kept in `posts`."""

    def __init__(self):
        self.posts: list = []  # (id, body) of every comment_post

    def pr_read(self, root, number, **_kw):
        return Result.ok({"number": number, "head": "tp/demo", "state": "OPEN",
                          "head_sha": HEAD, "url": "https://x.invalid/7"})

    def comment_list(self, root, number, **_kw):
        return Result.ok({"comments": [{"id": i, "body": b} for i, b in self.posts]})

    def comment_edit(self, root, comment_id, body, **_kw):
        return Result.ok({})

    def comment_post(self, root, number, body, **_kw):
        cid = 100 + len(self.posts) + 1
        self.posts.append((cid, body))
        return Result.ok({"id": cid, "url": f"https://x.invalid/c{cid}"})


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
    return write_json(tmp_path / "envelope.json",
                      _envelope("pr-brief", "The change adds an explainer brief to each PR."))


@pytest.fixture
def fake(monkeypatch) -> FakeForge:
    import explain_cli_deliver  # lazy: a missing module fails the tests, not the collection
    forge = FakeForge()
    monkeypatch.setattr(explain_cli_deliver, "FORGE", forge)
    return forge


def run(capsys, root, *argv):
    """`main(--root <root> argv)` -> (exit code, stdout, stderr)."""
    code = explain_cli.main(["--root", str(root), *[str(a) for a in argv]])
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def err_lines(stderr) -> list:
    return [ln for ln in stderr.splitlines() if ln.strip()]


def design(root, tree="tp-designs") -> Path:
    path = root / DOCS / tree / SLUG
    path.mkdir(parents=True)
    (path / "design.md").write_text("# demo\n", encoding="utf-8")
    return path


def live_brief(root) -> Path:
    return root / DOCS / "tp-designs" / SLUG / "brief.md"


def archived_brief(root) -> Path:
    return root / DOCS / "completed-tp-designs" / SLUG / "brief.md"


@pytest.fixture
def archived(capsys, repo, envelope_file) -> Path:
    """The brief written under `tp-designs`, committed, then archived by `git mv`."""
    design(repo)
    code, _out, _err = run(capsys, repo, "brief", "--slug", SLUG, "--envelope", envelope_file,
                           "--head", HEAD)
    assert code == 0 and live_brief(repo).is_file()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "brief")
    (repo / DOCS / "completed-tp-designs").mkdir(parents=True)
    _git(repo, "mv", f"{DOCS}/tp-designs/{SLUG}", f"{DOCS}/completed-tp-designs/{SLUG}")
    _git(repo, "commit", "-q", "-m", "archive")
    assert not live_brief(repo).exists() and archived_brief(repo).is_file()
    return archived_brief(repo)


# ------------------------------------------------------- brief_path after the archive

def test_brief_path_finds_the_archived_brief(archived, repo):
    assert explain_deliver.brief_path(repo, SLUG) == archived


def test_brief_path_falls_back_to_the_live_path_with_no_design_dir(repo):
    assert explain_deliver.brief_path(repo, SLUG) == live_brief(repo)


def test_brief_path_prefers_the_live_design_dir(repo):
    design(repo)
    design(repo, tree="completed-tp-designs")
    assert explain_deliver.brief_path(repo, SLUG) == live_brief(repo)


# ------------------------------------------------------- post and headline

def test_post_after_the_archive_sends_the_archived_brief_text(capsys, repo, fake, archived):
    code, out, err = run(capsys, repo, "post", "--slug", SLUG, "--pr", PR)
    assert (code, err) == (0, "")
    assert json.loads(out)["posted"] is True
    assert [body for _cid, body in fake.posts] == [archived.read_text(encoding="utf-8")]


def test_headline_after_the_archive_ends_with_the_archived_path(capsys, repo, archived):
    code, out, err = run(capsys, repo, "headline", "--slug", SLUG)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert len(lines) == 1
    assert lines[0].endswith(f"completed-tp-designs/{SLUG}/brief.md")
    assert str(archived) in lines[0]


# ------------------------------------------------------- a delivery error is a degrade line

def _missing_brief(repo, tmp_path):
    design(repo)  # a design dir, no brief.md
    return ("post", "--slug", SLUG, "--pr", PR)


def _missing_envelope(repo, tmp_path):
    design(repo)
    return ("ruling-append", "--slug", SLUG, "--envelope", tmp_path / "missing.json")


@pytest.mark.parametrize("forced", [_missing_brief, _missing_envelope],
                         ids=["post-without-brief", "ruling-append-without-envelope"])
def test_a_delivery_error_is_one_degrade_line_and_exit_0(capsys, repo, fake, tmp_path, forced):
    argv = forced(repo, tmp_path)
    code, out, err = run(capsys, repo, *argv)
    assert code == 0
    assert out == ""
    lines = err_lines(err)
    assert len(lines) == 1 and _LINE.match(lines[0]), err


def test_a_bad_slug_on_a_delivery_subcommand_is_a_degrade_line(capsys, repo, fake,
                                                               envelope_file):
    """Recording the degrade fails on a bad slug; the line still prints and the exit is 0."""
    code, out, err = run(capsys, repo, "brief", "--slug", "../x", "--envelope", envelope_file,
                         "--head", HEAD)
    assert code == 0
    assert out == ""
    lines = err_lines(err)
    assert len(lines) == 1 and _LINE.match(lines[0]), err


def test_a_pipeline_error_still_exits_2_with_the_json_error(capsys, repo, tmp_path):
    code, out, err = run(capsys, repo, "gate", "--request", tmp_path / "no-request.json",
                         "--envelope", tmp_path / "no-envelope.json")
    assert code == 2
    assert "error" in json.loads(out)
