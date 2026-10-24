"""Doc pins: the tp-worker dispatches open their worktree through worker_root.py.

design: classifier-no-verdict-nested-writes (Task 1.2)
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = ROOT / "skills" / "tp-run-full-design"


def _read(path):
    return path.read_text(encoding="utf-8")


def _tier3():
    text = _read(RUN / "tier-2-4-build.md")
    start = re.search(r"^## Tier 3$", text, re.M).start()
    return text[start:re.search(r"^## Tier 3\.5", text[start:], re.M).start() + start]


def test_tier3_reaps_then_opens_and_passes_the_worktree():
    body = _tier3()
    assert body.index("worker_root.py reap") < body.index("worker_root.py open")
    for token in ("WORKTREE:", "worktreePath", "worker-root-refused"):
        assert token in body, token


def test_tier3_tp_worker_span_has_no_isolation():
    body = _tier3()
    start = body.index('Agent(subagent_type=agent_ref("tp-worker")')
    depth = 0
    for i in range(body.index("(", start), len(body)):
        depth += {"(": 1, ")": -1}.get(body[i], 0)
        if depth == 0:
            break
    span = body[start:i + 1]
    assert "isolation" not in span
    assert not re.search(r'isolation="worktree"`?\s+is\s+mandatory', body)


def test_cert_fix_dispatch_opens_through_worker_root():
    line = next(l for l in _read(RUN / "tier-5-closeout.md").splitlines() if l.startswith("- `cert-fix`"))
    assert "worker_root.py open" in line
    assert line.index("worker_root.py reap") < line.index("worker_root.py open")
    assert 'isolation="worktree"' not in line


def test_cleanup_step_reaps_candidate_worktrees():
    text = _read(RUN / "SKILL.md")
    cleanup = text[text.index("## Cleanup"):]
    assert "worker_root.py reap" in cleanup


def test_boundary_contract_item_1_drops_the_auto_entry_branch():
    text = _read(RUN / "boundary-contracts.md")
    item1 = text[text.index("1. **Set up the candidate branch"):text.index("2. **Implement this phase")]
    assert not re.search(r"worktree-agent-\W+id", item1)
    assert "WORKTREE" in item1


def test_no_op_short_circuit_keys_on_the_opened_path():
    text = _read(RUN / "tier-2-4-build.md")
    start = re.search(r"^### No-op short-", text, re.M).start()
    body = text[start:re.search(r"^### Wrapper-", text[start:], re.M).start() + start]
    assert "worker_root.py open" in body


def test_waits_template_runs_behind_the_worktree_prefix():
    text = _read(ROOT / "agents" / "tp-worker.md")
    assert "cd <WORKTREE> && mkdir -p .tp-scratch/bg" in text


def test_tier3_snapshots_the_tip_and_asserts_it_unmoved():
    body = _tier3()
    assert body.index("worker_root.py tip") < body.index("worker_root.py assert-unmoved")
    assert "worker-escaped-worktree" in body


def test_tier3_phase_2_plus_opens_from_the_origin_candidate():
    body = _tier3()
    assert re.search(r"origin/candidate/\{slug\}/single", body)


def test_cert_fix_opens_from_the_fetched_origin_candidate():
    line = next(l for l in _read(RUN / "tier-5-closeout.md").splitlines() if l.startswith("- `cert-fix`"))
    assert re.search(r"--base-ref origin/candidate/\{slug\}/single", line)
    assert "git fetch" in line


def test_phase_check_fix_worker_gets_its_own_worktree():
    text = _read(ROOT / "skills" / "_shared" / "phase-check.md")
    start = re.search(r"^4\. \*\*Worker once\*\*", text, re.M).start()
    body = text[start:re.search(r"^5\. \*\*Tier 3\.5", text[start:], re.M).start() + start]
    for token in ("worker_root.py open", "WORKTREE:", "git fetch"):
        assert token in body, token
    assert re.search(r"--base-ref origin/candidate/\{slug\}/single", body)
    assert re.search(r"--phase\b", body)


def test_light_slot_8_fix_worker_opens_through_worker_root():
    text = _read(RUN / "SKILL.md")
    line = next(l for l in text.splitlines() if l.startswith("- **Slot 8** reviews the **candidate**"))
    assert "worker_root.py open" in line
