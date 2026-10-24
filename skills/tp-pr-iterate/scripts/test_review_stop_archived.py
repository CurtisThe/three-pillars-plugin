"""Tests for review_stop settle on an archived run -- decisions land under completed-tp-designs/.

design: seat-escalate-first (PR #352 review r1). The review stop fires in Tier 7, after
the Tier 5.6 archive, and the run passes its usual ``tp-designs/<slug>/decisions.md``.
``settle`` re-points ``--decisions`` through ``finalizer_cli_ruling.archived_path`` (the
same helper ``finalizer_cli.main`` uses), so it never recreates ``tp-designs/<slug>/``.
Every fixture is a tmp git repo; no network.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
for _p in (_HERE, _SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import finalizer_ruling  # noqa: E402
import iterate_state  # noqa: E402
import review_stop  # noqa: E402
import ruling_file  # noqa: E402

H = "cd" * 20
URL = "https://github.com/o/r/pull/7"
LIVE = "three-pillars-docs/tp-designs/demo"
ARCHIVED = "three-pillars-docs/completed-tp-designs/demo"
NOTE = {"title": "Tighten docstring", "summary": "loose", "verdict": "minor",
        "file": "src/a.py"}
STOP_OPT = {"id": "stop", "label": "Stop here", "description": "s", "recommended": True}
FIX_OPT = {"id": "fix", "label": "Fix these notes first", "description": "f"}


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path, monkeypatch, *, archived: bool) -> Path:
    repo = tmp_path / "repo"
    design = repo / (ARCHIVED if archived else LIVE)
    design.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "tp/demo")
    (design / "decisions.md").write_text("# decisions\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=f@test", "-c", "user.name=f", "commit", "-q", "-m", "fx")
    monkeypatch.chdir(repo)
    state = iterate_state.fresh_state(now="2026-10-22T00:00:00+00:00")
    state.update(iteration=1, last_codereview_head_sha=H, last_codereview_findings=[NOTE])
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return repo


def _ruling(repo) -> str:
    stop = review_stop.due({}, [NOTE], pr_url=URL, head=H)
    ruling = {**finalizer_ruling.EMPTY_RULING, "options": [dict(STOP_OPT), dict(FIX_OPT)]}
    path = ruling_file.write(repo, scope="demo", entry="run", stop=stop,
                             key=f"question:decision:{URL}",
                             result={"outcome": "resolved", "problems": [], "ruling": ruling},
                             model="fable", at="2026-10-22T00:00:00Z")
    return path.stem


def _cli(tmp_path, rid) -> int:
    return review_stop.main(["settle", "--id", rid, "--state", str(tmp_path / "state.json"),
                             "--decisions", f"{LIVE}/decisions.md"])


def test_cli_settle_on_archived_run_writes_the_archived_decisions(tmp_path, monkeypatch,
                                                                  capsys):
    repo = _repo(tmp_path, monkeypatch, archived=True)
    assert _cli(tmp_path, _ruling(repo)) == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"action": "label"}
    assert not (repo / LIVE).exists()  # nothing recreates the in-flight dir
    log = (repo / ARCHIVED / "decisions.md").read_text(encoding="utf-8")
    assert "[review-stop] follow-up seed notes" in log and NOTE["title"] in log


def test_cli_settle_on_live_run_keeps_the_in_flight_decisions(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, monkeypatch, archived=False)
    assert _cli(tmp_path, _ruling(repo)) == 0
    capsys.readouterr()
    assert not (repo / ARCHIVED).exists()
    log = (repo / LIVE / "decisions.md").read_text(encoding="utf-8")
    assert "[review-stop] follow-up seed notes" in log
