"""test_certify_issues.py — `issues render` / `issues apply` for certification results.

design: audit-pass-does-not-bind (Task 9.4; detailed-design.md §Interfaces [B]).

`render` files every `not-binding` / `false-red` sweep claim and every self
claim that is not `binds` / `known-bypass` (a B15 miss is filed, never silent).
`apply` re-derives the next free Medium id over `known_issues.md` ∪
`known_issues_resolved.md` at apply time and is re-runnable (an entry already
filed under its key is skipped).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import certify_issues  # noqa: E402
import certify_ledger  # noqa: E402


def _entry(cid: str, status: str, reasons=()) -> dict:
    return {"id": cid, "status": status, "reasons": list(reasons), "guard": f"g/{cid}.py::t",
            "evidence": {"red": [{"rc": 0, "tail": "1 passed"}], "green": []}}


def _result(name: str, entries: list[dict]) -> dict:
    return {"complete": True, "name": name, "sha": "a" * 40, "disposition": "ledger",
            "claims": entries}


SWEEP = _result("sweep-01", [_entry("s1", "binds"), _entry("s2", "not-binding"),
                             _entry("s3", "false-red"), _entry("s4", "unverified", ["budget"]),
                             _entry("s5", "known-bypass")])
SELF = _result("self", [_entry("c1", "binds"), _entry("c2", "unverified", ["no-record"]),
                        _entry("c3", "known-bypass"), _entry("c4", "not-binding")])

KNOWN = """# Known Issues

## Critical / High

### H1: something

## Medium

### M3: an open one

body

## Low
"""
RESOLVED = "# Resolved\n\n### M9 (RESOLVED 2026-01-01): an old one\n"


def test_render_files_sweep_misses_and_every_unmet_self_row():
    text = certify_issues.render([SWEEP], SELF)
    keys = certify_issues.keys_in(text)
    assert keys == ["sweep-01#s2", "sweep-01#s3", "self#c2", "self#c4"]
    assert text.count(f"### {certify_issues.PLACEHOLDER}:") == len(keys)
    assert "g/s2.py::t" in text and "not-binding" in text


def test_render_keys_a_claims_json_result_name_by_its_stem():
    """T1: `sweep-01.claims.json` files the same keys and text as `sweep-01`."""
    named = certify_issues.render([dict(SWEEP, name="sweep-01.claims.json")],
                                  dict(SELF, name="self.claims.json"))
    assert named == certify_issues.render([SWEEP], SELF)
    assert "sweep-01.claims.json" in named and ".claims.json.claims.json" not in named


def test_render_nothing_to_file_is_an_empty_pending_list():
    clean = _result("sweep-01", [_entry("s1", "binds")])
    assert certify_issues.keys_in(certify_issues.render([clean], None)) == []


def _files(tmp_path: Path) -> tuple[Path, Path]:
    known, resolved = tmp_path / "known_issues.md", tmp_path / "known_issues_resolved.md"
    known.write_text(KNOWN, encoding="utf-8")
    resolved.write_text(RESOLVED, encoding="utf-8")
    return known, resolved


def test_apply_allocates_past_both_files_under_medium(tmp_path):
    known, resolved = _files(tmp_path)
    ids = certify_issues.apply(certify_issues.render([SWEEP], SELF), known, resolved)
    assert ids == ["M10", "M11", "M12", "M13"]
    text = known.read_text(encoding="utf-8")
    medium = text.index("## Medium")
    assert text.index("### M10:") > medium
    assert text.index("### M13:") < text.index("### M3:")
    assert "M?" not in text


def test_apply_re_derives_the_id_at_apply_time(tmp_path):
    known, resolved = _files(tmp_path)
    pending = certify_issues.render([SWEEP], None)
    resolved.write_text(RESOLVED + "\n### M40 (RESOLVED 2026-02-02): allocated meanwhile\n",
                        encoding="utf-8")
    assert certify_issues.apply(pending, known, resolved) == ["M41", "M42"]


def test_apply_is_re_runnable(tmp_path):
    known, resolved = _files(tmp_path)
    pending = certify_issues.render([SWEEP], SELF)
    certify_issues.apply(pending, known, resolved)
    once = known.read_text(encoding="utf-8")
    assert certify_issues.apply(pending, known, resolved) == []
    assert known.read_text(encoding="utf-8") == once


def test_apply_without_a_medium_section_fails(tmp_path):
    known, resolved = _files(tmp_path)
    known.write_text("# Known Issues\n\n## Low\n", encoding="utf-8")
    with pytest.raises(ValueError, match="## Medium"):
        certify_issues.apply(certify_issues.render([SWEEP], None), known, resolved)


def test_issues_cli_render_then_apply(tmp_path, capsys):
    import json
    known, resolved = _files(tmp_path)
    res = tmp_path / "sweep-01.result.json"
    res.write_text(json.dumps(SWEEP), encoding="utf-8")
    pending = tmp_path / "known-issues.pending.md"
    assert certify_ledger.main(["issues", "render", "--result", str(res),
                                "--out", str(pending)]) == 0
    assert certify_ledger.main(["issues", "apply", "--pending", str(pending),
                                "--known-issues", str(known)]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {
        "applied": ["M10", "M11"]}
    assert "sweep-01#s3" in known.read_text(encoding="utf-8")
