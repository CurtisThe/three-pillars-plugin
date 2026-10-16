"""test_bypass_check.py — the post-merge bypass banner (design review-convergence 11.5).

`bypass_check.check(pr_url, merged_head, *, comments_fn, runners, config, repo_root)`:
neither a review proof nor an operator-accept on the merged head → the exact
`bypass: PR #<n> merged head <sha7> had neither a review proof nor an operator-accept`
line; either one present → None (silent); a Gitea origin → the named
`bypass check unavailable on gitea (gitea-forge-adapter)` line BEFORE either side is
consulted. Total: a raising fetch on either side is "not proven", never a raise.
The CLI prints the line when there is one and ALWAYS exits 0 (advisory).

Hermetic: every runner is injected — never a live gh call. Gitea fixtures are
`git init` + an origin + a COMMITTED `.three-pillars/config.json` (forge.resolve
reads the committed config, so the fixture resolves with no probe).
Run with: python3 -m pytest skills/tp-post-merge/scripts/test_bypass_check.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bypass_check  # noqa: E402

PR = "https://github.com/o/r/pull/7"
HEAD = "0123456789abcdef0123456789abcdef01234567"
BYPASS = ("bypass: PR #7 merged head 0123456 "
          "had neither a review proof nor an operator-accept")
GITEA_LINE = "bypass check unavailable on gitea (gitea-forge-adapter)"


def _raising_comments_fn(pr_url):
    raise RuntimeError("gh unavailable")


def _raising_reviews_fn(pr_url):
    raise RuntimeError("gh unavailable")


def _proof_comments_fn(pr_url):
    """A digest comment authored by the self login (the trusted digest author)."""
    return [{"author": "curtisthebot",
             "body": f"Review round 1.\n<sub>proof: base `abc1234` · "
                     f"head `{HEAD}` · 3 files +10 −2</sub>"}]


def _accept_reviews_fn(pr_url):
    return [{"user": {"login": "curtis", "type": "User"},
             "state": "APPROVED", "commit_id": HEAD,
             "submitted_at": "2026-10-11T00:00:00Z",
             "body": f"tp-accept: {HEAD} gate lows are fine"}]


def _gitea_repo(tmp_path: Path) -> Path:
    """A committed gitea config + a gitea origin, so forge.resolve answers without probing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["init", "-q"], check=True, capture_output=True)
    subprocess.run(git + ["config", "user.email", "t@example.test"],
                   check=True, capture_output=True)
    subprocess.run(git + ["config", "user.name", "Test"],
                   check=True, capture_output=True)
    cfg_dir = repo / ".three-pillars"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps(
        {"forge": {"kind": "gitea", "web_base": "https://gitea.example.test"}}),
        encoding="utf-8")
    subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(git + ["commit", "-q", "-m", "seed"], check=True,
                   capture_output=True)
    subprocess.run(git + ["remote", "add", "origin",
                          "https://gitea.example.test/o/r.git"],
                   check=True, capture_output=True)
    return repo


# --- check(): the three outcomes --------------------------------------------------

def test_neither_proof_nor_accept_returns_the_exact_bypass_line():
    line = bypass_check.check(PR, HEAD,
                              comments_fn=_raising_comments_fn,
                              runners={"self_login_fn": lambda: "curtisthebot",
                                       "reviews_fn": _raising_reviews_fn})
    assert line == BYPASS


def test_review_proof_present_is_silent():
    line = bypass_check.check(PR, HEAD,
                              comments_fn=_proof_comments_fn,
                              runners={"self_login_fn": lambda: "curtisthebot",
                                       "reviews_fn": _raising_reviews_fn})
    assert line is None


def test_operator_accept_present_is_silent():
    line = bypass_check.check(PR, HEAD,
                              comments_fn=_raising_comments_fn,
                              runners={"self_login_fn": lambda: "curtisthebot",
                                       "reviews_fn": _accept_reviews_fn})
    assert line is None


def test_both_fetches_raise_no_raise_and_the_bypass_line():
    """Totality: a raising side is an unprovable observation, never a crash."""
    assert bypass_check.check(
        PR, HEAD,
        comments_fn=lambda u: (_ for _ in ()).throw(RuntimeError("boom")),
        runners={"self_login_fn": lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                 "reviews_fn": _raising_reviews_fn}) == BYPASS


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                           "-c", "commit.gpgsign=false", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo, files, msg):
    for rel, text in files.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def test_round_log_flush_above_the_proven_head_is_not_a_bypass(tmp_path):
    """The two-stable log flush lands above the reviewed head; the gate's
    round-log carry proves the merged head, so the banner must stay silent."""
    arch = "three-pillars-docs/completed-tp-designs/demo"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _commit(repo, {f"{arch}/design.md": "# demo\n", f"{arch}/decisions.md": "log\n"}, "archive")
    reviewed = _commit(repo, {"code.py": "X = 1\n"}, "reviewed head")
    merged = _commit(repo, {f"{arch}/decisions.md": "log\nround 1 converged\n"}, "flush")
    line = bypass_check.check(
        PR, merged,
        comments_fn=lambda _u: [{"author": "tp-bot",
                                 "body": f"proof: base `abc1234` · head `{reviewed}`"}],
        runners={"self_login_fn": lambda: "tp-bot", "reviews_fn": lambda _u: []},
        repo_root=str(repo))
    assert line is None, line


