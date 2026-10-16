"""test_post_merge_inventory_wiring.py — post-merge step 6 verifies and writes nothing.

`/tp-post-merge` step 6 is verify-only: it runs `final_doc_state.py check` (the
living docs reached their final shape in the design PR, so a merge needs no
follow-up docs commit). This test takes the shipped command verbatim from the
step's fenced blocks and runs it in a fixture repo. A merged fixture (row already
archived, `Done — PR #177`) must report `verified` and leave `git status` clean;
a pre-change fixture (row still live, `Completion PR pending`) must report
`drift` with fix lines, exit 1 and still change no file. The step's fenced blocks
hold no `git add` and no `git commit`. The prose around the command is not pinned.

design: design-complete-final-doc-state

Run with: python3 -m pytest skills/_shared/test_post_merge_inventory_wiring.py -q
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "tp-post-merge" / "SKILL.md"
SLUG = "merged-slug"
DOCS = "three-pillars-docs"
LIVE = f"{DOCS}/product_roadmap.md"
ARCHIVE = f"{DOCS}/product_roadmap_archive.md"
HEAD = ["| Name | What | Type | Status | Track |", "|---|---|---|---|---|"]
MERGED_ROW = f"| {SLUG} | Merged fixture. | design | Done — PR #177 | Docs |"
PENDING_ROW = f"| {SLUG} | Merged fixture. | design | Completion PR pending | Docs |"


def _env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=f", "-c",
                           "user.email=f@t", *args], capture_output=True,
                          text=True, check=True, env=_env())


def _step6_fences() -> list[str]:
    """Every line of step 6's fenced bash blocks (before step 6.5)."""
    text = SKILL.read_text(encoding="utf-8")
    m = re.search(r"^6\. \*\*Doc-reconcile.*?(?=^6\.5\. )", text, re.DOTALL | re.MULTILINE)
    assert m, "tp-post-merge step 6 (Doc-reconcile) not found"
    return [line.strip() for fence in re.findall(r"```bash\n(.*?)```", m.group(0), re.DOTALL)
            for line in fence.splitlines()]


def _step6_commands() -> str:
    """The one `final_doc_state.py check` line from step 6; step 6 writes nothing."""
    lines = _step6_fences()
    writes = [line for line in lines if re.match(r"git\s+(add|commit)\b", line)]
    assert writes == [], f"step 6 must stage and commit nothing, got {writes}"
    checks = [line for line in lines if "final_doc_state.py check" in line]
    assert len(checks) == 1, f"step 6 must run final_doc_state.py check once, got {checks}"
    return checks[0]


def _shipped(command: str) -> list[str]:
    """The shipped line as an argv, its placeholders bound to this checkout
    and fixture. No shell: the line must carry no shell syntax beyond quoting."""
    command = command.replace('"$TP_ROOT"', shlex.quote(str(REPO_ROOT)))
    command = command.replace("{name}", SLUG)
    argv = shlex.split(command)
    if argv[:1] == ["python3"]:
        argv[0] = sys.executable
    return argv


def _fixture(root: Path, *, live: list[str], archived: list[str]) -> None:
    _git(root, "init", "-q", "-b", "master")
    done = root / DOCS / "completed-tp-designs" / SLUG
    done.mkdir(parents=True)
    (done / "design.md").write_text("# d\n", encoding="utf-8")
    inventory = ["# Product Roadmap", "", "## Design Inventory", "", "### Active", "", *HEAD,
                 "| other | Stays live. | design | Seed | Docs |", *live, ""]
    (root / LIVE).write_text("\n".join(inventory) + "\n", encoding="utf-8")
    completed = ["# Roadmap Archive", "", "## Design Inventory — completed and superseded rows",
                 "", *HEAD, *archived, ""]
    (root / ARCHIVE).write_text("\n".join(completed) + "\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "merged")


def _run_step6(root: Path):
    return subprocess.run(_shipped(_step6_commands()), cwd=root,
                          capture_output=True, text=True, env=_env())


def test_step_6_verifies_and_writes_nothing(tmp_path):
    _fixture(tmp_path, live=[], archived=[MERGED_ROW])

    r = _run_step6(tmp_path)

    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["verdict"] == "verified"
    assert _git(tmp_path, "status", "--porcelain").stdout == ""


def test_step_6_reports_drift_on_a_pre_change_branch(tmp_path):
    _fixture(tmp_path, live=[PENDING_ROW], archived=[])

    r = _run_step6(tmp_path)

    assert r.returncode == 1, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["verdict"] == "drift"
    assert payload["fix"], "drift must carry the fix commands"
    assert _git(tmp_path, "status", "--porcelain").stdout == ""
