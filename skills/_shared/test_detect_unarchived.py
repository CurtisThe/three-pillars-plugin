"""Tests for detect_unarchived.py — the merged-but-unarchived backstop detector.

Content-based, squash-safe, no git history needed. Pure filesystem fixtures
under tmp_path (no temp-repo / git needed — the detector reads the tree, not refs).

Run with: python -m pytest skills/_shared/test_detect_unarchived.py -q

Design refs:
  - three-pillars-docs/tp-designs/merged-design-closeout/detailed-design.md
  - three-pillars-docs/tp-designs/merged-design-closeout/plan.md
"""

from pathlib import Path

import pytest

import detect_unarchived
from detect_unarchived import Finding, find_unarchived, main


# --------------------------------------------------------------------------- #
# Tree helpers — build a three-pillars-docs/ layout under tmp_path.
# --------------------------------------------------------------------------- #


def _design_dir(root: Path, slug: str, *, archived: bool = False) -> Path:
    sub = "completed-tp-designs" if archived else "tp-designs"
    d = root / "three-pillars-docs" / sub / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(d: Path, name: str, text: str = "x\n") -> None:
    (d / name).write_text(text)


# --------------------------------------------------------------------------- #
# Task 1.1 — Finding + find_unarchived happy path
# --------------------------------------------------------------------------- #


def test_flags_impl_audit_dir(tmp_path):
    d = _design_dir(tmp_path, "myslug")
    _write(d, "design.md")
    _write(d, "implementation-audit.md")
    findings = find_unarchived(tmp_path)
    assert findings == [
        Finding(slug="myslug", evidence="implementation-audit.md", learn_skill="tp-design-learn")
    ]


def test_seed_only_exempt(tmp_path):
    d = _design_dir(tmp_path, "seedy")
    _write(d, "seed.md")
    _write(d, "design.md")
    assert find_unarchived(tmp_path) == []


def test_completed_dir_not_scanned(tmp_path):
    # Non-vacuous scan-scope test: a flagged live dir sits ALONGSIDE an archived
    # dir that also carries impl evidence. Result must contain "live" (non-empty)
    # but NOT "archived" — so the test fails if find_unarchived ever walked
    # completed-tp-designs/.
    live = _design_dir(tmp_path, "live")
    _write(live, "implementation-audit.md")
    archived = _design_dir(tmp_path, "archived", archived=True)
    _write(archived, "implementation-audit.md")
    slugs = {f.slug for f in find_unarchived(tmp_path)}
    assert "live" in slugs
    assert "archived" not in slugs


# --------------------------------------------------------------------------- #
# Task 1.2 — spike-vs-design learn-skill routing (spike wins)
# --------------------------------------------------------------------------- #


def test_spike_results_routes_to_spike_learn(tmp_path):
    d = _design_dir(tmp_path, "sp")
    _write(d, "spike-results.md")
    assert find_unarchived(tmp_path) == [
        Finding(slug="sp", evidence="spike-results.md", learn_skill="tp-spike-learn")
    ]


def test_both_present_spike_wins(tmp_path):
    # Hybrid case (e.g. worktree-merge-conflict-flow): a spike-flavored dir that
    # also shipped a production skill. spike-results.md wins the routing.
    d = _design_dir(tmp_path, "both")
    _write(d, "implementation-audit.md")
    _write(d, "spike-results.md")
    findings = find_unarchived(tmp_path)
    assert len(findings) == 1
    assert findings[0].slug == "both"
    assert findings[0].learn_skill == "tp-spike-learn"
    assert findings[0].evidence == "spike-results.md"


# --------------------------------------------------------------------------- #
# Task 1.3 — fail-open on IO/OS error (a hygiene check must never false-fail)
# --------------------------------------------------------------------------- #


def test_fail_open_missing_root(tmp_path):
    # No three-pillars-docs/tp-designs/ at all → empty, never raises.
    assert find_unarchived(tmp_path / "does-not-exist") == []


def test_fail_open_oserror(tmp_path, monkeypatch):
    _write(_design_dir(tmp_path, "live"), "implementation-audit.md")

    def boom(self):
        raise OSError("simulated IO failure")

    monkeypatch.setattr(Path, "iterdir", boom)
    assert find_unarchived(tmp_path) == []


# --------------------------------------------------------------------------- #
# Task 1.4 — main(argv) CLI: --repo / --slugs-only / --json / --exclude; exit 0
# --------------------------------------------------------------------------- #


def _two_flagged(tmp_path):
    _write(_design_dir(tmp_path, "alpha"), "implementation-audit.md")
    _write(_design_dir(tmp_path, "bravo"), "spike-results.md")


def test_cli_slugs_only(tmp_path, capsys):
    _two_flagged(tmp_path)
    rc = main(["--repo", str(tmp_path), "--slugs-only"])
    assert rc == 0
    assert capsys.readouterr().out.split() == ["alpha", "bravo"]


def test_cli_json(tmp_path, capsys):
    import json as _json

    _two_flagged(tmp_path)
    rc = main(["--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = _json.loads(capsys.readouterr().out)
    assert {p["slug"] for p in payload} == {"alpha", "bravo"}
    bravo = next(p for p in payload if p["slug"] == "bravo")
    assert bravo["learn_skill"] == "tp-spike-learn"
    assert bravo["evidence"] == "spike-results.md"


def test_cli_exclude(tmp_path, capsys):
    _two_flagged(tmp_path)
    # repeatable --exclude; the nudge callers pass the current in-flight design.
    rc = main(["--repo", str(tmp_path), "--slugs-only", "--exclude", "alpha"])
    assert rc == 0
    assert capsys.readouterr().out.split() == ["bravo"]
    rc = main(["--repo", str(tmp_path), "--slugs-only", "--exclude", "alpha", "--exclude", "bravo"])
    assert rc == 0
    assert capsys.readouterr().out.split() == []


def test_cli_always_exit_zero(tmp_path):
    # Reporter, not gate: exit 0 even with findings present.
    _two_flagged(tmp_path)
    assert main(["--repo", str(tmp_path)]) == 0
    # And exit 0 on a totally empty repo.
    assert main(["--repo", str(tmp_path / "nope")]) == 0
