"""test_docs_compile_number.py — Task 1.4: numbering and rollovers inside the one compile commit.

design: living-doc-fragments, Task 1.4 (§Interfaces steps 2-3). Real temp git repos; assertions are
exact text and path sets (Oracle: example), never message wording (test-fragility.md §2).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import docs_compile  # noqa: E402
from test_docs_compile import ARCH, CH, KI, ROADMAP, ROADMAP_TEXT, frag, git, make_repo  # noqa: E402

ADD = ("\n## Roadmap\n\n### Current Focus\n+ - cites {cite}\n\n## Known issues — add\n\n"
       "### {cite}: title {slug}\nbody of {slug}\n")


def _two():
    return {s: frag(s, d, ADD.format(cite=c, slug=s)) for s, d, c in
            (("alpha", "2020-01-02", "M-new-a"), ("beta", "2020-01-03", "M-new-b"))}


def test_placeholders_numbered_against_base(tmp_path):
    root = make_repo(tmp_path, _two())
    base = git(root, "rev-parse", "HEAD")
    docs_compile.compile_all(root, base_ref=base, prs={}, commit=True)
    ki = (root / KI).read_text(encoding="utf-8")
    assert "### M52: title alpha\nbody of alpha\n" in ki
    assert "### M53: title beta\nbody of beta\n" in ki
    road = (root / ROADMAP).read_text(encoding="utf-8")
    assert "- cites M52\n" in road and "- cites M53\n" in road
    assert "-new-" not in ki + road


def test_two_fragments_get_distinct_numbers(tmp_path):
    root = make_repo(tmp_path, _two())
    base = git(root, "rev-parse", "HEAD")
    docs_compile.compile_all(root, base_ref=base, prs={}, commit=True)
    ki = (root / KI).read_text(encoding="utf-8")
    ids = [line.split(":")[0] for line in ki.splitlines() if line.startswith("### M")]
    assert sorted(ids) == ["### M51", "### M52", "### M53"] and len(set(ids)) == 3


def test_history_and_cap_rollover_run_per_touched_doc(tmp_path):
    entries = "".join(f"- **2019-01-{n:02d}** — entry {n:02d} {'x' * 900}\n" for n in range(1, 21))
    entries = "".join(sorted(entries.splitlines(keepends=True), reverse=True))  # newest first
    fat = ROADMAP_TEXT.replace("- **2019-05-05** — older entry\n", entries)
    assert len(fat) > 10000
    fragments = {"alpha": frag("alpha", "2020-01-02", "\n## Roadmap\n\n### Current Focus\n+ - alpha focus\n")}
    root = make_repo(tmp_path, fragments, docs={ROADMAP: fat})
    base = git(root, "rev-parse", "HEAD")
    docs_compile.compile_all(root, base_ref=base, prs={}, commit=True)
    live = (root / ROADMAP).read_text(encoding="utf-8")
    archive = (root / "three-pillars-docs/product_roadmap_archive.md").read_text(encoding="utf-8")
    assert len(live) <= 10000
    assert "entry 01 " in archive and "entry 01 " not in live
    assert "entry 20 " in live
    changed = set(git(root, "diff", "--name-only", base, "HEAD").splitlines())
    assert changed == {ROADMAP, "three-pillars-docs/product_roadmap_archive.md", f"{CH}/alpha.md"}
    assert git(root, "status", "--porcelain") == "" and ARCH not in changed
