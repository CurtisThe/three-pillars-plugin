"""test_learn_low_parts_ref.py — the Low-filing commands /tp-design-learn carries work.

design: basesync-count-line-and-low-headroom (Task 2.5)

`/tp-design-learn` files a new Low by running the `low_doc_parts.py target` /
`count` commands written in its own instructions. This test pins no wording: it
parses the inline code spans that carry those commands out of the shipped
SKILL.md, fills the placeholders, and RUNS them against a tmp repo whose part 1 is
near-full. The commands as written must name and create part 2 and print the total.

Shipped, so it reads only shipped files (the skill text plus `low_doc_parts.py`)
and builds every repo tree in `tmp_path`.

Run with: python3 -m pytest skills/_shared/test_learn_low_parts_ref.py -q
"""
from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import skill_text  # noqa: E402

_REPO_ROOT = _SHARED_DIR.parents[1]
_CMD_RE = re.compile(r"`(python3 [^`]*low_doc_parts\.py (?:target|count)[^`]*)`")
_PLACEHOLDER = re.compile(r"<[^`>]*>")


def _commands() -> dict[str, str]:
    """The `target` and `count` command spans the skill carries, by subcommand."""
    found: dict[str, str] = {}
    for span in _CMD_RE.findall(skill_text.read_skill_text("tp-design-learn")):
        cmd = span.split("low_doc_parts.py", 1)[1].split()[0]
        found.setdefault(cmd, span)
    return found


def _near_full_repo(tmp_path: Path, entries: int) -> Path:
    """A tmp repo whose Low part 1 is padded to 49,000 chars with `entries` Lows."""
    head = "# Known Issues — Low (cold)\n\n"
    entry = "### L100: pad low entry for the headroom test\n\n"
    body = entry * entries
    path = tmp_path / "three-pillars-docs/known_issues_low.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((head + body).ljust(49_000, "."), encoding="utf-8")
    return tmp_path


def _run(span: str, cwd: Path) -> str:
    """Run one skill-carried command: `$TP_ROOT` → this repo, every `<…>` → 120."""
    argv = shlex.split(span)
    argv[0] = sys.executable
    argv = [
        str(_REPO_ROOT / tok.split("$TP_ROOT/", 1)[1]) if "$TP_ROOT" in tok else tok
        for tok in argv
    ]
    argv = [_PLACEHOLDER.sub("120", tok) for tok in argv]
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_the_skill_carries_both_low_part_commands():
    cmds = _commands()
    assert "target" in cmds, "no `low_doc_parts.py target` command span in the skill"
    assert "count" in cmds, "no `low_doc_parts.py count` command span in the skill"


def test_the_carried_commands_split_a_near_full_part1(tmp_path):
    root = _near_full_repo(tmp_path, entries=40)
    cmds = _commands()
    target = _run(cmds["target"], root)
    assert target == "three-pillars-docs/known_issues_low_2.md"
    created = root / target
    assert created.is_file(), f"`target --create` did not create {target}"
    assert _run(cmds["count"], root) == "40"
