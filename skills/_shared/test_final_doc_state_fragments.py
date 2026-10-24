"""Task 1.9: fragment mode in `final_doc_state` (`close`, `check`, `--base`).

design: living-doc-fragments. Oracle: example; assertions read JSON fields and exit codes.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import final_doc_state

DOCS = "three-pillars-docs"
RM = f"{DOCS}/product_roadmap.md"
KI = f"{DOCS}/known_issues.md"
FRAG = f"{DOCS}/changes/demo.md"
PENDING = "Completion PR pending"
DONE = f"{DOCS}/completed-tp-designs/demo"
ROW = f"| demo | Fixture. | design | {PENDING} — [design]({DONE}/design.md) | Docs |"
ROADMAP = "\n".join(["# Roadmap", "", "## Design Inventory", "", "| Name | What | Type | Status | Track |",
                     "|---|---|---|---|---|", ROW, ""])
FRAGMENT = "---\nslug: demo\nkind: design\ndate: 2026-10-22\n---\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8")


def _repo(root: Path, *, fragment: bool = True) -> Path:
    (root / DOCS / "changes").mkdir(parents=True)
    (root / DONE).mkdir(parents=True)
    (root / DONE / "decisions.md").write_text("- `demo` ok.\n", encoding="utf-8")
    (root / RM).write_text(ROADMAP, encoding="utf-8")
    (root / KI).write_text("base\n", encoding="utf-8")
    if fragment:
        (root / FRAG).write_text(FRAGMENT, encoding="utf-8")
    return root


def _snapshot(root: Path) -> dict:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _run(capsys, verb, root, *extra):
    code = final_doc_state.main([verb, "--slug", "demo", "--repo-root", str(root), "--json", *extra])
    return code, json.loads(capsys.readouterr().out)


def test_close_is_noop_with_fragment(tmp_path, capsys):
    root = _repo(tmp_path)
    before = _snapshot(root)
    code, out = _run(capsys, "close", root)
    assert code == 0
    assert out["mode"] == "fragment" and out["paths"] == [] and out["moved"] == 0
    assert out["refused"] is None
    assert _snapshot(root) == before


def test_close_folds_when_fragment_aware_false(tmp_path):
    root = _repo(tmp_path)
    out = final_doc_state.close(root, "demo", fragment_aware=False)
    assert "mode" not in out
    assert out["flipped"] >= 1
    assert PENDING not in (root / RM).read_text(encoding="utf-8")


def test_check_reports_pending_compile_exit_0(tmp_path, capsys):
    root = _repo(tmp_path)
    code, out = _run(capsys, "check", root)
    assert code == 0
    assert out["verdict"] == "pending-compile"


def test_check_with_base_runs_guard_and_exits_1_on_refusal(tmp_path, capsys):
    root = _repo(tmp_path, fragment=False)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "tp/demo")
    (root / KI).write_text("edited\n", encoding="utf-8")
    (root / FRAG).write_text(FRAGMENT, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "work")
    code, out = _run(capsys, "check", root, "--base", "main")
    assert code == 1
    assert out["verdict"] == "pending-compile"
    assert out["guard"]["verdict"] == "refused" and KI in out["guard"]["paths"]


def test_no_fragment_keeps_todays_behaviour(tmp_path, capsys):
    root = _repo(tmp_path, fragment=False)
    code, out = _run(capsys, "check", root)
    assert code == 1
    assert out["verdict"] == "drift" and out["rows"]
    assert "guard" not in out and "mode" not in out


# Task 1.11: an unappliable pending fragment (design: run-friction-1022).
OTHER = f"{DOCS}/changes/other.md"
OTHER_FRAG = ("---\nslug: other\nkind: design\ndate: 2026-10-21\n---\n"
              "## Roadmap\n\n### Current Focus\n- - focus one\n")
FOCUS_DOC = ROADMAP + "\n### Current Focus\n\n- focus one\n"


def _conflict_repo(root: Path, *, own_fragment: bool, base_has_line: bool = True) -> Path:
    """Base has the anchor line `- focus one`; the branch (HEAD) removes it. `other` pends."""
    _repo(root, fragment=False)
    (root / OTHER).write_text(OTHER_FRAG, encoding="utf-8")
    if own_fragment:
        (root / FRAG).write_text(FRAGMENT, encoding="utf-8")
    (root / RM).write_text(FOCUS_DOC if base_has_line else ROADMAP + "\n### Current Focus\n\n",
                           encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "tp/demo")
    (root / RM).write_text(ROADMAP + "\n### Current Focus\n\n", encoding="utf-8")
    (root / "work.txt").write_text("work\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "work")
    return root


REANCHOR = f"re-anchor {DOCS}/changes/other.md: "


def _reanchor(out: dict) -> list[str]:
    return [ln for ln in out["fix"] if ln.startswith(REANCHOR)]


def test_introduced_conflict_is_drift_in_fragment_mode(tmp_path, capsys):
    root = _conflict_repo(tmp_path, own_fragment=True)
    code, out = _run(capsys, "check", root, "--base", "main")
    assert code == 1
    assert out["verdict"] == "drift"
    assert len(_reanchor(out)) == 1


def test_introduced_conflict_is_drift_in_doc_mode(tmp_path, capsys):
    root = _conflict_repo(tmp_path, own_fragment=False)
    code, out = _run(capsys, "check", root, "--base", "main")
    assert out["verdict"] == "drift"
    assert code == 1
    assert len(_reanchor(out)) == 1


def test_conflict_on_both_base_and_head_leaves_verdict_unchanged(tmp_path, capsys):
    root = _conflict_repo(tmp_path, own_fragment=True, base_has_line=False)
    code, out = _run(capsys, "check", root, "--base", "main")
    assert code == 0
    assert out["verdict"] == "pending-compile"
    assert _reanchor(out) == []


def test_without_base_conflict_is_a_non_blocking_note(tmp_path, capsys):
    root = _conflict_repo(tmp_path, own_fragment=True)
    code, out = _run(capsys, "check", root)
    assert code == 0
    assert out["verdict"] == "pending-compile"
    assert list(out["pending_conflicts"]) == ["other"]
    assert _reanchor(out) == []


def test_no_pending_conflict_leaves_output_as_today(tmp_path, capsys):
    root = _repo(tmp_path)
    _, out = _run(capsys, "check", root)
    assert "pending_conflicts" not in out
