"""embedded_framework.py -- small hermetic fixture helper for the Phase 8 end-to-end
dispatch-from-seat ACTIVATION tests (test_carry_activation_e2e.py, tasks 8.5/8.6).

Builds an embedded-framework fixture on top of `base_sync_repo.build_scenario` (which
clones THIS checkout's current branch, so the fixture's seat carries the live gate
module set verbatim -- no separate file-copy step needed): a seat (primary worktree on
the base branch -- fixture-14's accepted topology), a `*-wt/{name}` design worktree
containing a certified AUTO-SAFE base-sync merge, an `origin` remote reshaped to a
`git@github.com:...` URL redirected OFFLINE via a `GIT_SSH_COMMAND` wrapper (so the
config-root binding check's `git remote get-url origin` sees a real, parseable GitHub
owner/repo), a `gh` PATH shim emitting the fixture's canned PR-state/reviews/threads JSON
(the REAL `gh` is never invoked), and carry config committed into the design branch's
history (an ancestor of every head built afterward).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from base_sync_repo import (  # noqa: E402
    LIVING_DOC_PATH,
    ScenarioRepo,
    build_scenario,
    diverge_living_doc,
    make_certified_sync_merge,
)
from base_sync_topologies import add_design_worktree  # noqa: E402

OWNER = "acme"
REPO = "widgets"
PR_NUMBER = "1"
PR_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PR_NUMBER}"
SELF_LOGIN = "framework-bot"
REVIEWER_LOGIN = "human-reviewer"

CARRY_CONFIG = {
    "review": {
        "approval_survives_safe_base_sync": True,
        "expects_copilot": False,
        "require_review_proof": False,
    },
    "ci": {"expects_github_checks": False},
}


def _run(args: list, cwd, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check)


def _write_ssh_wrapper(root: Path, origin_dir: Path) -> Path:
    """A `GIT_SSH_COMMAND` replacement redirecting the `git@github.com:...` scp-style ssh
    transport DIRECTLY to a local `git upload-pack/receive-pack <origin_dir>` call --
    fully offline, no network, no DNS.

    WHY THIS (not `url.<local>.insteadOf <github-url>`): `git remote get-url` EXPANDS
    insteadOf mappings before printing (verified live) -- an insteadOf-redirected remote
    would make `git remote get-url origin` print the LOCAL PATH, not the `github.com` URL
    evaluate_gate's config-root binding check needs to parse (W4). The `GIT_SSH_COMMAND`
    wrapper redirects the TRANSPORT (what actually connects) instead, leaving the
    stored/displayed URL string untouched -- `git remote get-url origin` prints the
    literal `git@github.com:...` string verbatim, while `git fetch` resolves fully
    offline through this wrapper.
    """
    script = root / "ssh-wrap.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "${1:-}" == "-G" ]]; then exit 1; fi\n'
        'last="${@: -1}"\n'
        'cmd="${last%% *}"\n'
        'rest="${last#* }"\n'
        "path=\"${rest//\\'/}\"\n"
        'case "$cmd" in\n'
        f'  git-upload-pack) exec git upload-pack "{origin_dir}" ;;\n'
        f'  git-receive-pack) exec git receive-pack "{origin_dir}" ;;\n'
        f'  git-upload-archive) exec git upload-archive "{origin_dir}" ;;\n'
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


_GH_SHIM = '''#!/usr/bin/env python3
"""PATH-shim for `gh` -- routes to the fixture's canned JSON. The REAL gh is never
invoked (offline, hermetic). FIXTURE_HEAD_OID varies per subprocess invocation via env
so one shim serves every scenario (honest / negative-control / tampered) with a fixed
review anchor."""
import json
import os
import sys

argv = sys.argv[1:]
HEAD_OID = os.environ.get("FIXTURE_HEAD_OID", "{default_head_oid}")
BASE_REF = "{base_ref}"
SELF_LOGIN = "{self_login}"
REVIEWER_LOGIN = "{reviewer_login}"
REVIEW_COMMIT_ID = "{review_commit_id}"


def _is_pr_view():
    return len(argv) >= 2 and argv[0] == "pr" and argv[1] == "view"


if _is_pr_view() and "--json" in argv:
    fields = argv[argv.index("--json") + 1]
    if "statusCheckRollup" in fields:
        print(json.dumps({{"mergeable": "MERGEABLE", "headRefOid": HEAD_OID, "statusCheckRollup": []}}))
        sys.exit(0)
    if fields == "baseRefName":
        print(json.dumps({{"baseRefName": BASE_REF}}))
        sys.exit(0)
    if "commits" in fields:
        print(json.dumps({{"headRefOid": HEAD_OID, "commits": []}}))
        sys.exit(0)
    print(json.dumps({{}}))
    sys.exit(0)

if len(argv) >= 2 and argv[0] == "api" and argv[1] == "user":
    print(SELF_LOGIN)
    sys.exit(0)

if len(argv) >= 2 and argv[0] == "api" and argv[1] == "graphql":
    print(json.dumps({{"data": {{"repository": {{"pullRequest": {{"reviewThreads": {{"nodes": []}}}}}}}}}}))
    sys.exit(0)

if len(argv) >= 2 and argv[0] == "api" and "/reviews" in argv[1]:
    print(json.dumps([
        {{"user": {{"login": REVIEWER_LOGIN, "type": "User"}}, "state": "APPROVED",
         "commit_id": REVIEW_COMMIT_ID, "submitted_at": "2026-01-01T00:00:00Z"}}
    ]))
    sys.exit(0)

sys.exit(1)
'''


def _write_gh_shim(root: Path, *, default_head_oid: str, base_ref: str, review_commit_id: str) -> Path:
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    shim = bin_dir / "gh"
    shim.write_text(_GH_SHIM.format(
        default_head_oid=default_head_oid, base_ref=base_ref,
        self_login=SELF_LOGIN, reviewer_login=REVIEWER_LOGIN,
        review_commit_id=review_commit_id,
    ), encoding="utf-8")
    shim.chmod(0o755)
    return bin_dir


@dataclass
class EmbeddedFixture:
    """The 8.5/8.6 shared fixture handle."""
    scenario: ScenarioRepo
    seat: Path              # primary worktree, checked out on base_ref (fixture-14 topology)
    design_wt: Path          # *-wt/{name}, HEAD == h1 (certified AUTO-SAFE merge)
    h0: str                  # pre-sync head -- the review's anchor commit_id
    h1: str                  # post-sync certified merge head
    base_ref: str
    gh_bin_dir: Path
    ssh_wrapper: Path
    pr_url: str = PR_URL

    def env(self, *, head_oid: "str | None" = None) -> dict:
        """Build the subprocess env for a gate_cli.py/land.py invocation: real PATH with
        the gh-shim dir prepended, GIT_SSH_COMMAND wired to the offline redirect,
        FIXTURE_HEAD_OID set for THIS invocation (defaults to h1, the honest head)."""
        env = dict(os.environ)
        env["PATH"] = f"{self.gh_bin_dir}:{env.get('PATH', '')}"
        env["GIT_SSH_COMMAND"] = str(self.ssh_wrapper)
        env["FIXTURE_HEAD_OID"] = head_oid or self.h1
        return env

    def gate_cli_argv(self, *, code_root, repo_root) -> list:
        """The documented step-6.7 invocation: python3 <code_root>/skills/tp-merge-from-main/
        scripts/gate_cli.py --repo <repo_root> <pr_url>."""
        return [
            sys.executable,
            str(Path(code_root) / "skills" / "tp-merge-from-main" / "scripts" / "gate_cli.py"),
            "--repo", str(repo_root),
            self.pr_url,
        ]


def build_embedded_fixture(tmp_path, monkeypatch) -> EmbeddedFixture:
    """The 8.5/8.6 shared fixture builder. See module docstring for the full topology."""
    s = build_scenario(tmp_path)

    # Seed the carry config EARLY -- an ancestor of both h0 and h1, so `git show
    # <any-descendant>:.three-pillars/config.json` resolves it via the tree walk (a
    # committed-HEAD read walks the FULL tree at that commit, not just its own diff).
    cfg_dir = s.repo_dir / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(CARRY_CONFIG), encoding="utf-8")
    _run(["add", "-A"], s.repo_dir)
    _run(["commit", "-q", "-m", "fixture: seed carry config"], s.repo_dir)

    # Redirect the origin remote to a git@github.com:-shaped URL, offline (see
    # _write_ssh_wrapper's docstring for why insteadOf can't be used here). Active for
    # the rest of fixture build via monkeypatch (auto-reverts at test teardown); the
    # eventual gate_cli.py subprocess gets its OWN explicit env via EmbeddedFixture.env().
    ssh_wrapper = _write_ssh_wrapper(Path(tmp_path), s.origin_dir)
    monkeypatch.setenv("GIT_SSH_COMMAND", str(ssh_wrapper))
    _run(["remote", "set-url", "origin", f"git@github.com:{OWNER}/{REPO}.git"], s.repo_dir)

    # A REAL conflicted AUTO-SAFE divergence (not a clean no-op merge) -- both sides
    # change the living doc's last line differently, so make_certified_sync_merge
    # invokes the actual shared resolver, representative of a real base-sync merge.
    # h0 is captured AFTER diverge_living_doc's own design-side commit (mirrors
    # test_attack2's usage) so it is h1's DIRECT first parent -- a single-hop chain;
    # capturing it before would insert an intervening plain commit between h0 and h1,
    # which the certified-chain walk correctly refuses (attack 6's own protection:
    # only merge commits are valid links) rather than a bug in this fixture's intent.
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)

    design_wt = add_design_worktree(s, name="feature")   # tp/feature @ h1

    sys.path.insert(0, str(HERE.parent))  # skills/_shared, for ci_local_stamp
    import ci_local_stamp
    ci_local_stamp.write_stamp(design_wt)

    # Seat: repo_dir switches onto base_ref (fixture-14's accepted topology) -- h1 stays
    # safely reachable via tp/feature in design_wt, decoupled from repo_dir's own HEAD.
    _run(["fetch", "-q", "origin", s.base_ref], s.repo_dir)
    _run(["checkout", "-q", "-B", s.base_ref, f"origin/{s.base_ref}"], s.repo_dir)

    gh_bin_dir = _write_gh_shim(
        Path(tmp_path), default_head_oid=h1, base_ref=s.base_ref, review_commit_id=h0,
    )

    return EmbeddedFixture(
        scenario=s, seat=s.repo_dir, design_wt=design_wt, h0=h0, h1=h1,
        base_ref=s.base_ref, gh_bin_dir=gh_bin_dir, ssh_wrapper=ssh_wrapper,
    )


def build_tampered_sibling(fixture: EmbeddedFixture, *, name: str = "tampered") -> "tuple[Path, str]":
    """Attack 8's fixture half (task 8.6): a SIBLING `*-wt/{name}` worktree off
    `fixture.h0`, whose OWN copy of the living doc diverges (own last-line edit) so
    merging `origin/<base>` (already advanced by the honest side's `diverge_living_doc`)
    produces a REAL conflict, then hand-crafts the resolution to content that byte-differs
    from what the honest resolver would produce for that SAME conflict shape (mirrors
    `test_attack2_hand_resolution_byte_inequality_yet_verify_clean`'s technique). An
    unmodified sibling would auto-merge cleanly and never reach condition 5's
    byte-equality check at all -- the own-side divergence is load-bearing.

    Returns (worktree_path, h1_bad) -- the tampered worktree's own doubly-diverged HEAD.
    """
    s = fixture.scenario
    tampered_wt = add_design_worktree(s, name=name, ref=fixture.h0)

    _run(["fetch", "-q", "origin", fixture.base_ref], tampered_wt)
    doc = tampered_wt / LIVING_DOC_PATH
    lines = doc.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[-1] = "### Z1: tampered-side change\n"
    doc.write_text("".join(lines), encoding="utf-8")
    _run(["add", "--", LIVING_DOC_PATH], tampered_wt)
    _run(["commit", "-q", "-m", "tampered: own divergence"], tampered_wt)

    # --no-commit --no-ff always leaves the index staged for us to overwrite, whether
    # git auto-merges cleanly or conflicts (check=False: either outcome is fine here).
    _run(["merge", "--no-commit", "--no-ff", f"origin/{fixture.base_ref}"], tampered_wt, check=False)
    hand_resolved = (
        "# Fixture Living Doc\n\n"
        "### Z0: seed entry\nseed body line.\n"
        "### Zx: TAMPERED hand-resolution (never reproduced by the honest resolver)\n"
    )
    doc.write_text(hand_resolved, encoding="utf-8")
    _run(["add", "--", LIVING_DOC_PATH], tampered_wt)
    _run(["commit", "-q", "-m", "tampered: forced merge resolution"], tampered_wt)
    h1_bad = _run(["rev-parse", "HEAD"], tampered_wt).stdout.strip()
    return tampered_wt, h1_bad
