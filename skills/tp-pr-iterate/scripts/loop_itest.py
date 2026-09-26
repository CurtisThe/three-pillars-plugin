"""loop_itest — a temp PR repo and the real loop CLIs, for the Phase-7 integration tests.

design: iterate-convergence-budget (Tasks 7.1–7.3)

Test support only (no `test_` prefix, so pytest does not collect it). It builds a
temp git repo shaped like a PR checkout — a bare `origin`, a `main` base, a `feat`
head with a real diff, a tracked `.three-pillars/config.json` and a tracked
`three-pillars-docs/.../decisions.md` — and runs every loop step through its REAL
CLI by subprocess: `round_scratch.py`, `reproduce.py`, `converge.py`, `run_round.py`.

The only stub is the network edge: `fake_gh` puts a `gh` shim first on PATH. It
records posted PR comments and serves them back (authored by `FAKE_LOGIN`) to
`gh pr view --json comments`, answers `gh api user` with `FAKE_LOGIN`, and returns
empty JSON for label calls — so converge's proof post, oracle and run_round's
labels all run their real code paths.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PR = "https://github.com/o/r/pull/9"
FAKE_LOGIN = "tp-bot"
DECISIONS = "three-pillars-docs/tp-designs/d/decisions.md"
CONFIG = ".three-pillars/config.json"
CLEAN = "```json\n[]\n```\n"
_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_CONFIG_NOSYSTEM": "1"}

_FAKE_GH = '''#!{python}
import json, os, sys
store = os.environ["FAKE_GH_STORE"]
args = sys.argv[1:]
with open(os.path.join(store, "calls.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\\n")
cpath = os.path.join(store, "comments.json")
try:
    with open(cpath, encoding="utf-8") as fh:
        comments = json.load(fh)
except OSError:
    comments = []
if args[:2] == ["api", "user"]:
    print("{login}")
elif args and args[0] == "api" and args[1].endswith("/comments") and "-f" in args:
    comments.append(args[args.index("-f") + 1].split("=", 1)[1])
    with open(cpath, "w", encoding="utf-8") as fh:
        json.dump(comments, fh)
    print("{{}}")
elif args[:2] == ["pr", "view"] and "comments" in args:
    print(json.dumps({{"comments": [{{"author": {{"login": "{login}"}}, "body": b}}
                                  for b in comments]}}))
elif args[:2] == ["pr", "view"] and "labels" in args:
    print(json.dumps({{"labels": []}}))
else:
    print("{{}}")
'''


def env(extra=None) -> dict:
    """os.environ plus the hermetic git identity (and any `extra`)."""
    return {**os.environ, **_GIT_ENV, **(extra or {})}


def git(cwd, *args) -> str:
    out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                         encoding="utf-8", env=env(), check=True)
    return out.stdout.strip()


def write(root, rel, text) -> Path:
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def config_doc(round_cap=6, k_consecutive=99) -> dict:
    return {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False},
            "pdw": {"guards": {"round_cap": round_cap, "k_consecutive": k_consecutive}}}


def make_repo(tmp, *, round_cap=6, k_consecutive=99) -> tuple[Path, str, str]:
    """→ (worktree, base_sha, head_sha): `feat` tracks a bare origin, one PR commit ahead."""
    tmp = Path(tmp)
    origin = tmp / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env(), check=True)
    wt = tmp / "wt"
    wt.mkdir()
    git(wt, "init", "-q", "-b", "main")
    git(wt, "config", "user.name", "t")
    git(wt, "config", "user.email", "t@example.com")
    git(wt, "config", "commit.gpgsign", "false")
    write(wt, CONFIG, json.dumps(config_doc(round_cap, k_consecutive), indent=2) + "\n")
    write(wt, DECISIONS, "# decisions\n")
    write(wt, "src/a.py", "a = 1\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "base")
    base = git(wt, "rev-parse", "HEAD")
    git(wt, "checkout", "-q", "-b", "feat")
    write(wt, "src/feature.py", "".join(f"x{i} = {i}\n" for i in range(40)))
    git(wt, "add", "src/feature.py")
    git(wt, "commit", "-q", "-m", "feature")
    git(wt, "remote", "add", "origin", str(origin))
    git(wt, "push", "-q", "-u", "origin", "feat")
    return wt, base, git(wt, "rev-parse", "HEAD")


def fake_gh(tmp) -> dict:
    """Install the `gh` shim; → env overrides (PATH first, FAKE_GH_STORE)."""
    bindir = Path(tmp) / "fakebin"
    store = Path(tmp) / "fakegh"
    bindir.mkdir()
    store.mkdir()
    gh = bindir / "gh"
    gh.write_text(_FAKE_GH.format(python=sys.executable, login=FAKE_LOGIN), encoding="utf-8")
    gh.chmod(0o755)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_GH_STORE": str(store), "HOME": str(tmp)}


def run(script, args, *, cwd, extra_env, stdin=None) -> subprocess.CompletedProcess:
    """Run a loop CLI by subprocess (`sys.executable scripts/<script> ...`)."""
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=str(cwd),
                          input=stdin, capture_output=True, text=True, encoding="utf-8",
                          env=env(extra_env), timeout=180, check=False)


def last_json(proc) -> dict:
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"no stdout (rc={proc.returncode}): {proc.stderr[-2000:]}"
    return json.loads(lines[-1])


class Loop:
    """One PR's loop paths: proof root, state, log (outside every worktree)."""

    def __init__(self, tmp, extra_env):
        self.root = Path(tmp) / "proof"
        self.state = self.root / "iterate-state.9.v1.json"
        self.log = self.root / "iterate-log.9.md"
        self.class_log = self.root / "class-log.9.md"
        self.env = extra_env

    def prepare(self, cwd, base, head) -> Path:
        p = run("round_scratch.py", ["prepare", "--root", str(self.root), "--pr-url", PR,
                                      "--base", base, "--head", head, "--state", str(self.state),
                                      "--log", str(self.log)], cwd=cwd, extra_env=self.env)
        assert p.returncode == 0, p.stdout + p.stderr
        return Path(p.stdout.strip())

    def reproduce(self, rd, cwd, head) -> subprocess.CompletedProcess:
        return run("reproduce.py", ["--round-dir", str(rd), "--cwd", str(cwd), "--head", head],
                   cwd=cwd, extra_env=self.env)

    def converge(self, rd, cwd, *extra) -> subprocess.CompletedProcess:
        return run("converge.py", ["--round-dir", str(rd), "--config", str(Path(cwd) / CONFIG),
                                   "--class-log-path", str(self.class_log), *extra],
                   cwd=cwd, extra_env=self.env)

    def run_round(self, rd, cwd, findings, *, config=True) -> subprocess.CompletedProcess:
        """The tail's blocking-round shell: tail findings + the manifest's identity."""
        m = manifest(rd)
        payload = {"state_path": m["paths"]["state_path"], "head_sha": m["head"],
                   "codereview_findings": findings, "reviewed": None,
                   "unresolved_actionable": 0, "ci_rollup": [], "pr_url": m["pr_url"],
                   "review_base": m["base"], "round": m["round"], "ordinal": m["ordinal"],
                   "class_log_path": str(self.class_log)}
        if config:  # else run_round.py reads the working-tree config from its cwd
            payload["config"] = json.loads((Path(cwd) / CONFIG).read_text(encoding="utf-8"))
        return run("run_round.py", [], cwd=cwd, extra_env=self.env, stdin=json.dumps(payload))

    def flush(self, cwd, decisions) -> dict:
        p = run("round_scratch.py", ["flush", "--log", str(self.log), "--decisions",
                                      str(decisions)], cwd=cwd, extra_env=self.env)
        assert p.returncode == 0, p.stderr
        return last_json(p)

    def read_state(self) -> dict:
        return json.loads(self.state.read_text(encoding="utf-8"))


