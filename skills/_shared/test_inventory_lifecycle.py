"""test_inventory_lifecycle.py — a design's inventory row and status end final
on the branch (design-complete-final-doc-state, Behaviors 1-3).

Drives a fixture repo through the lifecycle with the real CLIs each skill calls:
`/tp-design-learn` (writes `Completion PR pending` in the row, the Current State
bullet and the Recent-completions bullet, rolls History with `history_rollover.py`),
`/tp-design-complete` (`git mv`, the `archive_allowlist.py` plan + apply,
`reconcile_docs.py --archive-cites`, then `final_doc_state.py close`), the Tier 6
writeback (`reconcile_docs.py --pre-merge --pr`) and `/tp-post-merge` step 6
(`final_doc_state.py check`, verify-only). Oracles: example (the exact lines) and
metamorphic (a re-run of `close` or the writeback changes nothing), per
skills/_shared/test-fragility.md.

Run with: python3 -m pytest skills/_shared/test_inventory_lifecycle.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLUG = "lslug"
LIVE = "three-pillars-docs/product_roadmap.md"
ARCHIVE = "three-pillars-docs/product_roadmap_archive.md"
TP = f"three-pillars-docs/tp-designs/{SLUG}"
DONE = f"three-pillars-docs/completed-tp-designs/{SLUG}"
HEADER = "| Name | What | Type | Status | Track |"
DELIM = "|---|---|---|---|---|"
PENDING, NUMBERLESS, NUMBERED = "Completion PR pending", "Done (completion PR)", "Done — PR #177"
VERIFIED = {"verdict": "verified", "rows": [], "pending": [], "cites": [], "fix": []}
WRITEBACK = ("--slug", SLUG, "--pre-merge", "--pr", "177", "--apply", "--json")


def _env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True, env=_env())


def _commit(root, msg):
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=f", "-c", "user.email=f@t", "commit", "-q", "--allow-empty", "-m", msg)


def _run(root, script, *argv):
    return subprocess.run([sys.executable, str(HERE / script), *argv], cwd=root,
                          capture_output=True, text=True, env=_env())


def _tool(root, script, *argv):
    r = _run(root, script, *argv)
    assert r.returncode == 0, f"{script}: {r.stdout}{r.stderr}"
    return r.stdout


def _roadmap(bullets, state, rows):
    return "\n".join([
        "# Product Roadmap", "",
        "## Current Focus — seeds", "",
        "### Recent completions", *bullets, "",
        "*Older completions: see the archive.*", "",
        "## Current State", "", state, "",
        "## Design Inventory", "",
        "### Active (canon-reframe arc)", "",
        HEADER, DELIM, *rows, "",
        "## Roadmap History", "",
        "- **2026-09-01** — seeded the roadmap.", "",
    ]) + "\n"


def _learn(root):
    """`/tp-design-learn`: the three pending-text lines it writes, then the History rollover."""
    row = f"| {SLUG} | Lifecycle fixture. | design | {PENDING} — [design]({TP}/design.md) | Docs |"
    state = f"- Lifecycle fixture shipped (`{SLUG}`, 2026-09-28; {PENDING})."
    bullet = f"- **`{SLUG}`** — {PENDING} (2026-09-28) — [design]({TP}/design.md)"
    bullets = [bullet] + [f"- **`old{i}`** — merged (2026-09-0{i})" for i in (4, 3, 2, 1)]
    (root / LIVE).write_text(_roadmap(bullets, state, [
        "| other | Stays live. | design | Seed | Docs |", row]), encoding="utf-8")
    _tool(root, "history_rollover.py", "--doc", LIVE, "--repo-root", str(root))
    _commit(root, "Learn: lslug design")
    return {"row": row, "state": state, "bullet": bullet}


def _design_complete(root):
    """`/tp-design-complete` in its order: 6c `git mv`, 6e2 prune, 6f cite rewrite, then `close`."""
    (root / DONE).parent.mkdir(parents=True, exist_ok=True)
    _git(root, "mv", TP, DONE)
    plan = json.loads(_tool(root, "archive_allowlist.py", "plan", "--design-dir", DONE,
                            "--json", "--repo-root", str(root)))
    assert plan["drop"] == [f"{DONE}/demos/run.log"]
    _tool(root, "archive_allowlist.py", "apply", "--design-dir", DONE, "--repo-root", str(root))
    _tool(root, "reconcile_docs.py", "--repo", str(root), "--slug", SLUG,
          "--archive-cites", "--apply", "--json")
    _tool(root, "final_doc_state.py", "close", "--slug", SLUG, "--repo-root", str(root))
    _commit(root, "chore: complete lslug")


def _check(root):
    """`/tp-post-merge` step 6: `(exit code, payload)` of the read-only self-check."""
    r = _run(root, "final_doc_state.py", "check", "--slug", SLUG, "--repo-root", str(root), "--json")
    return r.returncode, json.loads(r.stdout)


def _lines(root, rel):
    return (root / rel).read_text(encoding="utf-8").splitlines()


def _fixture(root):
    _git(root, "init", "-q", "-b", "master")
    for rel, text in ((f"{TP}/design.md", "# d\n"), (f"{TP}/decisions.md", "# log\n"),
                      (f"{TP}/demos/run.log", "scratch\n"),
                      ("three-pillars-docs/completed-tp-designs/other/design.md", "# o\n")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return _learn(root)


def test_row_and_status_end_final_on_the_branch(tmp_path):
    learned = _fixture(tmp_path)
    _design_complete(tmp_path)

    # Behavior 1: no live row at the head; the archive holds it, number-free, cite re-pointed.
    done_form = {k: v.replace(PENDING, NUMBERLESS).replace(TP, DONE) for k, v in learned.items()}
    live, archive = _lines(tmp_path, LIVE), _lines(tmp_path, ARCHIVE)
    assert not [ln for ln in live if ln.startswith(f"| {SLUG} |")]
    assert archive.count(done_form["row"]) == 1 and "| other | Stays live. | design | Seed | Docs |" in live
    assert done_form["state"] in live and done_form["bullet"] in live
    assert not [ln for ln in live + archive if PENDING in ln]
    assert _check(tmp_path) == (0, VERIFIED)

    # Behavior 2: the Tier 6 writeback puts the real number everywhere the token was.
    _tool(tmp_path, "reconcile_docs.py", "--repo", str(tmp_path), *WRITEBACK)
    _commit(tmp_path, "docs: completion PR number")
    live, archive = _lines(tmp_path, LIVE), _lines(tmp_path, ARCHIVE)
    assert done_form["row"].replace(NUMBERLESS, NUMBERED) in archive
    assert done_form["state"].replace(NUMBERLESS, NUMBERED) in live
    assert done_form["bullet"].replace(NUMBERLESS, NUMBERED) in live
    assert not [ln for ln in live + archive if NUMBERLESS in ln or PENDING in ln]

    # Behavior 3: merged, the self-check reports verified and writes nothing.
    assert _check(tmp_path) == (0, VERIFIED)
    assert _git(tmp_path, "status", "--porcelain").stdout == ""


def test_rerunning_close_and_the_writeback_is_a_noop(tmp_path):
    _fixture(tmp_path)
    _design_complete(tmp_path)
    again = json.loads(_tool(tmp_path, "final_doc_state.py", "close", "--slug", SLUG,
                             "--repo-root", str(tmp_path), "--json"))
    assert (again["moved"], again["flipped"], again["paths"], again["refused"]) == (0, 0, [], None)
    assert _git(tmp_path, "status", "--porcelain").stdout == ""

    _tool(tmp_path, "reconcile_docs.py", "--repo", str(tmp_path), *WRITEBACK)
    _commit(tmp_path, "docs: completion PR number")
    _tool(tmp_path, "reconcile_docs.py", "--repo", str(tmp_path), *WRITEBACK)
    assert _git(tmp_path, "status", "--porcelain").stdout == ""
