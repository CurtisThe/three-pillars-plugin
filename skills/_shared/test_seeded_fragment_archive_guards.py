"""A seeded design completes in fragment mode: its Design Inventory row cites `tp-designs/<slug>/seed.md`.

Tier 7 round-1 reproducer (PR #364, living-doc-fragments). In fragment mode `--archive-cites` writes
nothing (the branch never edits a shared living doc), so the archive guards must not fail on a cite the
post-merge docs compile repoints; and the compile must still leave that cite resolving.
Oracle: example. Assertions read exit codes and the dead-cite detector, never message wording.
"""
import os
import subprocess
import sys
from pathlib import Path

SH = Path(__file__).resolve().parent
VERIFY = SH.parent / "-".join(["tp", "design", "complete"]) / "scripts" / "verify_archive_staged.py"
if str(SH) not in sys.path:
    sys.path.insert(0, str(SH))


def git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _archive_seeded(tmp_path):
    """A repo whose tp/demo branch carries the fragment-mode `Complete design: demo` commit."""
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@e")
    git(root, "config", "user.name", "t")
    write(root, "three-pillars-docs/product_roadmap.md",
          "# Roadmap\n\n## Design Inventory\n\n| Design | What | Status |\n|---|---|---|\n"
          "| `demo` | a thing | Seeded — [seed](tp-designs/demo/seed.md) |\n")
    write(root, "three-pillars-docs/tp-designs/demo/seed.md", "seed\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "switch", "-q", "-c", "tp/demo")
    write(root, "three-pillars-docs/tp-designs/demo/design.md", "# demo\n")
    write(root, "three-pillars-docs/changes/demo.md",
          "---\nslug: demo\nkind: design\ndate: 2026-10-22\nlearned: 2026-10-22\n---\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "design + learn fragment")
    (root / "three-pillars-docs" / "completed-tp-designs").mkdir()
    git(root, "mv", "three-pillars-docs/tp-designs/demo", "three-pillars-docs/completed-tp-designs/demo")
    write(root, "three-pillars-docs/completed-tp-designs/demo/design.md", "---\ncompleted: 2026-10-22\n---\n# demo\n")
    write(root, "three-pillars-docs/completed-tp-designs/demo/lock.json", '{"phase": "cleanup-pending"}\n')
    subprocess.run([sys.executable, os.path.join(SH, "reconcile_docs.py"), "--archive-cites", "--slug", "demo",
                    "--apply", "--json", "--repo", str(root)], capture_output=True, text=True, check=True)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Complete design: demo")
    return root


def test_seeded_fragment_design_can_pass_the_archive_guards(tmp_path):
    root = _archive_seeded(tmp_path)
    guard = subprocess.run([sys.executable, os.path.join(SH, "living_doc_guard.py"), "check", "--base", "main",
                            "--repo-root", str(root)], capture_output=True, text=True)
    verify = subprocess.run([sys.executable, str(VERIFY), "--repo", str(root), "--slug", "demo"],
                            capture_output=True, text=True)
    assert guard.returncode == 0, guard.stdout + guard.stderr
    assert verify.returncode == 0, verify.stderr


def test_compile_after_merge_leaves_the_seed_cite_resolving(tmp_path):
    import citation_liveness
    import docs_compile

    root = _archive_seeded(tmp_path)
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "merge tp/demo", "tp/demo")
    result = docs_compile.compile_all(root, base_ref="main", prs={"demo": 7}, commit=True)
    assert result.commit, result
    assert [c for c in citation_liveness.dead_design_cites(root) if c.slug == "demo"] == []
