"""Doc guard: where `local-dispatch.md` puts the re-probe and the slot check's wait.

design: one-cheap-engine (impl-audit-1 B2 + note c). The re-probe exists for a `sonnet-*` rung that
`next` returns after a busy skip, so it must sit where every retry and escalation passes: §2 step 2's
`sonnet` bullet. Slicing is by heading and list marker, never by line number.
"""
from __future__ import annotations

import re
from pathlib import Path

DOC = (Path(__file__).resolve().parent / "local-dispatch.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(start: str, end: str) -> str:
    i = DOC.index(start)
    return DOC[i:DOC.index(end, i)]


def _sonnet_bullet() -> str:
    sec = _section("\n## 2.", "\n## 3.")
    m = re.search(r"\n   - `sonnet` / `opus`:.*?(?=\n\d+\. \*\*|\n   - `|\Z)", sec, re.S)
    assert m, "§2 step 2 has no `sonnet` / `opus` bullet"
    return _flat(m.group(0))


def _slot_check() -> str:
    sec = _section("\n## 3.", "\n## 4.")
    i = sec.index("\n2. **Slot check**")
    return _flat(sec[i:sec.index("\n3. Right after", i)])


def test_reprobe_in_the_sonnet_bullet_of_section_2():
    bullet = _sonnet_bullet()
    assert "ladder_busy.py reprobe --record <R> --design <slug>" in bullet, bullet
    assert "busy skip" in bullet and "spawn" in bullet, bullet


def test_reprobe_not_left_in_the_local_slot_check():
    assert "reprobe" not in _slot_check()


def test_reprobe_named_once_in_the_file():
    assert DOC.count("ladder_busy.py reprobe") == 1


def test_slot_check_wait_excepts_the_measurement_window_owner():
    step = _slot_check()
    assert "--wait-s 3" in step, step
    assert "except when this design owns the live measurement window" in step, step
    assert "omit it" in step and "270 s" in step, step