def test_cli_loads_the_repo_config_so_a_base_sync_carry_is_not_a_bypass(tmp_path, monkeypatch):
    """`main` passes no config: `check` must load `<repo>/.three-pillars/config.json`, else
    the gate's certified base-sync carry is off and a gate-proven landing reads as a bypass."""
    shared = HERE.parents[1] / "_shared"
    sys.path.insert(0, str(shared / "fixtures"))
    import base_sync_oracle
    import diff_balloon_guard
    import review_proof
    from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge

    (tmp_path / "s").mkdir()
    s = build_scenario(tmp_path / "s")
    diverge_base_only(s)
    reviewed = s.head()
    merged = make_certified_sync_merge(s)
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)
    monkeypatch.setattr(diff_balloon_guard, "derive_base_ref", lambda _u: s.base_ref)
    cfg = {"schema_version": 1, "review": {"approval_survives_safe_base_sync": True,
                                           "base_sync_carry_max_chain": 2}}
    (Path(s.repo_dir) / ".three-pillars").mkdir(exist_ok=True)
    (Path(s.repo_dir) / ".three-pillars" / "config.json").write_text(json.dumps(cfg))
    meta = {"base": "base000", "head": reviewed, "files_changed": 1, "insertions": 1,
            "deletions": 0, "degraded": False, "reason": None}
    digest = [{"author": "tp-bot",
               "body": review_proof.format_proof_digest(meta, [("correctness", 0)])}]
    monkeypatch.setitem(bypass_check._LIVE_BUILDERS, "comments_fn", lambda _u: digest)
    monkeypatch.setitem(bypass_check._LIVE_BUILDERS, "self_login_fn", lambda: "tp-bot")
    monkeypatch.setitem(bypass_check._LIVE_BUILDERS, "reviews_fn", lambda _u: [])
    assert bypass_check.check(PR, merged, repo_root=str(s.repo_dir)) is None


# --- check(): forge parity --------------------------------------------------------

def test_gitea_origin_returns_the_named_line_and_consults_nothing(tmp_path):
    calls = []

    def _comments(pr_url):
        calls.append("comments")
        return []

    def _reviews(pr_url):
        calls.append("reviews")
        return []

    line = bypass_check.check(PR, HEAD, comments_fn=_comments,
                              runners={"self_login_fn": lambda: "curtisthebot",
                                       "reviews_fn": _reviews},
                              repo_root=str(_gitea_repo(tmp_path)))
    assert line == GITEA_LINE
    assert calls == []


def test_github_origin_and_bad_repo_root_are_not_gitea(tmp_path):
    assert bypass_check.check(PR, HEAD, comments_fn=_raising_comments_fn,
                              runners={"self_login_fn": lambda: "curtisthebot",
                                       "reviews_fn": _raising_reviews_fn},
                              repo_root=str(tmp_path)) == BYPASS


# --- the CLI is advisory: prints the line, always exits 0 --------------------------

def _argv(repo_root):
    return ["--pr-url", PR, "--head", HEAD, "--repo", str(repo_root)]


def test_cli_prints_the_bypass_line_and_exits_0(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(bypass_check._LIVE_BUILDERS, "comments_fn",
                        _raising_comments_fn)
    monkeypatch.setitem(bypass_check._LIVE_BUILDERS, "reviews_fn",
                        _raising_reviews_fn)
    monkeypatch.setitem(bypass_check._LIVE_BUILDERS, "self_login_fn",
                        lambda: "curtisthebot")
    assert bypass_check.main(_argv(tmp_path)) == 0
    assert BYPASS in capsys.readouterr().out


def test_cli_is_silent_and_exits_0_with_proof(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(bypass_check._LIVE_BUILDERS, "comments_fn",
                        _proof_comments_fn)
    monkeypatch.setitem(bypass_check._LIVE_BUILDERS, "reviews_fn",
                        _raising_reviews_fn)
    monkeypatch.setitem(bypass_check._LIVE_BUILDERS, "self_login_fn",
                        lambda: "curtisthebot")
    assert bypass_check.main(_argv(tmp_path)) == 0
    assert capsys.readouterr().out == ""


def test_cli_names_the_gitea_line_and_still_exits_0(tmp_path):
    """A real subprocess: the Gitea path needs no runner, so this is hermetic."""
    out = subprocess.run(
        [sys.executable, str(HERE / "bypass_check.py")] + _argv(_gitea_repo(tmp_path)),
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0
    assert GITEA_LINE in out.stdout


# --- SKILL.md step 6.5 wires the banner -------------------------------------------

def _step_6_5() -> str:
    text = (HERE.parent / "SKILL.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("6.5."))
    end = next(i for i in range(start + 1, len(lines))
               if lines[i].startswith("7. **Report**"))
    return "\n".join(lines[start:end])


def test_skill_step_6_5_names_the_script_advisory():
    block = _step_6_5()
    assert "bypass_check.py" in block
    assert "advisory" in block
