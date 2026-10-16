"""Tests for review_prep_cli.py — 6.3 `settle`.

`settle` never stops a clock; in order it drops on the live-tree guard, on a
late batch, or on an unreadable draft, and otherwise writes A.json / C.json
beside the draft and acts on the slot's oracle verdict.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import review_prep  # noqa: E402
import review_prep_cli  # noqa: E402
import review_prep_scaffold  # noqa: E402

PR = "https://github.com/o/r/pull/7"
REFS = {"refs": [{"path": "f.txt", "line": 1, "note": "n"}]}


def _git(repo, *args):
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture()
def env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".gitignore").write_text(".claude/worktrees/\n", encoding="utf-8")
    (repo / "f.txt").write_text("a\n", encoding="utf-8")
    (repo / "dispatch-telemetry.ndjson").write_text("", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("a\nb\n", encoding="utf-8")
    _git(repo, "commit", "-qa", "-m", "head")
    return {"repo": repo, "proof": tmp_path / "proof", "base": base,
            "head": _git(repo, "rev-parse", "HEAD"), "log": tmp_path / "prep.log",
            "cfg": tmp_path / "absent-config.json"}


def _cli(capsys, *argv, now=None):
    assert review_prep_cli.main(list(argv), now=now) == 0
    return json.loads(capsys.readouterr().out)


def _begin(env, capsys) -> Path:
    out = _cli(capsys, "begin", "--root", str(env["proof"]), "--pr-url", PR,
               "--base", env["base"], "--head", env["head"], "--repo", str(env["repo"]),
               "--log", str(env["log"]), "--config", str(env["cfg"]))
    return Path(out["work"])


def _open(env, capsys, W, slot, unit, now, *extra) -> Path:
    res = _cli(capsys, "open", "--work", str(W), "--head", env["head"], "--slot", slot,
               "--unit", unit, *extra, now=now)
    assert res["state"] == "spawn"
    return Path(res["out_path"])


def _end(env, capsys, W, loop_ids, now):
    return _cli(capsys, "batch-end", "--work", str(W), "--head", env["head"],
                "--loop-ids", ",".join(loop_ids), now=now)


def _settle(env, capsys, W, slot, unit, now=30.0):
    return _cli(capsys, "settle", "--work", str(W), "--head", env["head"], "--slot", slot,
                "--unit", unit, "--loop-id", f"{slot}--{unit}", now=now)


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def _slice(W):
    """A real passing review_slice draft: the diff's own hunk text."""
    diff = (W / "diff.patch").read_text(encoding="utf-8")
    hunk = diff[diff.index("@@"):]
    return {"hunks": [{"file": "f.txt", "hunk": hunk if hunk.endswith("\n") else hunk + "\n"}]}


def _angle(W):
    meta = json.loads((W / "meta.json").read_text(encoding="utf-8"))
    return next(a["name"] for a in meta["angles"] if not a["skipped"])


def _refs_batch(env, capsys, draft=REFS):
    """begin, batch, open review_refs and write its draft; batch-end at 20.0."""
    W = _begin(env, capsys)
    _cli(capsys, "batch", "--work", str(W))
    out = _open(env, capsys, W, "review_refs", "_", 10.0)
    if draft is not None:
        _write(out, draft)
    _end(env, capsys, W, ["review_refs--_"], 20.0)
    return W


def test_settle_accept_writes_accepted_and_cache(env, capsys):
    W = _refs_batch(env, capsys)
    res = _settle(env, capsys, W, "review_refs", "_")
    assert res["action"] == "accept" and res["late"] is False and res["verdict"]["ok"]
    acc = W / "accepted" / "review_refs--_.json"
    assert json.loads(acc.read_text(encoding="utf-8")) == REFS
    key = review_prep.cache_key(env["base"], env["head"], "review_refs", "_")
    assert (review_prep_cli._cache_dir(W) / key).exists()
    assert json.loads((W / "review_refs" / "_" / "A.json").read_text(encoding="utf-8")) == REFS
    ctx = json.loads((W / "review_refs" / "_" / "C.json").read_text(encoding="utf-8"))
    assert ctx == {"root": str(env["repo"].resolve())}


def test_settle_live_tree_write_drops_and_restores(env, capsys):
    W = _refs_batch(env, capsys)
    (env["repo"] / "f.txt").write_text("scribbled\n", encoding="utf-8")
    res = _settle(env, capsys, W, "review_refs", "_")
    assert res["action"] == "drop" and res["verdict"]["ok"] is False
    assert res["verdict"]["reason"].startswith("drafter-wrote-live-tree")
    assert (env["repo"] / "f.txt").read_text(encoding="utf-8") == "a\nb\n"
    assert not (W / "accepted" / "review_refs--_.json").exists()


def test_settle_unreadable_draft_drops(env, capsys):
    W = _refs_batch(env, capsys, draft=None)
    res = _settle(env, capsys, W, "review_refs", "_")
    assert res["action"] == "drop" and res["verdict"]["reason"] == "unreadable-draft"
    out = review_prep.draft_path(W, "review_refs", "_")
    out.write_text("not json", encoding="utf-8")
    assert _settle(env, capsys, W, "review_refs", "_")["verdict"]["reason"] == "unreadable-draft"
    out.write_text("[1]", encoding="utf-8")
    assert _settle(env, capsys, W, "review_refs", "_")["verdict"]["reason"] == "unreadable-draft"


