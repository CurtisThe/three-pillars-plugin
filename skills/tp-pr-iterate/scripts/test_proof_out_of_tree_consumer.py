"""test_proof_out_of_tree_consumer.py — a gitignore-blind lint passes after a round (1.6).

design: review-proof-out-of-tree (Task 1.6)

A consumer's whole-tree private-path lint ignores `.gitignore` on purpose. In a temp
PR repo and a LINKED worktree of it (cwd = the worktree), drive the manifest path the
loop uses by subprocess: resolve the root via the `proof_root.py` CLI, `prepare`,
deliver every angle reply and the tail envelope through the prompt's quoted-heredoc
`put` command, `capture_proof` a real two-commit diff, `reproduce.py`, `tail-check`.
Then walk the worktree (skipping only the `.git` entry, a FILE in a linked worktree)
and assert no file carries the temp absolute path. Second case: PR #48's in-tree
relative symlink to a sibling dir is migrated on the first resolve.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import loop_itest as it  # noqa: E402
import proof_root  # noqa: E402
import review_proof  # noqa: E402

TAG = "TP_REPLY_EOF"


def _linked_pr(tmp_path, monkeypatch):
    """→ (linked worktree, base, head): `lwt` checks out the PR head on its own branch."""
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    wt, base, head = it.make_repo(tmp_path)
    lwt = tmp_path / "lwt"
    it.git(wt, "worktree", "add", "-q", "-b", "feat-review", str(lwt), head)
    monkeypatch.chdir(lwt)
    return lwt, base, head


def _cli_root(cwd) -> Path:
    env = it.env()
    env.pop(proof_root.ENV_VAR, None)
    p = subprocess.run([sys.executable, str(HERE / "proof_root.py")], cwd=str(cwd),
                       capture_output=True, text=True, env=env, check=False)
    assert p.returncode == 0, p.stderr
    return Path(p.stdout.strip())


def _bash_put(cmd_line: str, body: str, cwd) -> None:
    p = subprocess.run(["bash", "-c", f"{cmd_line}\n{body}\n{TAG}\n"], cwd=str(cwd),
                       capture_output=True, text=True, env=it.env(), check=False)
    assert p.returncode == 0, p.stdout + p.stderr


def _put_line(prompt: str) -> str:
    return next(ln for ln in prompt.splitlines() if ln.startswith("python3 ") and TAG in ln)


def _tail_line(angle_line: str) -> str:
    head, _slot = angle_line.rsplit(" --slot ", 1)
    return f"{head} --slot tail <<'{TAG}'"


def _envelope(m: dict) -> str:
    doc = dict(schema="tp-pr-iterate/round-tail/v1", round=m["round"],
               head_reviewed=m["head"], head_after=m["head"],
               tally=dict(P=0, X=0, T=0, C=0, blocking=0, degraded=0),
               downgraded=0, notes=0, action="noop", fix_commit=None, terminal=None,
               converged=False, budget=dict(iteration=1, round_cap=6, signal=None, holding=[]),
               finalizer_stop=None, summary="consumer fixture")
    return json.dumps(doc)


def _leaks(tree: Path, needles) -> list:
    """Gitignore-blind walk: every file except the `.git` entry (dir or file)."""
    hits = []
    for d, dirs, files in os.walk(tree):
        if Path(d) == tree:
            dirs[:] = [n for n in dirs if n != ".git"]
            files = [n for n in files if n != ".git"]
        for n in files:
            p = Path(d) / n
            try:
                text = p.read_bytes().decode("utf-8", "replace")
            except OSError:
                continue
            hits += [f"{p}: {s}" for s in needles if s in text]
    return hits


def _needles(tmp_path) -> set:
    return set([str(tmp_path), os.path.realpath(tmp_path)])


def test_full_round_leaves_no_machine_path_in_the_linked_worktree(tmp_path, monkeypatch):
    lwt, base, head = _linked_pr(tmp_path, monkeypatch)
    assert (lwt / ".git").is_file()
    root = _cli_root(lwt)
    assert Path(os.path.realpath(lwt)) not in Path(os.path.realpath(root)).parents
    p = it.run("round_scratch.py", ["prepare", "--root", str(root), "--pr-url", it.PR,
                                    "--base", base, "--head", head,
                                    "--state", str(root / "iterate-state.9.v1.json"),
                                    "--log", str(root / "iterate-log.9.md"),
                                    "--rulings", "rulings.md"],
               cwd=lwt, extra_env=dict())
    assert p.returncode == 0, p.stdout + p.stderr
    rd = Path(p.stdout.strip())
    m = it.manifest(rd)
    for e in m["angles"]:
        _bash_put(_put_line(e["prompt"]), f"Reviewed `$HOME` for {e['name']}.\n\n{it.CLEAN}", lwt)
    meta = review_proof.capture_proof(base, head, [it.CLEAN] * len(m["angles"]), root=root)
    assert meta["degraded"] is False and meta["files_changed"] >= 1
    r = it.run("reproduce.py", ["--round-dir", str(rd), "--cwd", str(lwt), "--head", head],
               cwd=lwt, extra_env=dict())
    assert r.returncode == 0, r.stdout + r.stderr
    _bash_put(_tail_line(_put_line(m["angles"][0]["prompt"])), _envelope(m), lwt)
    t = it.run("round_scratch.py", ["tail-check", "--round-dir", str(rd)], cwd=lwt,
               extra_env=dict())
    assert t.returncode == 0, t.stdout + t.stderr
    assert (rd / m["angles"][0]["name"] / "reply.md").read_text(encoding="utf-8").startswith(
        "Reviewed `$HOME`")
    assert _leaks(lwt, _needles(tmp_path)) == []


def test_pr48_symlink_layout_is_migrated_on_first_resolve(tmp_path, monkeypatch):
    lwt, _base, _head = _linked_pr(tmp_path, monkeypatch)
    shared = tmp_path / "shared-proof"
    shared.mkdir()
    (shared / "iterate-state.v1.json").write_text("state-48", encoding="utf-8")
    legacy = lwt / ".three-pillars" / "review-proof"
    os.symlink(os.path.relpath(shared, legacy.parent), legacy)
    root = _cli_root(lwt)
    assert (root / "iterate-state.v1.json").read_text(encoding="utf-8") == "state-48"
    assert not os.path.lexists(legacy)
    assert (shared / "iterate-state.v1.json").read_text(encoding="utf-8") == "state-48"
    assert _leaks(lwt, _needles(tmp_path)) == []


def test_the_lint_is_not_vacuous_an_in_tree_manifest_is_caught(tmp_path, monkeypatch):
    lwt, _base, _head = _linked_pr(tmp_path, monkeypatch)
    it.write(lwt, ".three-pillars/review-proof/rounds/9/r1/angles.json",
             json.dumps(dict(paths=dict(proof_root=str(lwt)))))
    assert _leaks(lwt, _needles(tmp_path))