def manifest(rd) -> dict:
    return json.loads((Path(rd) / "angles.json").read_text(encoding="utf-8"))


def blocking_finding(summary="real defect") -> dict:
    """A reviewer finding whose command reproducer violates its `expect` (reproduced)."""
    return {"file": "src/a.py", "line_range": [1, 1], "summary": summary, "class": "P",
            "blocking": True,
            "reproducer": {"kind": "command", "argv": [sys.executable, "-c",
                                                       "import sys; sys.exit(1)"],
                           "expect": {"exit": 0}}}


def write_replies(rd, first=CLEAN, *, drop=None) -> None:
    """First angle gets `first`, the rest a clean `[]`; `drop` = index left without a reply."""
    for i, e in enumerate(manifest(rd)["angles"]):
        if i == drop:
            continue
        text = first if i == 0 else CLEAN
        Path(e["reply_path"]).write_text(text, encoding="utf-8")


def reply(findings) -> str:
    return "```json\n" + json.dumps(findings) + "\n```\n"


def tail_findings(rd) -> list:
    return json.loads((Path(rd) / "tail" / "findings.json").read_text(encoding="utf-8"))


def write_envelope(rd, *, action, head_reviewed, head_after, terminal=None,
                   converged=False, budget=None) -> None:
    """A schema-valid round-tail.v1 envelope (what the tail subagent writes)."""
    b = budget or {}
    env_doc = {"schema": "tp-pr-iterate/round-tail/v1", "round": manifest(rd)["round"],
               "head_reviewed": head_reviewed, "head_after": head_after,
               "tally": {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 0},
               "downgraded": 0, "notes": 0, "action": action, "fix_commit": None,
               "terminal": terminal, "converged": converged,
               "budget": {"iteration": b.get("iteration", 0),
                          "round_cap": b.get("round_cap", 6), "signal": b.get("signal"),
                          "holding": list(b.get("holding") or [])},
               "summary": "itest"}
    write(Path(rd) / "tail", "envelope.json", json.dumps(env_doc))
