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
