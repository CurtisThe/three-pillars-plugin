"""test_certify_issues_fragment.py — `certify_issues.apply_to_fragment` and `issues apply --fragment`.

design: living-doc-fragments, Task 1.12. Oracle: example. A design branch never edits a living doc, so
the certification's pending issues go under the fragment's `## Known issues — add` instead. Every case
builds its own docs on `tmp_path` and reads the result back through the real fragment grammar
(`changes_fragment.parse`); no skill prose is read (skills/_shared/test-fragility.md).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import certify_issues  # noqa: E402
import changes_fragment as cf  # noqa: E402
import low_doc_parts  # noqa: E402

ADD = "Known issues — add"
FM = "---\nslug: demo\nkind: design\ndate: 2026-10-22\n---\n"
KNOWN = "# Known Issues\n\n## Critical / High\n\n### H1: something\n\n## Medium\n\n### M3: an open one\n\nbody\n\n## Low\n"
RESOLVED = "# Resolved\n\n### M9 (RESOLVED 2026-01-01): an old one\n"
IDS = ["M-new-cert-sweep-01-s2", "M-new-cert-sweep-01-s3", "M-new-cert-self-c2", "M-new-cert-self-c4"]


def _entry(cid: str, status: str) -> dict:
    return {"id": cid, "status": status, "reasons": [], "guard": f"g/{cid}.py::t",
            "evidence": {"red": [{"rc": 0, "tail": "1 passed"}], "green": []}}


def _result(name: str, entries: list[dict]) -> dict:
    return {"complete": True, "name": name, "sha": "a" * 40, "disposition": "ledger", "claims": entries}


SWEEP = _result("sweep-01", [_entry("s1", "binds"), _entry("s2", "not-binding"), _entry("s3", "false-red")])
SELF = _result("self", [_entry("c1", "binds"), _entry("c2", "unver" + "ified"), _entry("c4", "not-binding")])
PENDING = certify_issues.render([SWEEP], SELF)


def _docs(tmp_path: Path) -> tuple[Path, Path]:
    """`three-pillars-docs/` with its issue docs and an empty `changes/`; returns (known_issues, fragment)."""
    docs = tmp_path / "three-pillars-docs"
    (docs / "changes").mkdir(parents=True)
    (docs / "known_issues.md").write_text(KNOWN, encoding="utf-8")
    (docs / "known_issues_resolved.md").write_text(RESOLVED, encoding="utf-8")
    return docs / "known_issues.md", docs / "changes" / "demo.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _blocks(path: Path) -> list[cf.Block]:
    fragment = cf.parse(_text(path), stem=path.stem)
    assert cf.validate(fragment) == [], [cf.format_problem(p) for p in cf.validate(fragment)]
    return fragment.sections.get(ADD, [])


def test_apply_to_fragment_files_under_known_issues_add(tmp_path):
    known, fragment = _docs(tmp_path)
    fragment.write_text(FM, encoding="utf-8")
    ids = certify_issues.apply_to_fragment(PENDING, fragment, known)
    assert ids == IDS
    blocks = _blocks(fragment)
    assert [b.heading.split(":")[0] for b in blocks] == IDS
    assert [certify_issues.keys_in(b.heading) for b in blocks] == [
        ["sweep-01#s2"], ["sweep-01#s3"], ["self#c2"], ["self#c4"]]
    # the block text is today's pending text, byte for byte, under its minted placeholder
    expected = PENDING.split("\n\n", 1)[1]
    for pid in IDS:
        expected = expected.replace(f"### {certify_issues.PLACEHOLDER}:", f"### {pid}:", 1)
    body = _text(fragment).split(f"## {ADD}\n\n", 1)[1]
    assert body.strip() == expected.strip()
    assert _text(fragment).startswith(FM)


def test_apply_to_fragment_writes_no_living_doc(tmp_path):
    known, fragment = _docs(tmp_path)
    low = known.parent / Path(low_doc_parts.PART_RELS[0]).name
    low.write_text("# Low\n\n### L1: a low one\n", encoding="utf-8")
    docs = [known, known.parent / "known_issues_resolved.md", low]
    before = {p: p.read_bytes() for p in docs}
    tree = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    certify_issues.apply_to_fragment(PENDING, fragment, known)
    assert {p: p.read_bytes() for p in docs} == before
    assert {p.relative_to(tmp_path) for p in tmp_path.rglob("*")} - tree == {fragment.relative_to(tmp_path)}


def test_apply_to_fragment_dedupes_against_docs_and_fragment(tmp_path):
    known, fragment = _docs(tmp_path)
    docs = known.parent
    # s2 is filed in the live doc, c2 in a Low part, c4 in the resolved archive, s3 in the fragment itself
    known.write_text(KNOWN.replace("### M3:", "### M-new-x: filed [certification sweep-01#s2]\n\n### M3:"),
                     encoding="utf-8")
    (docs / Path(low_doc_parts.PART_RELS[0]).name).write_text(
        "# Low\n\n### L1: low [certification self#c2]\n", encoding="utf-8")
    (docs / "known_issues_resolved.md").write_text(
        RESOLVED + "\n### M8 (RESOLVED 2026-01-01): old [certification self#c4]\n", encoding="utf-8")
    fragment.write_text(FM + f"\n## {ADD}\n\n### M-new-y: mine [certification sweep-01#s3]\n\nbody\n", encoding="utf-8")
    before = _text(fragment)
    assert certify_issues.apply_to_fragment(PENDING, fragment, known) == []
    assert _text(fragment) == before  # nothing new: the fragment is not rewritten
    # a placeholder the fragment already heads is never minted twice; a re-run adds nothing
    fragment.write_text(FM + f"\n## {ADD}\n\n### M-new-cert-sweep-01-s2: other entry\n\nbody\n", encoding="utf-8")
    known.write_text(KNOWN, encoding="utf-8")
    (docs / "known_issues_resolved.md").write_text(RESOLVED, encoding="utf-8")
    (docs / Path(low_doc_parts.PART_RELS[0]).name).unlink()
    ids = certify_issues.apply_to_fragment(PENDING, fragment, known)
    assert ids == ["M-new-cert-sweep-01-s2-2"] + IDS[1:]
    once = _text(fragment)
    assert certify_issues.apply_to_fragment(PENDING, fragment, known) == []
    assert _text(fragment) == once


def test_apply_to_fragment_creates_frontmatter_and_section(tmp_path):
    known, fragment = _docs(tmp_path)
    # absent file (and its directory): frontmatter from the file stem, then the section
    fragment.parent.rmdir()
    certify_issues.apply_to_fragment(PENDING, fragment, known)
    parsed = cf.parse(_text(fragment), stem="demo")
    assert (parsed.slug, parsed.kind) == ("demo", "design") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parsed.date)
    assert [b.heading.split(":")[0] for b in _blocks(fragment)] == IDS
    # an existing fragment without the section keeps its other sections and gains the new one
    fragment.write_text(FM + "\n## Roadmap\n\n### Current Focus\n\n+ - a line\n", encoding="utf-8")
    certify_issues.apply_to_fragment(PENDING, fragment, known)
    parsed = cf.parse(_text(fragment), stem="demo")
    assert cf.validate(parsed) == [] and set(parsed.sections) == {"Roadmap", ADD}
    assert [op.text for op in parsed.sections["Roadmap"][0].ops] == ["- a line"]
    # an existing section takes the new blocks after its own, and the next section stays put
    fragment.write_text(FM + f"\n## {ADD}\n\n### M-new-keep: kept\n\nbody\n\n## Known issues — resolve\n\n- M34: done\n",
                        encoding="utf-8")
    certify_issues.apply_to_fragment(PENDING, fragment, known)
    parsed = cf.parse(_text(fragment), stem="demo")
    assert cf.validate(parsed) == [] and list(parsed.sections) == [ADD, "Known issues — resolve"]
    assert [b.heading.split(":")[0] for b in parsed.sections[ADD]] == ["M-new-keep"] + IDS
    assert [b.heading for b in parsed.sections["Known issues — resolve"]] == ["M34"]


def _ledger(*args, cwd: Path) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(_SHARED_DIR / "certify_ledger.py"), "issues", "apply", *map(str, args)]
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=60)


def test_cli_fragment_and_known_issues_are_exclusive(tmp_path):
    known, fragment = _docs(tmp_path)
    pending = tmp_path / "known-issues.pending.md"
    pending.write_text(PENDING, encoding="utf-8")
    before = _text(known)
    both = _ledger("--pending", pending, "--fragment", fragment, "--known-issues", known, cwd=tmp_path)
    neither = _ledger("--pending", pending, cwd=tmp_path)
    resolved = _ledger("--pending", pending, "--fragment", fragment, "--resolved", known, cwd=tmp_path)
    assert [both.returncode, neither.returncode, resolved.returncode] == [2, 2, 2], both.stderr + neither.stderr
    assert not fragment.exists() and _text(known) == before
    # `--fragment` alone files into it, finding the living docs beside its `changes/` directory
    ok = _ledger("--pending", pending, "--fragment", fragment.relative_to(tmp_path), cwd=tmp_path)
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout.strip().splitlines()[-1]) == {"applied": IDS}
    assert [b.heading.split(":")[0] for b in _blocks(fragment)] == IDS and _text(known) == before
    # `--known-issues` alone is unchanged: it files under `## Medium` and writes no fragment
    other = tmp_path / "other"
    other.mkdir()
    known2, fragment2 = _docs(other)
    ok = _ledger("--pending", pending, "--known-issues", known2, cwd=tmp_path)
    assert ok.returncode == 0 and not fragment2.exists() and "### M-new-cert-sweep-01-s2:" in _text(known2)
