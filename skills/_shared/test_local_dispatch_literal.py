"""test_local_dispatch_literal.py — local-dispatch.md's commands run verbatim in tp-worker (seat G5).

design: run-throughput (PR #178 live check #3 item 4). Inside a worktree-isolated `tp-worker`,
Claude Code's own isolation check refused the documented forms: a `$TP_ROOT`-built script path
("runs python with a value computed at runtime"), `$(git rev-parse --git-common-dir)` and
`${…}` expansions ("names git in a form too complex to verify"). That check is the harness's,
not a module in this repo, so `computed()` is a conservative model of it, calibrated below
against the verdicts it returned in that run (commands scrubbed of their paths).

The documented commands are extracted from the doc's fenced shell blocks and its inline
helper invocations (data extraction, not prose needles), each must carry no computed
argument, and the §2 ladder block is executed verbatim in a fixture repo.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from attempt_fixture import IDENTITY, make_seat  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402

DOC = (HERE / "local-dispatch.md").read_text(encoding="utf-8")
TP = str(HERE.parent.parent)
_COMPUTED = re.compile(r"\$\(|`|\$\{|\$[A-Za-z_]")  # `$?` (a status echo) passed live

# Verdicts the harness returned inside the live check's tp-worker (S = the scratchpad).
REFUSED = [
    "export TP_ROOT=/S/rt; cd /S/fx/.claude/worktrees/agent-a\n"
    "python3 $TP_ROOT/skills/_shared/cwd_preflight.py probe; echo \"exit=$?\"",
    "cd /S/fx/.claude/worktrees/agent-a\nL=\"$(git rev-parse --git-common-dir)/tp-ladder/probe\"; "
    "mkdir -p \"$L\"\npython3 /S/rt/skills/_shared/tier_ladder.py start --task 2.1 --tier "
    "local-medium --record \"$L/2.1.json\" --root .",
    "python3 /S/rt/skills/_shared/attempt_watchdog.py orphans --dir /S/fx/.git/tp-ladder/probe "
    "--phase 2 --config-dir \"${CLAUDE_CONFIG_DIR:-$HOME/.claude}\"",
    "date -u +%FT%TZ && python3 /S/rt/skills/_shared/attempt_watchdog.py poll --state "
    "/S/fx/.git/tp-ladder/probe/2.1.watch.json --root . --config-dir /cfg | tee "
    "/S/fx/.git/tp-ladder/probe/2.1.poll.json; echo \"exit=${PIPESTATUS[0]}\"",
]
ACCEPTED = [
    "mkdir -p /S/fx/.git/tp-ladder/probe",
    "python3 /S/rt/skills/_shared/tier_ladder.py start --task 2.1 --tier local-medium --record "
    "/S/fx/.git/tp-ladder/probe/2.1.json --root . --route '{\"schema\": \"tp-local-route/v1\"}'",
    "python3 /S/rt/skills/_shared/attempt_watchdog.py orphans --dir /S/fx/.git/tp-ladder/probe "
    "--phase 2 --config-dir /cfg; echo \"exit=$?\"",
    "python3 /S/rt/skills/_shared/attempt_watchdog.py poll --state "
    "/S/fx/.git/tp-ladder/probe/2.1.watch.json --root . --config-dir /cfg | tee "
    "/S/fx/.git/tp-ladder/probe/2.1.poll.json",
    "python3 /S/rt/skills/_shared/attempt_scan.py scan --agent-id a0 --config-dir /cfg > "
    "/S/fx/.git/tp-ladder/probe/2.1.scan.json; echo \"exit=$?\"",
]


def computed(cmd: str) -> list[str]:
    """The computed-argument forms in ``cmd`` (the harness refuses any of them)."""
    return _COMPUTED.findall(cmd)


def documented_commands(doc: str = DOC) -> list[str]:
    """Every helper invocation the doc tells a dispatcher to run: each line of a fenced
    shell block, plus every inline code span naming a ``.py`` helper with arguments."""
    cmds = []
    for lang, body in re.findall(r"```(\w*)\n(.*?)```", doc, re.S):
        if lang in ("bash", "sh", ""):
            cmds += [ln.strip() for ln in body.splitlines() if ".py" in ln]
    prose = re.sub(r"```.*?```", "", doc, flags=re.S)
    spans = [" ".join(s.split()) for s in re.findall(r"`([^`]+)`", prose)]  # markdown pairing
    cmds += [s for s in spans if re.search(r"\w\.py \S", s)]
    return cmds


def test_model_matches_the_recorded_harness_verdicts():
    assert all(computed(c) for c in REFUSED)
    assert not any(computed(c) for c in ACCEPTED)


def test_every_documented_command_is_literal():
    cmds = documented_commands()
    assert len(cmds) >= 20, cmds
    for needed in ("ladder_files.py paths", "tier_ladder.py start", "attempt_watchdog.py poll",
                   "--finished | tee <P>", "attempt_watchdog.py orphans", "task_verify.py check",
                   "attempt_scan.py scan", "tier_ladder.py next"):
        assert any(needed in c for c in cmds), needed
    bad = {c: computed(c) for c in cmds if computed(c)}
    assert bad == {}


def test_documented_scripts_exist():
    scripts = {m for c in documented_commands() for m in re.findall(r"<TP>/(\S+\.py)", c)}
    assert "skills/_shared/ladder_files.py" in scripts
    assert [s for s in scripts if not (Path(TP) / s).is_file()] == []


def _render(line: str, values: dict) -> str:
    line = re.sub(r"<--route-from [^|]+\| (--route '<ROUTE json>')>", r"\1", line)
    for key, value in values.items():
        line = line.replace(f"<{key}>", value)
    assert "<" not in line and not computed(line), line
    return line


def test_section_2_ladder_block_runs_verbatim(tmp_path):
    """The §2 block, rendered with literal values only, runs as written in a fixture repo."""
    _seat, wt = make_seat(tmp_path)
    block = re.search(r"```bash\n(.*?)```", DOC.split("## 2. Per row", 1)[1], re.S).group(1)
    lines = [ln for ln in block.splitlines() if ln.strip()]
    route = json.dumps({"schema": "tp-local-route/v1", "state": "unrouted",
                        "reason": "no-base-url", "base_url": None,
                        "checked_at": "2026-09-29T00:00:00Z"})
    values = {"TP": TP, "slug": "demo", "id": "1.1", "start_rung": "sonnet-medium",
              "ROUTE json": route}
    env = clean_git_env(**IDENTITY)
    outs = []
    for line in lines:
        cmd = _render(line, values)
        proc = subprocess.run(["bash", "-c", cmd], cwd=str(wt), capture_output=True, text=True,
                              env=env, timeout=120)
        assert proc.returncode == 0, (cmd, proc.stderr)
        outs.append(json.loads(proc.stdout))
        values["R"] = outs[0]["record"]  # the literal path `paths` printed
    assert Path(outs[0]["record"]).is_file()
    assert outs[1]["rung"] == "sonnet-medium" and outs[1]["agent_ref"]
