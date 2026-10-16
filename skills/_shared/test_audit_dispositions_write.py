"""``audit_dispositions.write`` + ``claim_tokens`` (design: review-convergence 6.1).

The carry file is the impl-audit verdict's dispositions, written once at the final
Tier 5 verdict and read back by ``mark`` in Tier 7 (detailed-design-pr-loop.md §D4).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_dispositions  # noqa: E402

MODULE = Path(__file__).resolve().parent / "audit_dispositions.py"
HEAD = "11a54b232cdd15d48acdf1d2f7a93cc41884b358"

# Two findings carry a file (one also carries a line); the third is unfiled and
# never travels to Tier 7.
AUDIT_RETURN = {
    "verdict": "pass-with-notes",
    "findings": [
        {
            "file": "skills/_shared/guard.py",
            "line": 12,
            "description": "  The Guard   binds a File path ",
            "severity": "medium",
            "disposition": "fixed",
            "category": "logic",
        },
        {
            "file": "skills/_shared/deep/other.py",
            "description": "unused import",
            "severity": "minor",
            "disposition": "wontfix",
        },
        {"description": "a finding with no file", "severity": "critical"},
    ],
}

EXPECTED = [
    {
        "file": "skills/_shared/guard.py",
        "area": "skills/_shared",
        "claim": "the guard binds a file path",
        "disposition": "fixed",
        "severity": "medium",
        "audit_head": HEAD,
        "line": 12,
    },
    {
        "file": "skills/_shared/deep/other.py",
        "area": "skills/_shared/deep",
        "claim": "unused import",
        "disposition": "noted",
        "severity": "minor",
        "audit_head": HEAD,
    },
]


def _audit_return(tmp_path: Path, payload=AUDIT_RETURN) -> Path:
    path = tmp_path / "audit-return.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write(tmp_path: Path, payload=AUDIT_RETURN):
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    out = audit_dispositions.write(design_dir, _audit_return(tmp_path, payload), head=HEAD)
    return design_dir, out


def test_carry_name():
    assert audit_dispositions.CARRY == "audit-dispositions.json"


def test_write_returns_carry_path_in_design_dir(tmp_path):
    design_dir, out = _write(tmp_path)
    assert out == design_dir / audit_dispositions.CARRY
    assert out.is_file()


def test_write_one_entry_per_filed_finding(tmp_path):
    _, out = _write(tmp_path)
    assert json.loads(out.read_text(encoding="utf-8")) == EXPECTED


def test_write_carries_line_only_when_finding_has_one(tmp_path):
    _, out = _write(tmp_path, {"findings": [{"file": "a/b.py", "description": "x"}]})
    entries = json.loads(out.read_text(encoding="utf-8"))
    assert entries == [{"file": "a/b.py", "area": "a", "claim": "x", "disposition": "noted",
                        "severity": None, "audit_head": HEAD}]


def test_write_area_is_parent_dir_for_bare_name(tmp_path):
    _, out = _write(tmp_path, {"findings": [{"file": "top.py", "description": "y"}]})
    assert json.loads(out.read_text(encoding="utf-8"))[0]["area"] == ""


def test_write_accepts_findings_list_directly(tmp_path):
    _, out = _write(tmp_path, AUDIT_RETURN["findings"])
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 2


def test_write_no_filed_findings_writes_empty_list(tmp_path):
    _, out = _write(tmp_path, {"findings": [{"description": "nothing filed"}]})
    assert json.loads(out.read_text(encoding="utf-8")) == []


def test_claim_tokens_drops_stop_words_and_short_words():
    assert audit_dispositions.claim_tokens(
        "The guard binds a file path when the file changes") == {
        "guard", "binds", "file", "path", "changes"}


def test_claim_tokens_lowercases_and_splits_punctuation():
    # "an" / "OK" are under 3 chars, so they never reach the stop-word filter.
    assert audit_dispositions.claim_tokens("GUARD: binds FILE-path, an OK module") == {
        "guard", "binds", "file", "path", "module"}


def test_claim_tokens_is_frozenset_of_empty_for_nothing_kept():
    toks = audit_dispositions.claim_tokens("the a of to id")
    assert isinstance(toks, frozenset)
    assert toks == frozenset()


def _run_cli(design_dir: Path, audit_return: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MODULE), "write", "--design-dir", str(design_dir),
         "--audit-return", str(audit_return), "--head", HEAD],
        capture_output=True, text=True, cwd=str(MODULE.parent))


def test_cli_write_prints_the_carry_path(tmp_path):
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    audit_return = _audit_return(tmp_path)
    proc = _run_cli(design_dir, audit_return)
    assert proc.returncode == 0, proc.stderr
    expected = str(design_dir / audit_dispositions.CARRY)
    assert proc.stdout.strip() == expected
    assert len(json.loads(Path(expected).read_text(encoding="utf-8"))) == 2


def test_cli_write_exits_two_on_missing_audit_return(tmp_path):
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    proc = _run_cli(design_dir, tmp_path / "does-not-exist.json")
    assert proc.returncode == 2
