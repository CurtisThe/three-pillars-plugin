"""Tests for build_synth_prompt security (review-convergence 9.2).

The Slot-8 synth prompt carries the security lens: which brief the repo names,
the shared SECURITY_BAR text, the `category: "security"` tag, and the surfaces
the whole design diff touches (fail closed when the git read fails). Design:
review-convergence; see skills/_shared/test-fragility.md — assert the exact
rendered lines, with git stubbed through the run_git seam (no real repo).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import trust_boundary  # noqa: E402

from build_synth_prompt import build_synth_prompt  # noqa: E402

HEADING = "## Security"

# A tiny unified=0 diff text the fake run_git returns; the subprocess call site
# is an argv-subprocess surface (trust_boundary.PATTERNS row 1).
FAKE_DIFF = (
    "--- a/skills/x.py\n"
    "+++ b/skills/x.py\n"
    "@@ -1,0 +2 @@\n"
    "+subprocess.run(cmd, shell=True)\n"
)


def _fake_run_git(argv, cwd):
    assert argv[:3] == ["diff", "--unified=0", "--no-color"]
    return FAKE_DIFF


def _boom_run_git(argv, cwd):
    raise RuntimeError("git not available")


def _args(tmp_path):
    r1 = [{"member": "council-ada", "verdict": "pass-with-notes", "findings": []}]
    code_input = {"base": "tp/x", "candidate": "origin/candidate/x/single",
                  "touched_files": ["skills/x.py"]}
    return (["a.md"], r1, None, "impl-audit"), code_input


def test_security_block_names_shipped_checklist(tmp_path):
    # Red fixture: a repo dir WITHOUT a root SECURITY.md → the shipped checklist.
    repo = tmp_path / "repo"
    repo.mkdir()
    args, code_input = _args(tmp_path)
    out = build_synth_prompt(*args, code_input=code_input, repo=repo,
                             run_git=_fake_run_git)
    lines = out.splitlines()
    assert HEADING in lines
    assert f"Brief: read `{trust_boundary.CHECKLIST}` yourself." in lines
    assert trust_boundary.SECURITY_BAR in out
    assert 'security findings carry `category: "security"` exactly' in out
    # The surfaces of the whole design diff, one per line.
    assert "- `argv-subprocess` skills/x.py:2" in lines
    # The block sits before "## Round 1 — independent verdicts".
    assert lines.index(HEADING) < lines.index("## Round 1 — independent verdicts")


def test_surfaces_unavailable_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    args, code_input = _args(tmp_path)
    out = build_synth_prompt(*args, code_input=code_input, repo=repo,
                             run_git=_boom_run_git)
    lines = out.splitlines()
    assert HEADING in lines
    fail_closed = [ln for ln in lines if ln.startswith("- surfaces unavailable (")]
    assert len(fail_closed) == 1
    assert "treat every touched file as in scope" in fail_closed[0]


def test_repo_none_means_no_security_block():
    args, code_input = _args(None)
    out = build_synth_prompt(*args, code_input=code_input)
    assert HEADING not in out


def test_code_input_none_means_no_security_block(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    args, _ = _args(tmp_path)
    out = build_synth_prompt(*args, repo=repo, run_git=_fake_run_git)
    assert HEADING not in out


def test_finding_fields_are_requested():
    # Every slot asks for the finding fields the orchestrator folds downstream.
    from build_synth_prompt import FIELD_REQUEST
    for slot in ("design-audit", "plan-audit", "impl-audit"):
        r1 = [{"member": "council-ada", "verdict": "pass-with-notes", "findings": []}]
        out = build_synth_prompt(["a.md"], r1, None, slot)
        assert FIELD_REQUEST in out
        for token in ("`file`", "`line`", "`run_failure`", "critical|medium|minor"):
            assert token in FIELD_REQUEST, token
