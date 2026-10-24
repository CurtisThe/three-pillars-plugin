"""Doc pins: run-safety.md's classifier no-verdict stop and the worker's isolation source.

design: classifier-no-verdict-nested-writes (Task 1.4)
"""
import re
from pathlib import Path

RUN_SAFETY = Path(__file__).resolve().parents[2] / "skills" / "tp-run-full-design" / "run-safety.md"


def _text():
    return RUN_SAFETY.read_text(encoding="utf-8")


def _section(heading):
    text = _text()
    start = text.index(f"## {heading}\n")
    nxt = text.find("\n## ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


def test_classifier_no_verdict_section_names_the_trigger_and_the_stop():
    body = _section("Classifier no-verdict")
    for token in (".claude/", "worker_root.py", "never retry", "decisions.md", "inline"):
        assert token in body, token


def test_section_lists_the_evidence_fields_without_content():
    body = _section("Classifier no-verdict")
    for field in ("agent type", "model", "tool", "target path", "content size", "message"):
        assert field in body, field
    assert "no content" in body


def test_branch_hygiene_rule_2_sources_isolation_from_worker_root():
    rule2 = next(l for l in _section("Branch hygiene").splitlines() if l.startswith("2. "))
    assert "worker_root.py" in rule2
    assert not re.search(r"worker \(Tier 3\) and regression check", rule2)
    assert re.search(r"worker \(Tier 3\)[^.]*worker_root\.py", rule2)


def test_the_no_verdict_log_keeps_host_paths_out_of_decisions():
    body = _section("Classifier no-verdict")
    assert "portable_path" in body
    assert "absolute host path" in body


def test_the_backstop_is_the_tip_comparison_not_only_head():
    body = _section("Classifier no-verdict")
    assert "worker_root.py assert-unmoved" in body
    assert "uncommitted" in body


def _item2_and_first_bullet():
    rule2 = next(l for l in _section("Branch hygiene").splitlines() if l.startswith("2. "))
    bullet = next(l for l in _section("Classifier no-verdict").splitlines() if l.startswith("- "))
    return rule2, bullet


def _scan_hits_in_run_safety():
    import sys
    root = RUN_SAFETY.parents[2]
    sys.path.insert(0, str(root / "skills" / "_shared"))
    import wt_layout_scan
    hits = wt_layout_scan.scan([root / "skills" / "tp-run-full-design"], base=root)
    return [h for h in hits if h[0] == "skills/tp-run-full-design/run-safety.md"]


def test_docs_state_the_one_rule_through_wt_root_and_the_layout_hook():
    rule2, bullet = _item2_and_first_bullet()
    assert "wt_root.py" in rule2
    assert "isolation=" not in rule2
    assert "wt_root.py" in bullet
    assert "wt_layout_hook.py" in bullet
    assert _scan_hits_in_run_safety() == []
