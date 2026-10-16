"""round_log_carry.pred_ci_local_stamp_carried: a clean ci-local stamp at the anchor P carries
across round-log commits to head L; a code commit C, a dirty stamp, or no git seam never carries."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import ci_local_stamp  # noqa: E402
import round_log_carry  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402

ARCH = "three-pillars-docs/completed-tp-designs"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def commit(repo, files, msg="c"):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    p = commit(tmp_path, {f"{ARCH}/demo/design.md": "d\n", f"{ARCH}/demo/decisions.md": "a\n"})
    return tmp_path, p


def real_git(repo):
    def _run(args):
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return (r.returncode, r.stdout, r.stderr)
    return _run


def stamp_at(sha, dirty=False):
    return {"schema": 1, "head_sha": sha, "dirty": dirty}


def test_stamp_carried_across_round_log_commit(repo):
    r, p = repo
    head = commit(r, {f"{ARCH}/demo/decisions.md": "a\nb\n"})
    res = round_log_carry.pred_ci_local_stamp_carried(
        head, repo_root=str(r), stamp=stamp_at(p), run_git=real_git(r))
    assert res.verdict == GateVerdict.PASS
    assert res.detail.startswith("ci-local stamp carried across 1 round-log commit(s)")


def test_stamp_not_carried_across_code_commit(repo):
    r, p = repo
    head = commit(r, {"src/code.py": "x = 1\n"})
    res = round_log_carry.pred_ci_local_stamp_carried(
        head, repo_root=str(r), stamp=stamp_at(p), run_git=real_git(r))
    expected = ci_local_stamp.pred_ci_local_stamp(head, repo_root=str(r), stamp=stamp_at(p))
    assert res.verdict == GateVerdict.FAIL
    assert res == expected


def test_dirty_stamp_never_carried(repo):
    r, p = repo
    head = commit(r, {f"{ARCH}/demo/decisions.md": "a\nb\n"})
    res = round_log_carry.pred_ci_local_stamp_carried(
        head, repo_root=str(r), stamp=stamp_at(p, dirty=True), run_git=real_git(r))
    assert res.verdict == GateVerdict.FAIL


def _record_subprocess(monkeypatch):
    """Record every subprocess.run call; the adapter swallows exceptions, so a raise
    in the stub would not bind. Assert the returned list is empty afterwards."""
    calls = []

    def spy(*a, **k):
        calls.append(a)
        raise AssertionError("git must not be spawned")
    monkeypatch.setattr(subprocess, "run", spy)
    return calls


def test_stamp_on_head_is_unchanged_and_spawns_no_git(monkeypatch):
    head = "a" * 40
    expected = ci_local_stamp.pred_ci_local_stamp(head, repo_root="/nope", stamp=stamp_at(head))
    calls = _record_subprocess(monkeypatch)
    res = round_log_carry.pred_ci_local_stamp_carried(
        head, repo_root="/nope", stamp=stamp_at(head))
    assert res == expected and res.verdict == GateVerdict.PASS
    assert calls == []


def test_injected_stamp_without_run_git_spawns_no_git(monkeypatch):
    p, head = "a" * 40, "b" * 40
    expected = ci_local_stamp.pred_ci_local_stamp(head, repo_root="/nope", stamp=stamp_at(p))
    calls = _record_subprocess(monkeypatch)
    res = round_log_carry.pred_ci_local_stamp_carried(
        head, repo_root="/nope", stamp=stamp_at(p))
    assert res == expected and res.verdict == GateVerdict.FAIL
    assert calls == []


def test_gate_roster_calls_the_adapter(monkeypatch, tmp_path):
    import gate_roster
    from deterministic_gate import PredicateResult, evaluate_gate
    from test_gate_roster_wiring import _HERMETIC_CONFIG, _make_base_runners

    seen = []

    def spy(head_oid, **kw):
        seen.append(head_oid)
        return PredicateResult(name="ci_local_stamp", verdict=GateVerdict.PASS, detail="spy")

    monkeypatch.setattr(gate_roster, "find_project_root", lambda: tmp_path, raising=False)
    monkeypatch.setattr(round_log_carry, "pred_ci_local_stamp_carried", spy)
    config = {**_HERMETIC_CONFIG,
              "ci": {"expects_github_checks": False, "gate_command": "make ci"}}
    runners = _make_base_runners(stamp=stamp_at("deadbeef"))
    evaluate_gate("https://github.com/o/r/pull/1", runners=runners, config=config)
    assert seen == ["deadbeef"]
