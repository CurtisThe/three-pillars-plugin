"""Round 17, F8/F9 — the index cross-check arms no test had pinned.

F8  `merge_driver.resolve_living_doc`'s FAIL-CLOSED except arm: when the cross-check itself cannot
    run, the file must defer. The mutation `mis_parse = None` in that arm passed every test.
F9  `stage_oracle`'s theirs-vs-stage-3 containment: the mutation dropping `("theirs", 3)` from
    `STAGE_OF_SIDE` passed every test, because every misroute fixture put its line on ours or base.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import merge_driver  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from resolve import RESOLVED, resolve_file  # noqa: E402
from stage_oracle import index_disagreement, parse_disagrees_with_index  # noqa: E402
from test_merge_driver import KI, git  # noqa: E402
from test_stage_oracle import _plain_mechanical_repo  # noqa: E402


@pytest.mark.parametrize("exc", [OSError("merge-file could not be spawned"),
                                 UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")])
def test_f8_a_cross_check_that_cannot_run_defers_the_file(tmp_path, monkeypatch, exc):
    repo = _plain_mechanical_repo(tmp_path)

    def _raises(**kw):
        raise exc
    monkeypatch.setattr(merge_driver, "index_disagreement", _raises)
    report = merge_back(str(repo), "master")
    assert KI in report.deferred and KI not in report.auto_resolved, report.to_json()
    outcome = next(o for o in report.outcomes if o["path"] == KI)
    assert "could not be cross-checked" in outcome["reason"], outcome
    assert git(repo, "ls-files", "-u", "--", KI).stdout.strip(), "the file must stay unmerged"


def test_f8_control_the_same_repo_auto_resolves_when_the_cross_check_runs(tmp_path):
    """Without the injected failure the merge is ordinary and stages — so the deferral above is the
    except arm's doing, not the fixture's."""
    repo = _plain_mechanical_repo(tmp_path)
    assert KI in merge_back(str(repo), "master").auto_resolved


# A RESOLVED log-entry-insertion hunk whose THEIRS side holds a line stage 3 never contained, while
# its ours side and (empty) base agree with stages 2 and 1 exactly.
F9_BASE = "## History\n\n- **2026-01-01** — old\n"
F9_OURS = "## History\n\n- **2026-09-01** — ours\n- **2026-01-01** — old\n"
F9_THEIRS = "## History\n\n- **2026-09-02** — theirs\n- **2026-01-01** — old\n"
F9_INVENTED = "- **2026-09-03** — a line theirs never wrote"
F9_TEXT = ("## History\n\n<<<<<<< ours\n- **2026-09-01** — ours\n||||||| base\n=======\n"
           "- **2026-09-02** — theirs\n" + F9_INVENTED + "\n>>>>>>> theirs\n- **2026-01-01** — old\n")


def test_f9_a_theirs_line_stage_3_never_had_is_a_disagreement():
    status, _lines, results = resolve_file(F9_TEXT)
    assert status == RESOLVED and results[0].label == "log-entry-insertion", "precondition"
    faults = parse_disagrees_with_index(base=F9_BASE, ours=F9_OURS, theirs=F9_THEIRS,
                                        conflict_text=F9_TEXT)
    assert len(faults) == 1, faults
    assert F9_INVENTED in faults[0] and "theirs side" in faults[0] and "stage 3" in faults[0]


def test_f9_control_the_faithful_text_has_no_disagreement():
    faithful = F9_TEXT.replace(F9_INVENTED + "\n", "")
    assert parse_disagrees_with_index(base=F9_BASE, ours=F9_OURS, theirs=F9_THEIRS,
                                      conflict_text=faithful) == []
    assert index_disagreement(base=F9_BASE, ours=F9_OURS, theirs=F9_THEIRS) is None


def test_a_region_count_that_disagrees_with_merge_file_is_a_disagreement():
    faults = parse_disagrees_with_index(base=F9_BASE, ours=F9_OURS, theirs=F9_THEIRS,
                                        conflict_text=F9_TEXT.replace(F9_INVENTED + "\n", ""),
                                        labels=("ours", "base", "theirs"), conflicts=2)
    assert faults and "wrote 2 conflict region(s) but the parse found 1" in faults[0], faults


def test_index_disagreement_hands_merge_files_region_count_to_the_parse_check(monkeypatch):
    """Round 18: `index_disagreement` must pass `conflicts=d.conflicts`; passing None survived,
    because only `parse_disagrees_with_index` was driven with a count."""
    import stage_oracle
    real = stage_oracle.diff3_conflict

    def _one_more(**kw):
        d = real(**kw)
        return type(d)(d.text, d.labels, d.conflicts + 1)
    monkeypatch.setattr(stage_oracle, "diff3_conflict", _one_more)
    msg = index_disagreement(base=F9_BASE, ours=F9_OURS, theirs=F9_THEIRS)
    assert msg and "wrote 2 conflict region(s) but the parse found 1" in msg, msg


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
