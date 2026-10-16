"""test_explain_cli.py — the explainer CLI's pipeline subcommands and exit codes.

Covers explainer-agent plan Task 9.1 (detailed-design §Interfaces, the CLI bullet: one
JSON line out, exit 0 unless noted; `enabled` exits 1 when off, `gate` exits 3 on a fail
and prints `rewrite_prompt`; "the rewrite happens exactly once (a CLI attempt counter)").
`gate` keeps the count in the sidecar `<request>.gate-attempts`; a new `request` run
starts it again. Every call passes the global `--root <tmp git repo>`, so nothing here
writes the real repo's `.git/three-pillars/explainer/`. Requests and envelopes are built
here from the §Interfaces shapes (skills/_shared/test-fragility.md): assertions are on
exit codes and parsed JSON, and no repo docs are read.
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
import explain_gate  # noqa: E402
import explain_offline  # noqa: E402
import explain_state  # noqa: E402
import explainer_marker  # noqa: E402
import local_backend  # noqa: E402
import role_engine  # noqa: E402
from task_scope import _git_env  # noqa: E402 — git_env is dev-only

_ENV = _git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
TELEMETRY_KEYS = {"ts", "slug", "kind", "engine", "served", "gates", "rewrite_used",
                  "check_outcome", "facts_only", "degraded"}


@pytest.fixture
def repo(tmp_path) -> Path:
    """A tmp git repo; every CLI call below passes it as `--root`."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(root), env=_ENV, check=True)
    return root


def run(capsys, root, *argv):
    """`main(--root <root> argv)` -> (exit code, the one JSON line parsed)."""
    code = explain_cli.main(["--root", str(root), *[str(a) for a in argv]])
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 1, f"expected one JSON line, got {out!r}"
    return code, json.loads(out)


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_config(root: Path, config: dict) -> None:
    write_json(root / ".three-pillars" / "config.json", config)


def _item(text, ref, **extra):
    return {"text": text, "refs": [ref], **extra}


def _request():
    return {
        "schema": "explain-request/v1", "kind": "auto-ruling", "slug": "demo",
        "subject": {},
        "evidence": [
            {"ref": "decision:1", "label": "Decision 1", "text": "Disk cache."},
            {"ref": "design:problem", "label": "Problem", "text": "Restarts."},
            {"ref": "diffstat", "label": "Diffstat", "text": "cache.py +40"},
        ],
        "evidence_head": "abc1234",
    }


def _envelope():
    """A valid, cited, lint-clean auto-ruling with one good diagram."""
    return {
        "schema": "explain-envelope/v1", "kind": "auto-ruling",
        "ste_summary": _item("The run picks the second option for the cache.", "decision:1"),
        "sections": [
            {"id": "decided", "title": "Decided",
             "items": [_item("The run keeps the cache on disk.", "decision:1")]},
            {"id": "why", "title": "Why",
             "items": [_item("A disk cache survives a restart.", "design:problem")]},
            {"id": "commits-to", "title": "Commits to",
             "items": [_item("Later work reads the cache from disk.", "diffstat")]},
        ],
        "diagram_specs": [{"kind": "flow", "nodes": ["draft", "gate", "render"],
                           "edges": [["draft", "gate"], ["gate", "render"]]}],
        "confidence_note": _item("The diffstat shows the cache change.", "diffstat"),
    }


def _escalation():
    """A human-escalation envelope with two options; the second is recommended."""
    options = [_item("Memory — fast, but lost on restart.", "design:problem"),
               _item("Disk — survives a restart.", "design:problem", recommended=True)]
    return {
        "schema": "explain-envelope/v1", "kind": "human-escalation",
        "ste_summary": _item("The team must pick a cache store.", "decision:1"),
        "sections": [
            {"id": "question", "title": "Question",
             "items": [_item("Which cache store do we use?", "decision:1")]},
            {"id": "options", "title": "Options", "items": options}],
        "diagram_specs": [],
        "confidence_note": _item("The diffstat shows the cache change.", "diffstat"),
    }


@pytest.fixture
def files(tmp_path):
    """Paths for a gate/finalize run: the request, a good envelope and the out file."""
    return {"request": write_json(tmp_path / "req" / "request.json", _request()),
            "envelope": write_json(tmp_path / "req" / "envelope.json", _envelope()),
            "out": tmp_path / "req" / "final.json"}


def _without_why():
    env = _envelope()
    env["sections"] = [s for s in env["sections"] if s["id"] != "why"]
    return env


# --- enabled

@pytest.mark.parametrize("config, code, enabled", [
    ({}, 0, True),
    ({"explainer": {"enabled": False}}, 1, False),
])
def test_enabled_exit_code_follows_the_config(capsys, repo, config, code, enabled):
    write_config(repo, config)
    got_code, out = run(capsys, repo, "enabled")
    assert (got_code, out["enabled"]) == (code, enabled)


# --- request

