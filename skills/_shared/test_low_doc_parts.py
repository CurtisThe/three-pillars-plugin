"""test_low_doc_parts.py — the one helper that lists the Low parts.

design: basesync-count-line-and-low-headroom (1.1)

Every behaviour is exercised on a `tmp_path` tree — no git, no real repo. The
consumer-repo posture (a repo with only `known_issues.md`, no Low doc) is one
of the cases.
"""
from __future__ import annotations

import re
from pathlib import Path

import file_size_guard
import low_doc_parts as ldp

DOCS = "three-pillars-docs"
_HEAD_RE = re.compile(r"^### ", re.M)


def docs(root: Path) -> Path:
    d = root / DOCS
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_part(root: Path, n: int, text: str) -> Path:
    p = root / ldp.part_rel(n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def read_part(root: Path, n: int) -> str:
    return (root / ldp.part_rel(n)).read_text(encoding="utf-8")


def entry(i: int, pad: int = 0) -> str:
    """One `### L` entry, deterministic, optionally padded to a known width."""
    return f"### L{i}: issue {i}\n- body {i}\n" + ("x" * pad) + "\n"


def part_text(n: int, count: int, pad: int = 0, first: int = 1) -> str:
    return ldp.part_header(n) + "".join(
        entry(i, pad) for i in range(first, first + count))


def entries_of(text: str) -> list[str]:
    """Entries as the helper defines them: `### ` line up to the next."""
    starts = [m.start() for m in _HEAD_RE.finditer(text)]
    return [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]


# ---------------------------------------------------------------- names/parts

def test_cap_matches_the_diet_cap() -> None:
    """The helper's CAP is the same 50k diet cap the real tree is held to."""
    assert ldp.CAP == file_size_guard.char_caps(ldp.FIRST_REL, False)[1]


def test_is_part_rel() -> None:
    for rel in (ldp.FIRST_REL, ldp.part_rel(2), ldp.part_rel(9),
                "three-pillars-docs\\known_issues_low_2.md"):
        assert ldp.is_part_rel(rel), rel
    for rel in ("three-pillars-docs/known_issues_low_1.md",
                "three-pillars-docs/known_issues_low_10.md",
                "three-pillars-docs/known_issues.md",
                "three-pillars-docs/known_issues_low.md.bak",
                "docs/known_issues_low.md"):
        assert not ldp.is_part_rel(rel), rel


def test_part_rels_and_next() -> None:
    assert ldp.PART_RELS == tuple(ldp.part_rel(n) for n in range(1, ldp.MAX_PARTS + 1))
    assert ldp.PART_RELS[0] == ldp.FIRST_REL
    assert ldp.next_part_rel(ldp.part_rel(ldp.MAX_PARTS)) is None
    assert ldp.next_part_rel(ldp.FIRST_REL) == ldp.part_rel(2)
    assert ldp.part_number(ldp.part_rel(3)) == 3
    assert ldp.part_number(ldp.FIRST_REL) == 1
    assert ldp.part_number("three-pillars-docs/known_issues.md") is None


def test_parts_on_disk(tmp_path: Path) -> None:
    assert ldp.parts_on_disk(tmp_path) == []
    docs(tmp_path)
    (tmp_path / DOCS / "known_issues.md").write_text("# Known Issues\n\n", encoding="utf-8")
    assert ldp.parts_on_disk(tmp_path) == []
    write_part(tmp_path, 3, part_text(3, 1))
    write_part(tmp_path, 1, part_text(1, 2))
    assert ldp.parts_on_disk(tmp_path) == [ldp.part_rel(1), ldp.part_rel(3)]


# ----------------------------------------------------------------- counting

def test_count_lows_ignores_near_misses() -> None:
    text = "### L12: a\n### L-new-x: b\n### M5: c\n#### L1: d\n### Lorem\n"
    assert ldp.count_lows(text) == 2


def test_total_lows_across_parts(tmp_path: Path) -> None:
    write_part(tmp_path, 1, part_text(1, 2) + "### L-new-x: new\n### M5: m\n")
    write_part(tmp_path, 3, "### L9: z\n")
    assert ldp.total_lows(tmp_path) == 4


# ------------------------------------------------------------- target_part

def test_target_part(tmp_path: Path) -> None:
    docs(tmp_path)
    assert ldp.target_part(tmp_path, 100) == ldp.FIRST_REL
    write_part(tmp_path, 1, part_text(1, 1))
    assert ldp.target_part(tmp_path, 100) == ldp.part_rel(1)
    write_part(tmp_path, 1, ldp.part_header(1) + "x" * (ldp.CAP - ldp.RESERVE - 50))
    assert ldp.target_part(tmp_path, 100) == ldp.part_rel(2)
    for n in range(1, ldp.MAX_PARTS + 1):
        write_part(tmp_path, n, "x" * ldp.CAP)
    assert ldp.target_part(tmp_path, 100) is None


# ------------------------------------------------------------- split_part

def _check_split(tmp_path: Path, before1: str, before2: str | None) -> None:
    moved = ldp.split_part(tmp_path, ldp.part_rel(1))
    after1, after2 = read_part(tmp_path, 1), read_part(tmp_path, 2)
    assert moved > 0
    assert len(after1) <= ldp.CAP
    assert after2.startswith(ldp.part_header(2))
    assert after1.split("### ")[0] == before1.split("### ")[0], "preamble changed"
    heads_before = ldp.count_lows(before1) + (ldp.count_lows(before2) if before2 else 0)
    assert ldp.count_lows(after1) + ldp.count_lows(after2) == heads_before
    heads1 = {ln for ln in after1.splitlines() if ln.startswith("### ")}
    heads2 = {ln for ln in after2.splitlines() if ln.startswith("### ")}
    assert not (heads1 & heads2), "a heading line is in both parts"
    # the moved entries appear verbatim, in order, at the end of part 2
    moved_texts = entries_of(before1)[-moved:]
    tail = after2[len(ldp.part_header(2)):] if not before2 else after2[len(before2):]
    assert tail == "".join(moved_texts)


def test_split_part_no_loss(tmp_path: Path) -> None:
    before1 = part_text(1, 300, pad=140)
    assert len(before1) > ldp.CAP
    write_part(tmp_path, 1, before1)
    _check_split(tmp_path, before1, None)


def test_split_part_appends_to_existing_part2(tmp_path: Path) -> None:
    before1 = part_text(1, 300, pad=140)
    before2 = part_text(2, 3, pad=5, first=900)
    write_part(tmp_path, 1, before1)
    write_part(tmp_path, 2, before2)
    _check_split(tmp_path, before1, before2)
    assert read_part(tmp_path, 2).startswith(before2)


def _expect_refusal(root: Path, rel: str, snapshot: dict[Path, str]) -> None:
    try:
        ldp.split_part(root, rel)
        raise AssertionError("expected LowSplitError")
    except ldp.LowSplitError:
        pass
    for path, text in snapshot.items():
        assert path.read_text(encoding="utf-8") == text, f"{path} changed"


def test_split_part_refusals_leave_files_untouched(tmp_path: Path) -> None:
    big = ldp.part_header(1) + entry(1, pad=ldp.CAP + 10)
    p1 = write_part(tmp_path, 1, big)
    _expect_refusal(tmp_path, ldp.part_rel(1), {p1: big})
    assert not (tmp_path / ldp.part_rel(2)).exists()

    last = part_text(ldp.MAX_PARTS, 400, pad=140)
    plast = write_part(tmp_path, ldp.MAX_PARTS, last)
    _expect_refusal(tmp_path, ldp.part_rel(ldp.MAX_PARTS), {plast: last})

    b1, b2 = part_text(1, 300, pad=140), "x" * (ldp.CAP - 10)
    q1 = write_part(tmp_path, 1, b1)
    q2 = write_part(tmp_path, 2, b2)
    _expect_refusal(tmp_path, ldp.part_rel(1), {q1: b1, q2: b2})


def test_split_part_refuses_a_part_with_no_entry(tmp_path: Path) -> None:
    """C1: an over-cap part with no `### ` entry has nothing to move.

    It used to return 1 and write a header-only part 2 — a part that holds no
    issue and that every reader then lists. Refuse, and leave the tree alone.
    """
    big = ldp.part_header(1) + "x" * (ldp.CAP + 10)  # preamble only, no entry
    p1 = write_part(tmp_path, 1, big)
    _expect_refusal(tmp_path, ldp.part_rel(1), {p1: big})
    assert not (tmp_path / ldp.part_rel(2)).exists()


def test_split_part_refuses_an_over_cap_preamble(tmp_path: Path) -> None:
    """C1: when the preamble alone is over `cap`, no entry can stay.

    The refusal names the preamble, not the first entry — the entry is not what
    is too big.
    """
    big = "y" * (ldp.CAP + 10) + "\n" + entry(1)  # the entry starts its own line
    p1 = write_part(tmp_path, 1, big)
    try:
        ldp.split_part(tmp_path, ldp.part_rel(1))
        raise AssertionError("expected LowSplitError")
    except ldp.LowSplitError as exc:
        assert "preamble" in str(exc), str(exc)
    assert p1.read_text(encoding="utf-8") == big
    assert not (tmp_path / ldp.part_rel(2)).exists()


def test_low_split_error_is_a_value_error() -> None:
    assert issubclass(ldp.LowSplitError, ValueError)


# -------------------------------------------------------------------- CLI

def test_cli_target_create(tmp_path: Path, capsys) -> None:
    write_part(tmp_path, 1, "x" * (ldp.CAP - ldp.RESERVE - 20))
    assert ldp.main(["target", "--root", str(tmp_path), "--chars", "120"]) == 0
    assert capsys.readouterr().out.strip() == ldp.part_rel(2)
    assert not (tmp_path / ldp.part_rel(2)).exists()
    assert ldp.main(["target", "--root", str(tmp_path), "--chars", "120",
                     "--create"]) == 0
    assert read_part(tmp_path, 2) == ldp.part_header(2)


def test_cli_target_all_full(tmp_path: Path, capsys) -> None:
    for n in range(1, ldp.MAX_PARTS + 1):
        write_part(tmp_path, n, "x" * ldp.CAP)
    assert ldp.main(["target", "--root", str(tmp_path), "--chars", "10"]) == 2
    err = capsys.readouterr().err.strip()
    assert err.startswith("low_doc_parts:") and "\n" not in err


def test_cli_count(tmp_path: Path, capsys) -> None:
    write_part(tmp_path, 1, part_text(1, 2))
    write_part(tmp_path, 2, "### L-new-x: n\n")
    assert ldp.main(["count", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "3"
