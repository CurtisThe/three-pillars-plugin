"""Tests for fragility_metrics — rounds per PR and fragility-class share.

design: fragile-test-prevention (detailed-design-stages.md, fragility_metrics.py)

Round lines are built with `finding_class.class_line`, never hand-written, so
the parser is exercised against the real key=value token grammar. A stripped
copy of a real line (the `frag=…` suffix removed) stands in for a
pre-migration line, since that format predates the frag token and there is no
generator for it anymore.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "tp-pr-iterate" / "scripts"))

import fragility_metrics  # noqa: E402
from finding_class import class_line  # noqa: E402

TALLY_A1 = {"P": 1, "X": 0, "T": 0, "C": 0, "blocking": 3,
            "frag": {"open-ended": 1, "change-detector": 1, "blocklist": 1}, "regression": 0}
TALLY_A2 = {"P": 0, "X": 1, "T": 0, "C": 0, "blocking": 2,
            "frag": {"open-ended": 0, "change-detector": 2, "blocklist": 0}, "regression": 0}
TALLY_B1_LEGACY_SOURCE = {"P": 2, "X": 1, "T": 1, "C": 0, "blocking": 4,
                           "frag": {"open-ended": 2, "change-detector": 1, "blocklist": 1},
                           "regression": 0}
TALLY_B2 = {"P": 1, "X": 0, "T": 0, "C": 0, "blocking": 1,
            "frag": {"open-ended": 1, "change-detector": 0, "blocklist": 0}, "regression": 0}
TALLY_DECOY = {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 999,
               "frag": {"open-ended": 999, "change-detector": 0, "blocklist": 0}, "regression": 0}


def _build_repo(root: Path) -> None:
    design_a = root / "three-pillars-docs" / "tp-designs" / "design-a"
    design_b = root / "three-pillars-docs" / "completed-tp-designs" / "design-b"
    design_a.mkdir(parents=True)
    design_b.mkdir(parents=True)

    line_a1 = class_line(1, "abc1234", TALLY_A1)
    line_a2 = class_line(2, "abc5678", TALLY_A2)
    (design_a / "decisions.md").write_text(line_a1 + "\n" + line_a2 + "\n", encoding="utf-8")

    legacy_source = class_line(1, "def1234", TALLY_B1_LEGACY_SOURCE)
    legacy_line = legacy_source.split(" frag=")[0]
    line_b2 = class_line(2, "ghi9012", TALLY_B2)
    (design_b / "decisions.md").write_text(legacy_line + "\n" + line_b2 + "\n", encoding="utf-8")

    # The proof root: `/tp-post-merge` deletes it with the worktree, and the
    # module must never read it, so a huge decoy round here would corrupt
    # every total if it leaked in.
    proof_root = root / ".three-pillars" / "review-proof"
    proof_root.mkdir(parents=True)
    decoy_line = class_line(99, "zzz9999", TALLY_DECOY)
    (proof_root / "decisions.md").write_text(decoy_line + "\n", encoding="utf-8")

    # A decisions.md outside either design root — also not read.
    (root / "decisions.md").write_text(class_line(1, "out0000", TALLY_DECOY) + "\n",
                                        encoding="utf-8")


def test_rounds_and_frag_share_per_pr(tmp_path):
    _build_repo(tmp_path)
    report = fragility_metrics.build_report(tmp_path)

    assert set(report["prs"]) == {"design-a", "design-b"}

    a = report["prs"]["design-a"]
    assert a["rounds"] == 2
    assert a["frag"] == {"open-ended": 1, "change-detector": 3, "blocklist": 1,
                          "unclassified": 0}
    assert a["frag_share"]["change-detector"] == 3 / 5

    b = report["prs"]["design-b"]
    assert b["rounds"] == 2
    # The legacy (frag-less) line's blocking count (4) becomes unclassified;
    # the classified line adds its explicit open-ended count (1).
    assert b["frag"] == {"open-ended": 1, "change-detector": 0, "blocklist": 0,
                          "unclassified": 4}
    assert b["frag_share"]["unclassified"] == 4 / 5


def test_proof_root_and_outside_files_never_read(tmp_path):
    _build_repo(tmp_path)
    report = fragility_metrics.build_report(tmp_path)

    assert "review-proof" not in report["prs"]
    assert "." not in report["prs"]
    total_blocking = sum(sum(pr["frag"].values()) for pr in report["prs"].values())
    assert total_blocking == 10  # 5 (design-a) + 5 (design-b); the decoys (999 each) excluded


def test_baseline_comparison(tmp_path):
    _build_repo(tmp_path)
    report = fragility_metrics.build_report(tmp_path)
    baseline = {"schema": 1, "prs": {
        "design-a": {"rounds": 2},
        "design-b": {"rounds": 5},
        "design-c": {"rounds": 1},
    }}
    comparison = fragility_metrics.compare(report, baseline)

    assert comparison["design-a"] == {"status": "ok", "rounds_delta": 0}
    assert comparison["design-b"] == {"status": "ok", "rounds_delta": -3}
    assert comparison["design-c"] == {"status": "missing"}


def test_main_cli_reports_and_compares(tmp_path, capsys):
    _build_repo(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"schema": 1, "prs": {"design-a": {"rounds": 2}}}),
                              encoding="utf-8")

    rc = fragility_metrics.main(["--root", str(tmp_path), "--baseline", str(baseline_path)])
    assert rc == 0

    out = json.loads(capsys.readouterr().out)
    assert out["prs"]["design-a"]["rounds"] == 2
    assert out["comparison"]["design-a"] == {"status": "ok", "rounds_delta": 0}


def test_baseline_keyed_by_pr_number_matches_its_named_design(tmp_path):
    """The committed baseline keys entries by PR number and names each one's design;
    the report keys by design directory, so the comparison resolves through `design`."""
    _build_repo(tmp_path)
    report = fragility_metrics.build_report(tmp_path)
    baseline = {"schema": 1, "prs": {
        "143": {"design": "design-a", "rounds": 27},
        "144": {"design": "design-gone", "rounds": 26},
    }}
    comparison = fragility_metrics.compare(report, baseline)

    assert comparison["143"] == {"status": "ok", "rounds_delta": 2 - 27}
    assert comparison["144"] == {"status": "missing"}


def test_unmeasured_side_gets_no_delta(tmp_path):
    """A comparison exists only when BOTH sides carry a measured `rounds` figure.

    The shipped baseline's #162/#165 entries record blockers and no `rounds`; a design
    whose decisions.md predates flushed round lines has no measured count either. Neither
    side may default to 0: the entry says which side is unmeasured and carries no delta.
    """
    measured = tmp_path / "three-pillars-docs" / "completed-tp-designs" / "measured"
    unflushed = tmp_path / "three-pillars-docs" / "tp-designs" / "unflushed"
    measured.mkdir(parents=True)
    unflushed.mkdir(parents=True)
    (measured / "decisions.md").write_text(
        class_line(1, "aaa1111", TALLY_A1) + "\n" + class_line(2, "aaa2222", TALLY_A2) + "\n",
        encoding="utf-8")
    (unflushed / "decisions.md").write_text(
        "### [tp-pr-iterate] round 27 review — narrative only, no flushed round line\n",
        encoding="utf-8")

    report = fragility_metrics.build_report(tmp_path)
    assert report["prs"]["measured"]["rounds"] == 2
    assert report["prs"]["unflushed"]["rounds"] is None

    baseline = {"schema": 1, "prs": {
        "162": {"design": "measured", "blockers": 20, "fragility_class_blockers": 17},
        "143": {"design": "unflushed", "rounds": 27},
        "150": {"design": "measured", "rounds": 5},
        "measured": 26,
        "unflushed": {"blockers": 9},
        "999": {"design": "gone", "rounds": 1},
    }}
    comparison = fragility_metrics.compare(report, baseline)

    assert comparison["162"] == {"status": "unmeasured", "unmeasured": ["baseline"]}
    assert comparison["143"] == {"status": "unmeasured", "unmeasured": ["current"]}
    assert comparison["150"] == {"status": "ok", "rounds_delta": 2 - 5}
    # A bare number is not a measured entry (and must not crash the comparison).
    assert comparison["measured"] == {"status": "unmeasured", "unmeasured": ["baseline"]}
    assert comparison["unflushed"] == {"status": "unmeasured",
                                       "unmeasured": ["baseline", "current"]}
    assert comparison["999"] == {"status": "missing"}
    assert not any("rounds_delta" in v for k, v in comparison.items() if v["status"] != "ok")
