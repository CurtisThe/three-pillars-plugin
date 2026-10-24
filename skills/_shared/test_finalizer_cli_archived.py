"""Tests for finalizer_cli on an archived run -- the finalizer writes to completed-tp-designs/.

design: seat-escalate-first (Task 2.3). After the Tier 5.6 archive the run's
``tp-designs/<slug>/`` is gone, yet the run still passes its usual
``tp-designs/<slug>/...`` paths. ``prepare`` / ``apply`` / ``escalate`` must write under
``completed-tp-designs/<slug>/`` instead of recreating ``tp-designs/<slug>/``, and the
ruling's card must pass the escalate-first hook (B8). Every fixture is a tmp git repo;
no network, no real environment.
Run with: python3 -m pytest skills/_shared/test_finalizer_cli_archived.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import escalate_first_hook as hook  # noqa: E402
import finalizer_cli as cli  # noqa: E402
import finalizer_cli_ruling as fcr  # noqa: E402
import finalizer_ruling as fr  # noqa: E402
import ruling_cli  # noqa: E402

LIVE = "three-pillars-docs/tp-designs/demo"
ARCHIVED = "three-pillars-docs/completed-tp-designs/demo"
QUESTION = {"source": "question", "signal": "decision", "target": "demo",
            "detail": {"question": "Which rung owns the retry?"}}
VISION = "# Vision\n\n## Fleet operation\nA run reaches a reviewable PR unattended.\n"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def archived_repo(tmp_path, monkeypatch):
    """A tmp git repo on ``tp/demo`` holding ONLY the archived design (Tier 7) and vision.md."""
    repo = tmp_path / "repo"
    (repo / ARCHIVED).mkdir(parents=True)
    _git(repo, "init", "-b", "tp/demo", "-q")
    lock = {"owner": "orchestrator:x", "phase": "tier-7"}
    (repo / ARCHIVED / "lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (repo / ARCHIVED / "design.md").write_text("# demo\n", encoding="utf-8")
    (repo / ARCHIVED / "decisions.md").write_text("# decisions\n", encoding="utf-8")
    (repo / "three-pillars-docs" / "vision.md").write_text(VISION, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=fixture@test", "-c", "user.name=fixture",
         "commit", "-q", "-m", "fixture: archived demo")
    monkeypatch.chdir(repo)
    return repo


def run(capsys, *argv):
    rc = cli.main([str(a) for a in argv], resolve_fn=lambda a: f"three-pillars:{a}", now=1.8e9)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return rc, json.loads(lines[-1])


def escalate_reply(tmp_path):
    body = {"outcome": "escalate", "actions": [], "diagnosis": "the docs do not settle it",
            "reasoning": "r (vision.md)", "demoted": [], "blocked": [], **fr.EMPTY_RULING}
    path = tmp_path / "reply.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def assert_card_passes_hook(capsys, repo, rid):
    """B8: the ruling's card, sent as an AskUserQuestion, is allowed in the archived run."""
    assert ruling_cli.main(["card", "--id", rid]) == 0
    card = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert card["question"].startswith(QUESTION["detail"]["question"])
    payload = {"tool_name": "AskUserQuestion", "cwd": str(repo),
               "tool_input": {"questions": [{**card, "header": "Retry"}]}}
    assert hook.run(payload, env={"TP_DESIGN_RUN": "1"}) == ("", 0)


def assert_archived_only(repo):
    assert not (repo / LIVE).exists(), "tp-designs/demo was recreated after the archive"


def test_prepare_then_apply_write_under_completed(capsys, tmp_path, monkeypatch):
    repo = archived_repo(tmp_path, monkeypatch)
    ledger, decisions = f"{LIVE}/finalizer-ledger.json", f"{LIVE}/decisions.md"
    rc, out = run(capsys, "prepare", "--stop", json.dumps(QUESTION), "--ledger", ledger,
                  "--decisions", decisions, "--entry", "run")
    assert (rc, out["status"]) == (0, "dispatch")
    assert_archived_only(repo)
    assert (repo / ARCHIVED / "finalizer-ledger.json").is_file()
    assert f"{ARCHIVED}/decisions.md" in out["brief"]
    assert not re.search(r"(?<!completed-)tp-designs/demo", out["brief"])
    rc, out = run(capsys, "apply", "--stop", json.dumps(QUESTION), "--ledger", ledger,
                  "--reply", escalate_reply(tmp_path), "--decisions", decisions, "--entry", "run")
    assert (rc, out["outcome"]) == (0, "escalate")
    assert_archived_only(repo)
    entry = (repo / ARCHIVED / "decisions.md").read_text(encoding="utf-8")
    assert f"- **Ruling**: {out['ruling_id']}" in entry
    assert_card_passes_hook(capsys, repo, out["ruling_id"])


def test_escalate_writes_under_completed(capsys, tmp_path, monkeypatch):
    repo = archived_repo(tmp_path, monkeypatch)
    rc, out = run(capsys, "escalate", "--stop", json.dumps(QUESTION), "--decisions",
                  f"{LIVE}/decisions.md", "--reason", "nested", "--entry", "run")
    assert (rc, out["outcome"]) == (0, "escalate")
    assert_archived_only(repo)
    entry = (repo / ARCHIVED / "decisions.md").read_text(encoding="utf-8")
    assert f"- **Ruling**: {out['ruling_id']}" in entry
    assert_card_passes_hook(capsys, repo, out["ruling_id"])


def test_archived_path_rewrites_only_an_archived_design(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    live, archived = "three-pillars-docs/tp-designs/demo/x.json", "three-pillars-docs/completed-tp-designs/demo/x.json"
    assert fcr.archived_path(live) == live  # neither directory exists
    (tmp_path / ARCHIVED).mkdir(parents=True)
    assert fcr.archived_path(live) == archived  # in-flight absent, archived present
    assert fcr.archived_path(str(tmp_path / live)) == str(tmp_path / archived)
    (tmp_path / LIVE).mkdir(parents=True)
    assert fcr.archived_path(live) == live  # the run is still in flight
    assert fcr.archived_path(archived) == archived  # already an archived path
    assert fcr.archived_path("decisions.md") == "decisions.md"  # not a design path
    assert fcr.archived_path(None) is None