def test_settle_over_budget_drops(env, capsys):
    W = _begin(env, capsys)
    _cli(capsys, "batch", "--work", str(W))
    angle = _angle(W)
    _write(_open(env, capsys, W, "review_refs", "_", 0.0), REFS)
    _write(_open(env, capsys, W, "review_slice", angle, 0.0), _slice(W))
    _end(env, capsys, W, ["review_refs--_", f"review_slice--{angle}"], 400.0)
    res = _settle(env, capsys, W, "review_refs", "_", now=401.0)
    assert res["action"] == "drop" and res["late"] is True
    assert res["verdict"]["reason"] == "over-budget"
    assert not (W / "accepted" / "review_refs--_.json").exists()


def test_slow_first_settle_leaves_batch_mates_on_time(env, capsys):
    W = _begin(env, capsys)
    _cli(capsys, "batch", "--work", str(W))
    angle = _angle(W)
    _write(_open(env, capsys, W, "review_refs", "_", 10.0), REFS)
    _write(_open(env, capsys, W, "review_slice", angle, 10.0), _slice(W))
    _end(env, capsys, W, ["review_refs--_", f"review_slice--{angle}"], 20.0)
    first = _settle(env, capsys, W, "review_refs", "_", now=5000.0)
    assert first["action"] == "accept" and first["late"] is False
    second = _settle(env, capsys, W, "review_slice", angle, now=5001.0)
    assert second["action"] == "accept" and second["late"] is False


def test_settle_keeps_tracked_telemetry_row_between_batches(env, capsys):
    """D10: the next `batch` re-snapshots, so a driver's row is never undone."""
    W = _refs_batch(env, capsys)
    assert _settle(env, capsys, W, "review_refs", "_")["action"] == "accept"
    ndjson = env["repo"] / "dispatch-telemetry.ndjson"
    row = json.dumps({"dispatch_log": "row"})
    ndjson.write_text(row + "\n", encoding="utf-8")
    _cli(capsys, "batch", "--work", str(W))
    angle = _angle(W)
    _write(_open(env, capsys, W, "review_slice", angle, 100.0), _slice(W))
    _end(env, capsys, W, [f"review_slice--{angle}"], 110.0)
    res = _settle(env, capsys, W, "review_slice", angle, now=120.0)
    assert res["action"] == "accept" and res["late"] is False
    assert ndjson.read_text(encoding="utf-8") == row + "\n"


def test_settle_skip_and_refused(env, capsys, tmp_path):
    W = _refs_batch(env, capsys)
    bad = _cli(capsys, "settle", "--work", str(tmp_path / "nowhere"), "--head", env["head"],
               "--slot", "review_refs", "--unit", "_", "--loop-id", "x")
    assert bad == {"state": "skip"}
    foreign = _cli(capsys, "settle", "--work", str(W), "--head", "0" * 40,
                   "--slot", "review_refs", "--unit", "_", "--loop-id", "x")
    assert foreign == {"state": "skip"}
    for unit in ("..", "a/b"):
        res = _cli(capsys, "settle", "--work", str(W), "--head", env["head"],
                   "--slot", "review_refs", "--unit", unit, "--loop-id", "x")
        assert res["state"] == "refused"


def _round(env) -> Path:
    R = env["proof"] / "rounds" / "7" / "r1"
    reply = R / "angle0" / "reply.md"
    reply.parent.mkdir(parents=True)
    finding = {"file": "f.txt", "line_range": [1, 2], "summary": "boom", "class": "P",
               "blocking": True}
    reply.write_text("```json\n" + json.dumps({"findings": [finding]}) + "\n```\n",
                     encoding="utf-8")
    _write(R / "angles.json", {
        "pr_url": PR, "round": 1, "ordinal": "r1", "base": env["base"],
        "paths": {"proof_root": str(env["proof"]), "state_path": str(R / "state.json"),
                  "log_path": str(R / "iterate-log.md")},
        "angles": [{"name": "angle0", "role": "confirmer", "model": "opus",
                    "tier": "claude", "reply_path": str(reply)}]})
    return R


def test_settle_scaffold_accept_writes_note_and_discards_scratch(env, capsys):
    W = _begin(env, capsys)
    R = _round(env)
    W2 = review_prep.move_work(W, R)
    assert W2 == R / "prep" / "work"
    _cli(capsys, "batch", "--work", str(W2))
    key = review_prep_scaffold.targets(R)[0]["key"]
    out = _open(env, capsys, W2, "repro_scaffold", key, 10.0, "--round-dir", str(R))
    _write(out, {"source": "def test_boom():\n    assert 1 == 2\n", "test_name": "test_boom"})
    _end(env, capsys, W2, [f"repro_scaffold--{key}"], 20.0)
    res = _settle(env, capsys, W2, "repro_scaffold", key)
    assert res["action"] == "accept", res
    note = json.loads((R / "prep" / "scaffolds" / f"{key}.json").read_text(encoding="utf-8"))
    assert note["key"] == key and note["head"] == env["head"] and note["accepted"] is True
    assert (W2 / "accepted" / f"repro_scaffold--{key}.json").is_file()
    worktrees = env["repo"] / ".claude" / "worktrees"
    assert not list(worktrees.glob("review-prep-*"))
    listed = _git(env["repo"], "worktree", "list", "--porcelain")
    assert [ln for ln in listed.splitlines() if ln.startswith("worktree ")] == \
        [f"worktree {env['repo'].resolve()}"]
