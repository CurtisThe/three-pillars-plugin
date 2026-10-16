"""test_spawn_model_placeholder.py — the spawn-model guard (Behavior 7, B16).

design: hybrid-routing-hardening (detailed-design.md §Spawn-model wiring)

Every `tp-task-worker` `Agent(...)` spawn, anywhere in `skills/**/*.md` or `agents/*.md`, must
carry exactly `model="{model}"` — never a literal `model="haiku"` / `model="opus"` / anything
else. A first attempt's spawn model is only ever the one `tier_ladder.py start`/`next` printed
(dd §`start` stdout contract); a hardcoded model literal in a spawn template would silently
reintroduce the no-Haiku-rule bug this design fixes (Behavior 7's regression).

Reuses `_agent_spans` / `TASK_WORKER_RE` from `test_cheap_tier_exclusions.py` (the same
paren-balanced `Agent(...)` matcher and `subagent_type="tp-task-worker"` regex), so the two
guards can never drift apart on what counts as a spawn.
"""
from __future__ import annotations

import re
from pathlib import Path

from test_cheap_tier_exclusions import _agent_spans, TASK_WORKER_RE

ROOT = Path(__file__).resolve().parent.parent.parent

_MODEL_KW_RE = re.compile(r"""model\s*=\s*(["'])(?P<value>.*?)\1""")


def _task_worker_spans(text: str) -> list[str]:
    """Every `Agent(...)` span text whose `subagent_type` is `tp-task-worker`."""
    return [text[s:e] for s, e in _agent_spans(text) if TASK_WORKER_RE.search(text[s:e])]


def find_violations(root: Path) -> list[str]:
    """Every `tp-task-worker` spawn under `root` whose `model=` is not exactly
    `"{model}"`, as `<rel path>: <reason>` strings."""
    out: list[str] = []
    paths = sorted({*(root / "skills").rglob("*.md"), *(root / "agents").glob("*.md")})
    for path in paths:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(root).as_posix()
        for span in _task_worker_spans(text):
            models = _MODEL_KW_RE.findall(span)
            if len(models) != 1:
                out.append(f"{rel}: spawn has {len(models)} model= keys, expected exactly 1")
                continue
            value = models[0][1]
            if value != "{model}":
                out.append(f"{rel}: spawn model is {value!r}, not the placeholder '{{model}}'")
    return out


def _count_spans(root: Path) -> int:
    total = 0
    for path in {*(root / "skills").rglob("*.md"), *(root / "agents").glob("*.md")}:
        total += len(_task_worker_spans(path.read_text(encoding="utf-8")))
    return total


def _write(root: Path, rel_path: str, text: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_repo_has_at_least_one_placeholder_spawn():
    assert _count_spans(ROOT) >= 1
    assert find_violations(ROOT) == []


def test_synthetic_haiku_pin_is_flagged(tmp_path):
    (tmp_path / "skills").mkdir()
    (tmp_path / "agents").mkdir()
    _write(tmp_path, "skills/x/SKILL.md",
           'Agent(subagent_type="tp-task-worker", model="haiku", description="task", prompt=p)\n')
    got = find_violations(tmp_path)
    assert len(got) == 1
    assert "skills/x/SKILL.md" in got[0]
    assert "'haiku'" in got[0]


def test_synthetic_opus_pin_is_flagged(tmp_path):
    (tmp_path / "skills").mkdir()
    (tmp_path / "agents").mkdir()
    _write(tmp_path, "agents/tp-x.md",
           'Agent(subagent_type="tp-task-worker", model="opus", description="task", prompt=p)\n')
    got = find_violations(tmp_path)
    assert len(got) == 1
    assert "agents/tp-x.md" in got[0]
    assert "'opus'" in got[0]


def test_placeholder_spawn_passes(tmp_path):
    (tmp_path / "skills").mkdir()
    (tmp_path / "agents").mkdir()
    _write(tmp_path, "skills/x/SKILL.md",
           'Agent(subagent_type="tp-task-worker", model="{model}", description="task", prompt=p)\n')
    assert find_violations(tmp_path) == []
    assert _count_spans(tmp_path) == 1


def test_non_task_worker_spawn_is_ignored(tmp_path):
    (tmp_path / "skills").mkdir()
    (tmp_path / "agents").mkdir()
    _write(tmp_path, "skills/x/SKILL.md",
           'Agent(subagent_type="general-purpose", model="haiku", prompt=p)\n')
    assert find_violations(tmp_path) == []
    assert _count_spans(tmp_path) == 0
