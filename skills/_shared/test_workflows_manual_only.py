"""Guard: the three GitHub workflows must be manual-only (workflow_dispatch).

self-hosted-ci-runner moved CI off GitHub-hosted runners (minutes exhaustion); the
workflows stay in the tree but must NOT auto-run on push/pull_request, or the billing
resumes silently. This test fails closed if any of them regains an auto-trigger.

Text/regex matching is deliberate — `yaml.safe_load` parses the bare key `on` as the
boolean `True`, so a parsed-dict assertion is a footgun. We match trigger *lines*
(`^\\s*push:` / `^\\s*pull_request:`) so prose like "every push to master" in a comment
does not produce a false positive.

Run with: pytest skills/_shared/test_workflows_manual_only.py -q
"""

import re
from pathlib import Path

import pytest

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
WORKFLOWS = ["framework-check.yml", "tests.yml", "security-scan.yml"]

_DISPATCH = re.compile(r"^\s*workflow_dispatch:", re.MULTILINE)
_PUSH = re.compile(r"^\s*push:", re.MULTILINE)
_PR = re.compile(r"^\s*pull_request:", re.MULTILINE)


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflow_is_manual_only(name):
    text = (WORKFLOWS_DIR / name).read_text(encoding="utf-8")
    assert _DISPATCH.search(text), f"{name}: missing workflow_dispatch trigger"
    assert not _PUSH.search(text), f"{name}: still has a push: trigger (would bill minutes)"
    assert not _PR.search(text), f"{name}: still has a pull_request: trigger (would bill minutes)"


def test_tests_workflow_runs_the_serial_lane_split():
    """The `serial` marker's first real user landed with a two-lane split in
    `tests.yml` mirroring `scripts/ci-local.sh` (which `test_ci_local_fast_lane.py`
    pins). Pin the workflow half too: the `-n auto` pass must exclude serial tests
    and a single-process `-m serial -n0` fallback must run them, with pytest-xdist
    installed so pytest.ini's `-n auto` addopts can even parse.
    """
    text = (WORKFLOWS_DIR / "tests.yml").read_text(encoding="utf-8")
    assert "pytest-xdist" in text, "tests.yml must install pytest-xdist (pytest.ini injects -n auto)"
    assert "-m 'not serial'" in text, "tests.yml main pass must exclude serial-marked tests"
    assert "-m serial -n0" in text, "tests.yml must run serial-marked tests single-process"
    # The serial lane's exit guard is fail-CLOSED: only pytest's 5 (nothing
    # collected) is tolerated; any other non-zero code must propagate.
    for needle in ("set +e", "rc=$?", "set -e", "[ $rc -eq 0 ]", "[ $rc -eq 5 ]", "|| exit $rc"):
        assert needle in text, f"tests.yml serial-lane exit guard lost {needle!r}"


# ---- The verifier suite must stay wired into BOTH gates ---------------------------------------

_VERIFIER_TREE = "skills/tp-merge-from-main/scripts/"


def test_the_merge_verifier_suite_runs_in_both_test_lanes_of_the_workflow():
    """`skills/tp-merge-from-main/scripts/` holds the zero-drop verifier's floor, superset and
    coverage invariants plus every silent-drop regression test. It ran in NEITHER gate — 22 files
    and 200+ tests reachable only by a hand-typed pytest invocation — so the merge driver's safety
    story was unenforced. Both lanes must name it, or it goes quiet again the same way.
    """
    text = (WORKFLOWS_DIR / "tests.yml").read_text(encoding="utf-8")
    lanes = [ln for ln in text.splitlines() if "python -m pytest" in ln]
    assert len(lanes) == 2, f"expected two pytest lanes in tests.yml, got {lanes}"
    for ln in lanes:
        assert _VERIFIER_TREE in ln, f"tests.yml lane does not run the verifier suite: {ln.strip()}"


def test_the_merge_verifier_suite_runs_in_ci_local():
    """The stamp-producing gate. `PYTEST_PATHS` is the single list both of its lanes expand, so
    pinning the array plus "every pytest invocation expands it" covers the fast lane too — and
    `--fast`'s meaning is unchanged: still xdist pytest + framework-check, still no stamp.
    """
    ci_local = WORKFLOWS_DIR.parents[1] / "scripts" / "ci-local.sh"
    text = ci_local.read_text(encoding="utf-8")
    assert f"PYTEST_PATHS=(skills/_shared/ {_VERIFIER_TREE})" in text, (
        "scripts/ci-local.sh must declare both test trees in PYTEST_PATHS")
    lanes = [ln for ln in text.splitlines() if "python -m pytest" in ln]
    assert len(lanes) == 4, f"expected four pytest lanes in ci-local.sh, got {lanes}"
    for ln in lanes:
        assert '"${PYTEST_PATHS[@]}"' in ln, f"a ci-local lane bypasses PYTEST_PATHS: {ln.strip()}"
