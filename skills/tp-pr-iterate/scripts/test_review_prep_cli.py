"""Tests for review_prep_cli.py — 6.1 (`begin`, `batch`) and 6.2 (`open`,
`batch-end`).

`open` decides one unit in order — a re-verified cache hit, a spent-budget
skip, or a spawn — and a hit never starts a budget interval; `batch-end`
stops the batch's budget clocks at one instant with no oracle run.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import angles  # noqa: E402
import review_prep  # noqa: E402
import review_prep_budget  # noqa: E402
import review_prep_cli  # noqa: E402
import review_prep_io  # noqa: E402
import review_prep_scaffold  # noqa: E402

import cheap_oracle  # noqa: E402 (via _shared, on sys.path after the imports above)

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                         env=env, check=True)
    return out.stdout.strip()


@pytest.fixture()
def env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".gitignore").write_text("/.tp-scratch/\n", encoding="utf-8")
    (repo / "f.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("a\nb\n", encoding="utf-8")
    _git(repo, "commit", "-qa", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")
    proof = tmp_path / "proof"  # OUTSIDE the repo
    return {"repo": repo, "proof": proof,
            "pr": "https://github.com/o/r/pull/7",
            "base": base, "head": head,
            "W": review_prep.work_dir(proof, "https://github.com/o/r/pull/7"),
            "log": tmp_path / "prep.log"}


def _begin_argv(env, head=None):
    return ["begin", "--root", str(env["proof"]), "--pr-url", env["pr"],
            "--base", env["base"], "--head", head or env["head"],
            "--repo", str(env["repo"]), "--log", str(env["log"]),
            "--config", str(env["repo"] / "absent-config.json")]


def test_begin_head_mismatch(env, capsys):
    rc = review_prep_cli.main(_begin_argv(env, head="0" * 40))
    out = capsys.readouterr()
    assert rc == 0
    assert json.loads(out.out) == {"skip": "head-mismatch"}
    assert "[cheap-tier] prep skipped: HEAD != head" in env["log"].read_text(encoding="utf-8")
    assert not env["W"].exists()


def test_begin_happy_path(env, capsys):
    W = env["W"]
    W.mkdir(parents=True)
    (W / "stale.txt").write_text("old\n", encoding="utf-8")
    cache = W.parent.parent / review_prep.CACHE
    other = "f" * 40
    review_prep.cache_put(cache,
                          review_prep.cache_key(env["base"], other, "review_refs", "u1"),
                          {"x": 1})
    review_prep.cache_put(cache,
                          review_prep.cache_key(env["base"], env["head"], "review_refs", "u2"),
                          {"y": 2})
    rc = review_prep_cli.main(_begin_argv(env))
    out = capsys.readouterr()
    assert rc == 0
    res = json.loads(out.out)
    assert res["work"] == str(W)
    assert res["bucket"] in {"xs", "s", "m", "l"}
    assert not (W / "stale.txt").exists()
    assert (W / "diff.patch").read_text(encoding="utf-8") == \
        _git(env["repo"], "diff", f"{env['base']}...{env['head']}").rstrip("\n") + "\n"
    assert (W / "budget.json").exists()
    meta = json.loads((W / "meta.json").read_text(encoding="utf-8"))
    assert meta["pr_url"] == env["pr"]
    assert meta["base"] == env["base"] and meta["head"] == env["head"]
    assert Path(meta["repo"]).is_absolute() and Path(meta["log"]).is_absolute()
    expected = [(a.get("name"), bool(a.get("skipped")), a.get("prompt"))
                for a in angles.load_angles(None)]
    actual = [(a["name"], a["skipped"], a["prompt"]) for a in meta["angles"]]
    assert actual == expected
    assert not (cache / review_prep.cache_key(env["base"], other, "review_refs", "u1")).exists()
    assert (cache / review_prep.cache_key(env["base"], env["head"], "review_refs", "u2")).exists()
    assert not (W / "live").exists()  # begin takes no snapshot


def test_begin_resolves_symbolic_base_to_sha(env, capsys):
    argv = _begin_argv(env)
    argv[argv.index("--base") + 1] = "main~1"  # a ref, not a SHA (impl-audit finding 2)
    assert review_prep_cli.main(argv) == 0 and "work" in json.loads(capsys.readouterr().out)
    meta = json.loads((env["W"] / "meta.json").read_text(encoding="utf-8"))
    assert meta["base"] == env["base"]
    key = review_prep.cache_key(meta["base"], meta["head"], "review_refs", "_")
    review_prep.cache_put(env["W"].parent.parent / review_prep.CACHE, key, {"x": 1})


def test_batch_writes_and_replaces(env, capsys):
    review_prep_cli.main(_begin_argv(env))
    capsys.readouterr()
    live = env["W"] / "live"
    for p in (env["W"].parent.parent / review_prep.CACHE).glob("*.tmp"):
        p.unlink()  # cache_put leftovers, not part of the batch
    live.mkdir()
    (live / "stale-marker.txt").write_text("old\n", encoding="utf-8")
    rc = review_prep_cli.main(["batch", "--work", str(env["W"])])
    assert rc == 0 and json.loads(capsys.readouterr().out)
    assert (live / "snapshot.json").exists()
    assert not (live / "stale-marker.txt").exists()  # the earlier dir was replaced


def test_batch_no_meta(tmp_path, capsys):
    rc = review_prep_cli.main(["batch", "--work", str(tmp_path / "nope")])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"state": "skip"}


def test_usage_error_exits_2():
    with pytest.raises(SystemExit) as exc:
        review_prep_cli.main(["begin"])
    assert exc.value.code == 2


# --- 6.2: open and batch-end -----------------------------------------------------


def _call(argv, capsys, now=None):
    assert review_prep_cli.main(argv, now=now) == 0
    return json.loads(capsys.readouterr().out)


def _begin(env):
    review_prep_cli.main(_begin_argv(env))  # the caller drains the printed line
    return env["W"]


def _open_argv(env, slot="review_refs", unit="_", head=None, round_dir=None):
    argv = ["open", "--work", str(env["W"]), "--slot", slot, "--unit", unit,
            "--head", head or env["head"]]
    if round_dir is not None:
        argv += ["--round-dir", str(round_dir)]
    return argv


def _round(tmp_path):
    """A minimal round dir carrying one blocking-without-reproducer target."""
    rd = tmp_path / "proof" / "rounds" / "pr7" / "r3"
    rp = rd / "angle0" / "reply.md"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("```json\n" + json.dumps({"findings": [{
        "file": "src/a.py", "line_range": [3, 5], "summary": "boom",
        "class": "P", "blocking": True}]}) + "\n```\n", encoding="utf-8")
    (rd / "angles.json").write_text(json.dumps({
        "pr_url": "https://github.com/o/r/pull/7", "round": 3, "ordinal": "r3",
        "base": "BASE",
        "paths": {"proof_root": str(tmp_path / "proof"),
                  "log_path": str(tmp_path / "proof" / "iterate-log.1.md")},
        "angles": [{"name": "angle0", "role": "confirmer", "model": "opus",
                    "reply_path": str(rp)}]}), encoding="utf-8")
    return rd


def test_open_spawn_hit_skip(env, capsys):
    W = _begin(env)
    capsys.readouterr()
    staged = review_prep_io.unit_dir(env["repo"], env["pr"], "review_refs", "_")
    facts = staged / "facts.json"  # in-tree: the drafter is project-scoped
    res = _call(_open_argv(env), capsys, now=10.0)
    assert res == {"state": "spawn", "facts_path": str(facts),
                   "out_path": str(staged / "draft.json"),
                   "loop_id": "review_refs--_"}
    assert facts.is_file()
    art = {"refs": [{"path": "f.txt", "line": 1, "note": "n"}]}
    review_prep.cache_put(W.parent.parent / review_prep.CACHE,
                          review_prep.cache_key(env["base"], env["head"],
                                                "review_refs", "_"), art)
    facts.unlink()
    assert _call(_open_argv(env), capsys, now=20.0) == {"state": "hit"}
    acc = (W / "accepted" / "review_refs--_.json").read_text(encoding="utf-8")
    assert json.loads(acc) == art
    assert not facts.exists()
    review_prep_budget.start(W, "x", now=0.0)
    res = _call(_open_argv(env, "review_slice", "correctness-leak"), capsys, now=1000.0)
    assert res == {"state": "skip"}
    log = env["log"].read_text(encoding="utf-8")
    assert "prep budget spent" in log and "review_slice/correctness-leak" in log


def test_open_refusals(env, capsys):
    W = _begin(env)
    capsys.readouterr()
    res = _call(_open_argv(env, "review_slice", "nope"), capsys, now=5.0)
    assert res["state"] == "refused" and "nope" in res["reason"]
    assert not (W / "review_slice" / "nope").exists()
    res = _call(_open_argv(env, "repro_scaffold", "zzz"), capsys, now=5.0)
    assert res["state"] == "refused" and "round-dir" in res["reason"]


def test_open_repro_scaffold_finding(env, capsys, tmp_path):
    W = _begin(env)
    capsys.readouterr()
    rd = _round(tmp_path)
    key = review_prep_scaffold.targets(rd)[0]["key"]
    assert _call(_open_argv(env, "repro_scaffold", key, round_dir=rd), capsys,
                 now=5.0)["state"] == "spawn"
    staged = review_prep_io.unit_dir(env["repo"], env["pr"], "repro_scaffold", key)
    facts = json.loads((staged / "facts.json").read_text(encoding="utf-8"))
    finding = facts["finding"]
    assert set(finding) == {"file", "line_range", "summary", "class"}
    assert finding["file"] == "src/a.py" and finding["line_range"] == [3, 5]


def test_batch_end_stops_all(env, capsys):
    W = _begin(env)
    capsys.readouterr()
    review_prep_budget.start(W, "a", now=10.0)
    review_prep_budget.start(W, "b", now=10.0)
    res = _call(["batch-end", "--work", str(W), "--head", env["head"],
                 "--loop-ids", "a,b"], capsys, now=20.0)
    assert res == {"late": {"a": False, "b": False}}
    budget = json.loads((W / "budget.json").read_text(encoding="utf-8"))
    assert {iv["id"]: iv["end"] for iv in budget["intervals"]} == {"a": 20.0, "b": 20.0}


def test_open_batch_end_missing_w_foreign_head(env, tmp_path, capsys, monkeypatch):
    W = _begin(env)
    capsys.readouterr()
    errbuf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", errbuf)
    assert _call(["open", "--work", str(tmp_path / "nowhere"), "--slot",
                  "review_refs", "--unit", "_", "--head", env["head"]], capsys,
                 now=1.0) == {"state": "skip"}
    assert "[cheap-tier] prep work dir missing:" in errbuf.getvalue()
    assert _call(["batch-end", "--work", str(tmp_path / "nowhere"),
                  "--head", env["head"], "--loop-ids", "a"], capsys, now=1.0) \
        == {"state": "skip"}
    assert _call(_open_argv(env, head="0" * 40), capsys, now=1.0) == {"state": "skip"}
    assert _call(["batch-end", "--work", str(W), "--head", "0" * 40,
                  "--loop-ids", "a"], capsys, now=1.0) == {"state": "skip"}
    assert env["log"].read_text(encoding="utf-8").count(
        "prep work dir is for another head") == 2


def test_open_scaffold_hit_checks_before_discard(env, monkeypatch, capsys, tmp_path):
    W = _begin(env)
    capsys.readouterr()
    rd = _round(tmp_path)
    key = review_prep_scaffold.targets(rd)[0]["key"]
    art = {"source": "def t():\n    assert 0", "test_name": "test_t"}
    review_prep.cache_put(W.parent.parent / review_prep.CACHE,
                          review_prep.cache_key(env["base"], env["head"],
                                                "repro_scaffold", key), art)
    scratch = tmp_path / "review-prep-1" / "r1"
    scratch.mkdir(parents=True)
    notes, state = [], {"discarded": False}
    monkeypatch.setattr(review_prep_scaffold, "scratch", lambda repo, head: scratch)
    monkeypatch.setattr(review_prep_scaffold, "write_note",
                        lambda R, k, a, h: notes.extend((str(R), k, a, str(h))))

    def fake_check(slot, artifact, ctx):
        assert ctx["cwd"] == str(scratch) and Path(ctx["cwd"]).exists()
        return {"ok": True, "oracle": "observed_red", "reason": ""}

    def fake_discard(path):
        state["discarded"] = True
        shutil.rmtree(str(path), ignore_errors=True)

    monkeypatch.setattr(cheap_oracle, "check", fake_check)
    monkeypatch.setattr(review_prep_scaffold, "discard", fake_discard)
    assert _call(_open_argv(env, "repro_scaffold", key, round_dir=rd), capsys,
                 now=5.0) == {"state": "hit"}
    assert state["discarded"] and notes == [str(rd), key, art, env["head"]]