@pytest.mark.parametrize("kind, needs_check", [("pr-brief", True), ("auto-ruling", False)])
def test_request_writes_the_request_and_prints_the_summary(
        capsys, repo, tmp_path, kind, needs_check, monkeypatch):
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: False)  # no --local
    subject = write_json(tmp_path / "subject.json", {"question": "Ship the brief now?"})
    out_path = tmp_path / "work" / "request.json"
    code, out = run(capsys, repo, "request", "--kind", kind, "--slug", "s",
                    "--subject", subject, "--out", out_path)
    assert code == 0
    assert out["request"] == str(out_path)
    assert out["drafter"]["engine"] == "sonnet"  # the run's cheap engine, no --local
    assert out["needs_check"] is needs_check
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert (written["schema"], written["kind"], written["slug"]) == \
        ("explain-request/v1", kind, "s")
    assert "subject:question" in [item["ref"] for item in written["evidence"]]


def test_request_drafts_on_strata_under_a_local_run_when_a_backend_answers(
        capsys, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: True)  # --local
    monkeypatch.setattr(local_backend, "available", lambda: True)
    code, out = run(capsys, repo, "request", "--kind", "auto-ruling", "--slug", "s",
                    "--out", tmp_path / "request.json")
    assert code == 0
    assert out["drafter"]["engine"] == "local"


def test_request_with_an_unknown_kind_exits_2(capsys, repo, tmp_path):
    out_path = tmp_path / "request.json"
    code, out = run(capsys, repo, "request", "--kind", "essay", "--slug", "s",
                    "--out", out_path)
    assert code == 2
    assert "error" in out
    assert not out_path.exists()


# --- gate: exit 3 on a fail, and exactly one rewrite

def test_gate_passes_a_good_envelope_with_exit_0(capsys, repo, files):
    code, out = run(capsys, repo, "gate", "--request", files["request"],
                    "--envelope", files["envelope"])
    assert code == 0
    assert out["pass"] is True
    assert out["failures"] == []
    assert out["rewrite_prompt"] is None


def test_gate_fails_with_exit_3_and_the_rewrite_prompt_the_first_time(capsys, repo, files):
    write_json(files["envelope"], _without_why())
    code, out = run(capsys, repo, "gate", "--request", files["request"],
                    "--envelope", files["envelope"])
    assert code == 3
    assert out["pass"] is False
    assert "missing-section:why" in out["failures"]
    assert out["rewrite_prompt"] == explain_gate.rewrite_prompt(out["failures"])
    assert out["next"] == "rewrite"


def test_gate_allows_exactly_one_rewrite(capsys, repo, files):
    write_json(files["envelope"], _without_why())
    args = ("gate", "--request", files["request"], "--envelope", files["envelope"])
    first_code, first = run(capsys, repo, *args)
    second_code, second = run(capsys, repo, *args)
    third_code, third = run(capsys, repo, *args)
    assert first["rewrite_prompt"] is not None
    for code, out in ((second_code, second), (third_code, third)):
        assert code == 3
        assert out["pass"] is False
        assert out["rewrite_prompt"] is None
        assert out["next"] == "finalize"
    assert first_code == 3
    sidecar = Path(str(files["request"]) + ".gate-attempts")
    assert sidecar.exists()


def test_a_new_request_run_gives_the_gate_a_fresh_rewrite(capsys, repo, files):
    write_json(files["envelope"], _without_why())
    args = ("gate", "--request", files["request"], "--envelope", files["envelope"])
    run(capsys, repo, *args)
    _, spent = run(capsys, repo, *args)
    assert spent["rewrite_prompt"] is None
    run(capsys, repo, "request", "--kind", "auto-ruling", "--slug", "s",
        "--out", files["request"])
    _, fresh = run(capsys, repo, "gate", "--request", files["request"],
                   "--envelope", files["envelope"])
    assert fresh["rewrite_prompt"] is not None


def test_gate_with_a_missing_request_file_exits_2(capsys, repo, files, tmp_path):
    code, out = run(capsys, repo, "gate", "--request", tmp_path / "nowhere.json",
                    "--envelope", files["envelope"])
    assert code == 2
    assert "error" in out


# --- finalize

def test_finalize_writes_the_envelope_and_prints_the_summary(capsys, repo, files):
    code, out = run(capsys, repo, "finalize", "--request", files["request"],
                    "--envelope", files["envelope"], "--out", files["out"])
    assert code == 0
    assert out == {"out": str(files["out"]), "facts_only": False, "check_outcome": None}
    final = json.loads(files["out"].read_text(encoding="utf-8"))
    assert final["kind"] == "auto-ruling"
    assert final["facts_only"] is False


