"""test_docs_compile.py — Task 1.4: `docs_compile.compile_all` folds, deletes and commits once.

design: living-doc-fragments, Task 1.4 (§Interfaces steps 1-3 and 5). Every test runs in a real temp
git repo (a base commit with living docs plus fragments). Assertions compare git trees, changed-path
sets and exact text (Oracle: example, metamorphic), never the wording of a message
(test-fragility.md §2). Numbering and rollover live in test_docs_compile_number.py.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

import docs_compile  # noqa: E402

ROADMAP = "three-pillars-docs/product_roadmap.md"
ARCH = "three-pillars-docs/architecture.md"
KI = "three-pillars-docs/known_issues.md"
CH = "three-pillars-docs/changes"

ROADMAP_TEXT = """# Product Roadmap
*Last updated: 2019-05-05 — see [History](#roadmap-history) for the full changelog.*

## Current Focus
- focus one

## Design Inventory
| a | row |

## Roadmap History

*Newest-first. One line per update.*
- **2019-05-05** — older entry
"""
ARCH_TEXT = "# Architecture\n*Last updated: 2019-05-05 — see [History](#history).*\n\n## Key\n### Dist\n- one\n\n## History\n- **2019-05-05** — first\n"
KI_TEXT = "# Known Issues\n\n## Critical / High\n\n## Medium\n\n### M51: old\nbody\n\n## Low\n"


def frag(slug: str, date: str, body: str = "") -> str:
    return f"---\nslug: {slug}\nkind: design\ndate: {date}\n---\n{body}"


def git(root, *args) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def make_repo(tmp_path, fragments: dict, docs: dict | None = None, name="repo"):
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    files = {ROADMAP: ROADMAP_TEXT, ARCH: ARCH_TEXT, KI: KI_TEXT}
    files.update(docs or {})
    files.update({f"{CH}/{slug}.md": text for slug, text in fragments.items()})
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


TWO = {
    "alpha": frag("alpha", "2020-01-02", "\n## Roadmap\n\n### Current Focus\n+ - alpha focus\n"),
    "beta": frag("beta", "2020-01-03", "\n## Architecture\n\n### Dist\n+ - beta bullet\n"),
}


def test_folded_fragments_are_deleted_in_the_same_commit(tmp_path):
    root = make_repo(tmp_path, TWO)
    base = git(root, "rev-parse", "HEAD")
    result = docs_compile.compile_all(root, base_ref=base, prs={"alpha": 7}, commit=True)
    assert git(root, "rev-list", "--count", f"{base}..HEAD") == "1"
    changed = set(git(root, "diff", "--name-only", base, "HEAD").splitlines())
    assert changed == {ROADMAP, ARCH, f"{CH}/alpha.md", f"{CH}/beta.md"}
    assert git(root, "status", "--porcelain") == ""
    assert sorted(result.folded) == ["alpha", "beta"] and result.conflicts == []
    assert result.commit == git(root, "rev-parse", "HEAD")
    assert "- alpha focus\n" in (root / ROADMAP).read_text(encoding="utf-8")
    assert "- beta bullet\n" in (root / ARCH).read_text(encoding="utf-8")
    assert not (root / CH / "alpha.md").exists()


def test_same_fragments_same_base_same_bytes(tmp_path):
    first = make_repo(tmp_path, TWO, name="one")
    second = tmp_path / "two"
    shutil.copytree(first, second)
    base = git(first, "rev-parse", "HEAD")
    docs_compile.compile_all(first, base_ref=base, prs={}, commit=True)
    docs_compile.compile_all(second, base_ref=base, prs={}, commit=True)
    assert git(first, "rev-parse", "HEAD^{tree}") == git(second, "rev-parse", "HEAD^{tree}")


def test_vision_fragment_is_cut_to_vision(tmp_path):
    body = "\n## Roadmap\n\n### Current Focus\n+ - v focus\n\n## Vision\n\nWiden the scope.\n"
    root = make_repo(tmp_path, {"vis": frag("vis", "2020-01-02", body)})
    base = git(root, "rev-parse", "HEAD")
    docs_compile.compile_all(root, base_ref=base, prs={}, commit=True)
    kept = (root / CH / "vis.md").read_text(encoding="utf-8")
    assert kept == frag("vis", "2020-01-02", "\n## Vision\n\nWiden the scope.\n")
    assert "- v focus\n" in (root / ROADMAP).read_text(encoding="utf-8")


def test_plan_mode_writes_nothing(tmp_path):
    root = make_repo(tmp_path, TWO)
    base = git(root, "rev-parse", "HEAD")
    result = docs_compile.compile_all(root, base_ref=base, prs={})
    assert sorted(result.folded) == ["alpha", "beta"] and result.commit is None
    assert git(root, "rev-parse", "HEAD") == base
    assert git(root, "status", "--porcelain") == ""
    assert (root / CH / "alpha.md").exists()


def test_dirty_tree_exits_3(tmp_path, capsys):
    root = make_repo(tmp_path, TWO)
    base = git(root, "rev-parse", "HEAD")
    (root / ARCH).write_text("dirty\n", encoding="utf-8")
    rc = docs_compile.main(["--base" + "-ref", base, "--commit", "--repo-root", str(root)])
    assert rc == 3
    assert git(root, "rev-parse", "HEAD") == base
    assert (root / ARCH).read_text(encoding="utf-8") == "dirty\n"
    assert (root / CH / "alpha.md").exists()
