"""test_explain_cli_post_head.py — Task 11.3 (F3): a first `post` stamps `posted_head` with the
PR head commit from `pr_read`, so `refresh-needed` is current right after it.

A fake forge is injected as `explain_cli_deliver.FORGE`. Assertions read parsed values
(skills/_shared/test-fragility.md).
"""
import json
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
import explain_cli_deliver  # noqa: E402
import explain_envelope  # noqa: E402
import explain_state  # noqa: E402
from forge import Result  # noqa: E402
from task_scope import _git_env  # noqa: E402 — git_env is dev-only

SLUG = "demo"
PR = 7
EVIDENCE = "abc123"
PR_SHA = "1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e"
_ENV = _git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


class Fake:
    """`pr_read` answers with `head_sha` (or without it, or degraded)."""

    def __init__(self, head_sha=PR_SHA, degraded=False):
        self.head_sha, self.degraded = head_sha, degraded
        self.comments: dict = {}

    def pr_read(self, root, number, **_kw):
        if self.degraded:
            return Result.degraded("pr_read refused")
        payload = {"number": number, "head": "tp/demo", "state": "OPEN"}
        if self.head_sha:
            payload["head_sha"] = self.head_sha
        return Result.ok(payload)

    def comment_list(self, root, number, **_kw):
        return Result.ok({"comments": [{"id": i, "body": b} for i, b in self.comments.items()]})

    def comment_edit(self, root, comment_id, body, **_kw):
        self.comments[comment_id] = body
        return Result.ok({})

    def comment_post(self, root, number, body, **_kw):
        cid = 100 + len(self.comments) + 1
        self.comments[cid] = body
        return Result.ok({"id": cid, "url": f"https://x.invalid/c{cid}"})


def _env():
    sections = [{"id": sid, "title": f"T {sid}",
                 "items": [{"text": f"{sid} item.", "refs": ["diffstat"]}]}
                for sid in explain_envelope.REQUIRED_SECTIONS["pr-brief"]]
    return {"schema": explain_envelope.SCHEMA, "kind": "pr-brief",
            "ste_summary": {"text": "The change adds a brief.", "refs": ["diffstat"]},
            "sections": sections, "diagram_specs": [],
            "confidence_note": {"text": "The evidence is the diff.", "refs": ["diffstat"]}}


def run(root, *argv):
    return explain_cli.main(["--root", str(root), *[str(a) for a in argv]])


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for argv in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *argv],
                       cwd=str(root), env=_ENV, check=True, capture_output=True)
    env_file = tmp_path / "env.json"
    env_file.write_text(json.dumps(_env()), encoding="utf-8")
    run(root, "brief", "--slug", SLUG, "--envelope", env_file, "--head", EVIDENCE)
    return root


def posted_head(root):
    return explain_state.delivery(root, SLUG, "pr-brief").get("posted_head")


def test_first_post_stamps_the_pr_head_sha_and_refresh_is_current(
        capsys, repo, monkeypatch):
    monkeypatch.setattr(explain_cli_deliver, "FORGE", Fake())
    assert run(repo, "post", "--slug", SLUG, "--pr", PR) == 0
    assert posted_head(repo) == PR_SHA
    capsys.readouterr()
    assert run(repo, "refresh-needed", "--slug", SLUG, "--pr", PR) == 1


def test_no_head_sha_keeps_the_marker_head(capsys, repo, monkeypatch):
    monkeypatch.setattr(explain_cli_deliver, "FORGE", Fake(head_sha=None))
    assert run(repo, "post", "--slug", SLUG, "--pr", PR) == 0
    assert posted_head(repo) == EVIDENCE


def test_degraded_pr_read_still_posts_silently(capsys, repo, monkeypatch):
    monkeypatch.setattr(explain_cli_deliver, "FORGE", Fake(degraded=True))
    capsys.readouterr()
    code = run(repo, "post", "--slug", SLUG, "--pr", PR)
    cap = capsys.readouterr()
    assert code == 0 and cap.err == ""
    assert json.loads(cap.out.strip().splitlines()[-1])["posted"] is True
    assert posted_head(repo) == EVIDENCE


def test_refresh_form_keeps_its_current_stamp(capsys, repo, monkeypatch, tmp_path):
    monkeypatch.setattr(explain_cli_deliver, "FORGE", Fake())
    run(repo, "post", "--slug", SLUG, "--pr", PR)
    env_file = tmp_path / "e2.json"
    env_file.write_text(json.dumps(_env()), encoding="utf-8")
    assert run(repo, "post", "--slug", SLUG, "--pr", PR, "--envelope", env_file) == 0
    local = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), env=_ENV,
                           capture_output=True, text=True).stdout.strip()
    assert posted_head(repo) == local