def test_finalize_falls_back_to_the_facts_only_envelope(capsys, repo, files):
    write_json(files["envelope"], _without_why())
    code, out = run(capsys, repo, "finalize", "--request", files["request"],
                    "--envelope", files["envelope"], "--out", files["out"])
    assert code == 0
    assert out["facts_only"] is True
    final = json.loads(files["out"].read_text(encoding="utf-8"))
    assert final["facts_only"] is True
    assert {"decided", "why", "commits-to"} <= {s["id"] for s in final["sections"]}


def _checked(tmp_path, change) -> Path:
    env = _envelope()
    change(env)
    return write_json(tmp_path / "checked.json", env)


def _edit_one_word(env):
    env["ste_summary"]["text"] = "The run picks the first option for the cache."


def _rewrite_all(env):
    env["ste_summary"]["text"] = "Xyzzy plugh quux."
    for sec in env["sections"]:
        for item in sec["items"]:
            item["text"] = "Xyzzy plugh quux."
    env["confidence_note"]["text"] = "Xyzzy plugh quux."


@pytest.mark.parametrize("change, expected", [
    (lambda env: None, "accepted"),
    (_edit_one_word, "edited"),
    (_rewrite_all, "rewritten"),
])
def test_finalize_reports_the_check_outcome(capsys, repo, files, tmp_path, change, expected):
    checked = _checked(tmp_path, change)
    code, out = run(capsys, repo, "finalize", "--request", files["request"],
                    "--envelope", files["envelope"], "--checked", checked,
                    "--out", files["out"])
    assert code == 0
    assert out["check_outcome"] == expected
    assert out["facts_only"] is False
    final = json.loads(files["out"].read_text(encoding="utf-8"))
    checked_text = json.loads(checked.read_text(encoding="utf-8"))["ste_summary"]["text"]
    assert final["ste_summary"]["text"] == checked_text  # the checked prose is what ships


# --- render

def test_render_html_prints_an_offline_page(capsys, repo, files):
    code, out = run(capsys, repo, "render", "--envelope", files["envelope"],
                    "--format", "html", "--head", "abc1234", "--title", "Brief demo")
    assert code == 0
    assert out["format"] == "html"
    assert out["text"].startswith("<!DOCTYPE html>")
    assert "abc1234" in out["text"]
    assert explain_offline.assert_offline(out["text"]) is None


def test_render_markdown_starts_with_the_marker(capsys, repo, files):
    code, out = run(capsys, repo, "render", "--envelope", files["envelope"],
                    "--format", "markdown", "--slug", "demo", "--head", "abc1234")
    assert code == 0
    assert out["format"] == "markdown"
    assert explainer_marker.parse(out["text"].splitlines()[0]) == \
        {"kind": "auto-ruling", "slug": "demo", "head": "abc1234"}


def test_render_card_puts_the_recommended_option_first(capsys, repo, tmp_path):
    env = write_json(tmp_path / "escalation.json", _escalation())
    html_path = tmp_path / "brief.html"
    code, out = run(capsys, repo, "render", "--envelope", env, "--format", "card",
                    "--html-path", html_path)
    assert code == 0
    card = out["card"]
    assert str(html_path) in card["question"]
    assert [o["label"] for o in card["options"]] == ["Disk (Recommended)", "Memory"]


def test_render_log_prints_a_decision_entry(capsys, repo, files):
    code, out = run(capsys, repo, "render", "--envelope", files["envelope"],
                    "--format", "log")
    assert code == 0
    assert out["format"] == "log"
    assert out["text"].startswith("### [explainer] ")


# --- telemetry and report

def _row(engine, **extra):
    return json.dumps({"slug": "s", "kind": "pr-brief", "engine": engine, **extra})


def test_telemetry_appends_one_row(capsys, repo):
    code, out = run(capsys, repo, "telemetry", "--row",
                    _row("sonnet", rewrite_used=True, check_outcome="edited"))
    assert code == 0
    assert set(out["row"]) == TELEMETRY_KEYS
    ledger = explain_state.state_root(repo) / "telemetry.ndjson"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["engine"] == "sonnet"


@pytest.mark.parametrize("bad", ["{not json", "[1, 2]"])
def test_telemetry_rejects_a_row_that_is_not_a_json_object(capsys, repo, bad):
    code, out = run(capsys, repo, "telemetry", "--row", bad)
    assert code == 2
    assert "error" in out
    assert not (explain_state.state_root(repo) / "telemetry.ndjson").exists()


def test_report_prints_the_per_engine_rates(capsys, repo):
    run(capsys, repo, "telemetry", "--row", _row("sonnet", rewrite_used=True))
    run(capsys, repo, "telemetry", "--row", _row("sonnet", check_outcome="rewritten"))
    code, out = run(capsys, repo, "report")
    assert code == 0
    assert out["report"] == {"sonnet": {"n": 2, "rewrite_rate": 0.5,
                                        "check_rewritten_rate": 0.5}}


def test_report_with_no_rows_is_empty(capsys, repo):
    code, out = run(capsys, repo, "report")
    assert code == 0
    assert out["report"] == {}
