"""test_proof_root_resolve.py — the one proof-root resolver (review-proof-out-of-tree 1.1).

Real temp git repos (a main checkout and a linked worktree of it): the default root
is `<absolute git-dir>/three-pillars/review-proof`, outside the working tree; the
`review.proof_dir` override is relative-only and stays inside the worktree;
`TP_REVIEW_PROOF_DIR` (absolute only; a relative value is refused) wins;
outside git the old `<start>/.three-pillars/review-proof` applies. Resolving never
touches the filesystem.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import loop_itest  # noqa: E402
import proof_root  # noqa: E402
from proof_root_itest import LEGACY, SUB, linked, main_repo, snapshot  # noqa: E402


def test_main_checkout_default_is_under_dot_git(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main = main_repo(tmp_path)
    got = proof_root.resolve_proof_root(start=main, config={})
    assert got == (main / ".git" / SUB).resolve()


def test_linked_worktree_default_is_its_git_dir_outside_the_tree(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main, wt = linked(tmp_path)
    got = proof_root.resolve_proof_root(start=wt, config={})
    assert got.is_absolute()
    assert got == (main / ".git" / "worktrees" / "wt" / SUB).resolve()
    assert wt.resolve() not in got.parents


def test_start_none_uses_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main, wt = linked(tmp_path)
    monkeypatch.chdir(wt)
    assert proof_root.resolve_proof_root(config={}) == (
        main / ".git" / "worktrees" / "wt" / SUB).resolve()


def _cfg(value) -> dict:
    return dict(review=dict(proof_dir=value))


def test_relative_config_override_is_against_the_worktree_toplevel(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    _main, wt = linked(tmp_path)
    sub = wt / "scratch"
    sub.mkdir()
    got = proof_root.resolve_proof_root(start=sub, config=_cfg("scratch/proof"))
    assert got == wt.resolve() / "scratch" / "proof"


def test_absolute_config_override_is_refused_with_a_notice(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main = main_repo(tmp_path)
    err = io.StringIO()
    got = proof_root.resolve_proof_root(
        start=main, config=_cfg(str(tmp_path / "elsewhere")), err=err)
    assert got == (main / ".git" / SUB).resolve()
    assert "review.proof_dir" in err.getvalue() and "relative" in err.getvalue()


def test_env_absolute_wins_over_config(tmp_path, monkeypatch):
    main = main_repo(tmp_path)
    shared = tmp_path / "shared-proof"
    monkeypatch.setenv(proof_root.ENV_VAR, str(shared))
    assert proof_root.resolve_proof_root(start=main, config=_cfg("scratch/proof")) == shared


def test_non_git_dir_keeps_the_old_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    plain = tmp_path / "plain"
    plain.mkdir()
    fail = lambda _args: (128, "", "fatal: not a git repository")  # noqa: E731
    got = proof_root.resolve_proof_root(start=plain, config=dict(), run_git=fail)
    assert got == plain / LEGACY


def test_git_shim_is_injectable_and_used(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    calls = []

    def fake(args):
        calls.append(args)
        return 0, f"{tmp_path}/gd\n{tmp_path}/top\n", ""

    got = proof_root.resolve_proof_root(start=tmp_path, config=dict(), run_git=fake)
    assert got == tmp_path / "gd" / SUB
    assert calls and "--absolute-git-dir" in calls[0] and "--show-toplevel" in calls[0]


def test_config_none_loads_the_repo_config(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main = main_repo(tmp_path)
    doc = dict(schema_version=1, review=dict(proof_dir="p/q"))
    loop_itest.write(main, ".three-pillars/config.json", json.dumps(doc))
    assert proof_root.resolve_proof_root(start=main) == main.resolve() / "p" / "q"


def test_config_none_malformed_or_missing_is_the_default(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main = main_repo(tmp_path)
    default = (main / ".git" / SUB).resolve()
    assert proof_root.resolve_proof_root(start=main) == default
    loop_itest.write(main, ".three-pillars/config.json", "not json at all")
    assert proof_root.resolve_proof_root(start=main) == default


def test_resolver_performs_no_filesystem_mutation(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main, wt = linked(tmp_path)
    (wt / LEGACY).mkdir(parents=True)
    (wt / LEGACY / "iterate-state.v1.json").write_text("[]", encoding="utf-8")
    before = snapshot(main, wt)
    proof_root.resolve_proof_root(start=wt, config=dict())
    proof_root.resolve_proof_root(start=wt, config=_cfg("x/y"))
    assert snapshot(main, wt) == before


def test_cli_no_migrate_prints_the_resolved_root(tmp_path):
    main, wt = linked(tmp_path)
    env = loop_itest.env()
    env.pop(proof_root.ENV_VAR, None)
    p = subprocess.run([sys.executable, str(HERE / "proof_root.py"), "--no-migrate"],
                       cwd=str(wt), capture_output=True, text=True, env=env, check=False)
    assert p.returncode == 0, p.stderr
    assert Path(p.stdout.strip()) == (main / ".git" / "worktrees" / "wt" / SUB).resolve()


def test_relative_env_is_refused_with_a_notice_and_the_default_used(tmp_path, monkeypatch):
    main = main_repo(tmp_path)
    monkeypatch.setenv(proof_root.ENV_VAR, "rel/proof")
    err = io.StringIO()
    got = proof_root.resolve_proof_root(start=main, config={}, err=err)
    assert got == (main / ".git" / SUB).resolve()
    assert proof_root.ENV_VAR in err.getvalue() and "absolute" in err.getvalue()


def test_relative_env_outside_git_falls_back_to_the_legacy_root(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv(proof_root.ENV_VAR, "rel/proof")
    fail = lambda _args: (128, "", "fatal: not a git repository")  # noqa: E731
    err = io.StringIO()
    got = proof_root.resolve_proof_root(start=plain, config={}, run_git=fail, err=err)
    assert got == plain / LEGACY and proof_root.ENV_VAR in err.getvalue()


def test_config_override_escaping_the_worktree_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main, wt = linked(tmp_path)
    default = (main / ".git" / "worktrees" / "wt" / SUB).resolve()
    for value in ("../x", "a/../../x", ".."):
        err = io.StringIO()
        assert proof_root.resolve_proof_root(start=wt, config=_cfg(value), err=err) == default
        assert "review.proof_dir" in err.getvalue() and "inside the worktree" in err.getvalue()
    err = io.StringIO()
    assert proof_root.resolve_proof_root(start=wt, config=_cfg("a/../p"), err=err) == \
        wt.resolve() / "p"
    assert err.getvalue() == ""
