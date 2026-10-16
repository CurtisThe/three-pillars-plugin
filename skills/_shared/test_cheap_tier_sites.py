"""Guard: cheap-tier site stubs sit only where `SLOT_SITES` allows, and say only safe things.

design: cheap-tier-offload (Task 3.7; audits #1, #5, #9).

A site stub is the block between `<!-- cheap-tier:<slot> -->` and `<!-- /cheap-tier -->`
in a SKILL.md. `find_violations(root)` checks every stub under `skills/`, the protocol
doc `skills/_shared/cheap-dispatch.md` and the cheap agent files. The per-phase site
tests (`test_cheap_tier_lever_sites.py`, `test_cheap_tier_slot_sites.py`,
`test_cheap_tier_prose_sites.py`) import `stubs`, `argument_hint` and `SLOT_SITES` from
here; this file holds only the guard.
"""
from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_tier  # noqa: E402
from test_cheap_tier_exclusions import CHEAP_MODEL_RE, GUARDED_SKILL_GLOBS  # noqa: E402
from weight_class import parse_frontmatter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
DISPATCH_DOC = "skills/_shared/cheap-dispatch.md"

# slot -> the files its stub may sit in (slots doc §Site wiring, minus plan.md
# Deviations 2-4). `task` has no stub: it is the Tier 3 lever.
SLOT_SITES: dict[str, tuple[str, ...]] = {
    "runbook": ("skills/tp-post-merge/SKILL.md",),
    "base_sync_splice": ("skills/tp-merge-from-main/SKILL.md",),
    "pr_fix_reproducer": ("skills/tp-pr-fix/SKILL.md",),
    "classifier_judge": ("skills/tp-pr-fix/SKILL.md", "skills/tp-pr-iterate/SKILL.md",
                         "skills/tp-pr-iterate/cheap-tier.md"),
    "handoff": ("skills/tp-session-save/SKILL.md",),
    "history_line": ("skills/tp-design-learn/SKILL.md", "skills/tp-docs-update/SKILL.md"),
    "docs_draft": ("skills/tp-design-learn/SKILL.md", "skills/tp-docs-update/SKILL.md"),
    # cheap-tier-review-prep: the four review-prep slots share one protocol file
    "review_slice": ("skills/tp-pr-iterate/cheap-tier.md",),
    "review_refs": ("skills/tp-pr-iterate/cheap-tier.md",),
    "ci_log_triage": ("skills/tp-pr-iterate/cheap-tier.md",),
    "repro_scaffold": ("skills/tp-pr-iterate/cheap-tier.md",),
}

STUB_RE = re.compile(r"<!-- cheap-tier:([A-Za-z0-9_-]+) -->(.*?)<!-- /cheap-tier -->", re.S)
OPEN_RE = re.compile(r"<!-- cheap-tier:([A-Za-z0-9_-]+) -->")
GATE_BANS = ("ci_local_stamp", "ci-local.sh", "gh pr merge")
BYPASS_RE = re.compile(r"--no-verify|--force(?![-\w])")
SPEC_CALL = "cheap_tier_cli.py spec"
SCRIPT_CALL_RE = re.compile(r"\b(?:python3|bash)\s+(\S+)")
CHEAP_AGENTS = ("tp-drafter*.md", "tp-runbook*.md")
DISPATCH_PINS = (
    "non-zero exit or unparseable output from `check` is `SLOTS[slot].on_fail`",
    "`cheap_ab.py budget` before each pair",
    "[cheap-tier] ab budget exhausted: <slot> ships opt-in",
    "cheap_ab.py alt-arm",
    "alt:<slot>",
    "`--oracle` with `--slot` takes only `pass` or `fail`",
)
RECORD_FLAGS = ("--rung <spec.rung>", "--slot", "--oracle", "--escalated")


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def stubs(root: Path) -> list[tuple[str, str, str]]:
    """`(file, slot, body)` for every stub in `skills/**/*.md` under `root`."""
    out = []
    for path in sorted((root / "skills").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        out += [(rel(root, path), m.group(1), m.group(2)) for m in STUB_RE.finditer(text)]
    return out


def argument_hint(path: Path) -> str:
    return str(parse_frontmatter(path.read_text(encoding="utf-8")).get("argument-hint") or "")


def _skill(file: str) -> str:
    parts = file.split("/")
    return parts[1] if len(parts) > 2 and parts[0] == "skills" else ""


def _stub_violations(root: Path) -> list[str]:
    out = []
    for file, slot, body in stubs(root):
        where, skill = f"{file}: cheap-tier:{slot}", _skill(file)
        if slot not in cheap_tier.SLOTS or slot == "task":
            out.append(f"{where}: not a stub slot")
        elif file not in SLOT_SITES.get(slot, ()):
            out.append(f"{where}: not in SLOT_SITES[{slot!r}]")
        if DISPATCH_DOC not in body:
            out.append(f"{where}: does not cite {DISPATCH_DOC}")
        if skill == "tp-merge" or "audit" in skill or skill == "council":
            out.append(f"{where}: no stub may sit in {skill}")
        out += [f"{where}: names {ban!r}" for ban in GATE_BANS if ban in body]
        out += [f"{where}: bypass flag {m.group(0)!r}" for m in BYPASS_RE.finditer(body)]
        out += [f"{where}: script call {arg!r} lacks the \"$TP_ROOT\"/skills/ prefix"
                for arg in SCRIPT_CALL_RE.findall(body)
                if not arg.startswith('"$TP_ROOT"/skills/')]
        if CHEAP_MODEL_RE.search(body):
            guarded = any(fnmatch.fnmatchcase(skill, g) for g in GUARDED_SKILL_GLOBS)
            out.append(f"{where}: model literal{' in a guarded skill' if guarded else ''}")
        # one-cheap-engine 2.7: passing the retired `--cheap-tier <mode>` is optional; a stub
        # that still does must have its SKILL.md argument-hint list the flag (so it parses).
        hint = file if file.endswith("SKILL.md") else f"skills/{skill}/SKILL.md"
        if "--cheap-tier <mode>" in body and "--cheap-tier" not in argument_hint(root / hint):
            out.append(f"{file}: argument-hint lacks --cheap-tier")
    return out


def _file_violations(root: Path) -> list[str]:
    out = []
    for path in sorted((root / "skills").rglob("*.md")) + sorted((root / "agents").glob("*.md")):
        text, file = path.read_text(encoding="utf-8"), rel(root, path)
        if file == DISPATCH_DOC:
            continue
        if len(OPEN_RE.findall(text)) != len(STUB_RE.findall(text)):
            out.append(f"{file}: unclosed cheap-tier stub")
        if SPEC_CALL in STUB_RE.sub("", text):
            out.append(f"{file}: {SPEC_CALL!r} outside a stub")
    agents = sorted(p for g in CHEAP_AGENTS for p in (root / "agents").glob(g))
    for path in agents:
        text, file = path.read_text(encoding="utf-8"), rel(root, path)
        out += [f"{file}: names {ban!r}" for ban in GATE_BANS if ban in text]
        if path.name.startswith("tp-drafter"):
            out += [f"{file}: bypass flag {m.group(0)!r}" for m in BYPASS_RE.finditer(text)]
    return out


def _dispatch_doc_violations(root: Path) -> list[str]:
    path = root / DISPATCH_DOC
    if not path.is_file():
        return [f"{DISPATCH_DOC}: missing"]
    text = path.read_text(encoding="utf-8")
    out = [f"{DISPATCH_DOC}: bypass flag {m.group(0)!r}" for m in BYPASS_RE.finditer(text)]
    out += [f"{DISPATCH_DOC}: lacks {pin!r}" for pin in DISPATCH_PINS if pin not in text]
    record = [line for line in text.splitlines() if "dispatch_log.py record" in line]
    if not record:
        out.append(f"{DISPATCH_DOC}: no dispatch_log.py record step")
    out += [f"{DISPATCH_DOC}: record step lacks {flag!r}" for flag in RECORD_FLAGS
            if not any(flag in line for line in record)]
    return out


def find_violations(root: Path) -> list[str]:
    root = Path(root)
    return _stub_violations(root) + _file_violations(root) + _dispatch_doc_violations(root)


def test_live_tree_is_clean():
    assert find_violations(ROOT) == []


def test_slot_sites_cover_every_stub_slot():
    assert set(SLOT_SITES) == set(cheap_tier.SLOTS) - {"task"}
    for files in SLOT_SITES.values():
        assert all((ROOT / f).is_file() for f in files), files


# --- tmp-tree cases: each check fires ------------------------------------------------

GOOD = ('<!-- cheap-tier:handoff -->\nRun python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py '
        'spec --slot handoff --cheap-tier <mode> per skills/_shared/cheap-dispatch.md.\n'
        '<!-- /cheap-tier -->\n')
HINT = '---\nname: x\nargument-hint: "{name} [--cheap-tier[=ab]]"\n---\n'


def _tree(tmp_path: Path) -> Path:
    doc = (ROOT / DISPATCH_DOC).read_text(encoding="utf-8")
    (tmp_path / "skills" / "_shared").mkdir(parents=True)
    (tmp_path / "agents").mkdir()
    (tmp_path / DISPATCH_DOC).write_text(doc, encoding="utf-8")
    _put(tmp_path, "skills/tp-session-save/SKILL.md", HINT + GOOD)
    return tmp_path


def _put(root: Path, file: str, text: str) -> None:
    (root / file).parent.mkdir(parents=True, exist_ok=True)
    (root / file).write_text(text, encoding="utf-8")


def test_a_clean_tree_passes(tmp_path):
    assert find_violations(_tree(tmp_path)) == []


def test_stub_placement_checks_fire(tmp_path):
    root = _tree(tmp_path)
    _put(root, "skills/tp-guide/SKILL.md", HINT + GOOD)
    _put(root, "skills/tp-merge/SKILL.md", HINT + GOOD)
    _put(root, "skills/tp-plan-audit/SKILL.md", HINT + GOOD.replace("handoff", "task"))
    _put(root, "skills/council/SKILL.md", HINT + GOOD.replace("handoff", "bogus"))
    got = find_violations(root)
    assert "skills/tp-guide/SKILL.md: cheap-tier:handoff: not in SLOT_SITES['handoff']" in got
    assert "skills/tp-merge/SKILL.md: cheap-tier:handoff: no stub may sit in tp-merge" in got
    assert "skills/tp-plan-audit/SKILL.md: cheap-tier:task: not a stub slot" in got
    assert "skills/tp-plan-audit/SKILL.md: cheap-tier:task: no stub may sit in tp-plan-audit" in got
    assert "skills/council/SKILL.md: cheap-tier:bogus: not a stub slot" in got


def test_stub_content_checks_fire(tmp_path):
    root = _tree(tmp_path)
    bad = ('<!-- cheap-tier:handoff -->\npython3 skills/_shared/cheap_tier_cli.py spec '
           '--slot handoff --cheap-tier on, model="sonnet", then ci-local.sh and '
           'commit --no-verify or push --force.\n<!-- /cheap-tier -->\n')
    _put(root, "skills/tp-session-save/SKILL.md", "---\nname: x\n---\n" + bad)
    got = [v.split(": ", 2)[-1] for v in find_violations(root)]
    assert "does not cite skills/_shared/cheap-dispatch.md" in got
    assert "names 'ci-local.sh'" in got
    assert "bypass flag '--no-verify'" in got and "bypass flag '--force'" in got
    assert "script call 'skills/_shared/cheap_tier_cli.py' lacks the \"$TP_ROOT\"/skills/ prefix" in got
    assert "model literal" in got
    # one-cheap-engine 2.7: the flag is retired; a stub need not pass it nor the hint list it
    assert "does not pass --cheap-tier <mode>" not in got
    assert "argument-hint lacks --cheap-tier" not in " ".join(find_violations(root))


def test_stub_without_the_retired_flag_is_clean(tmp_path):
    root = _tree(tmp_path)
    bare = GOOD.replace(" --cheap-tier <mode>", "")
    _put(root, "skills/tp-session-save/SKILL.md", "---\nname: x\n---\n" + bare)
    assert find_violations(root) == []


def test_guarded_skill_model_literal_is_named(tmp_path):
    root = _tree(tmp_path)
    _put(root, "skills/tp-merge-from-main/SKILL.md", HINT + GOOD.replace(
        "handoff", "base_sync_splice").replace("per skills", "on haiku per skills"))
    assert ("skills/tp-merge-from-main/SKILL.md: cheap-tier:base_sync_splice: model literal "
            "in a guarded skill") in find_violations(root)


def test_force_takeover_is_not_a_bypass_flag(tmp_path):
    root = _tree(tmp_path)
    _put(root, "skills/tp-session-save/SKILL.md",
         HINT + GOOD.replace("per skills", "(hint: --force-takeover) per skills"))
    assert find_violations(root) == []


def test_file_checks_fire(tmp_path):
    root = _tree(tmp_path)
    _put(root, "skills/tp-guide/SKILL.md", "Run cheap_tier_cli.py spec here.\n"
         "<!-- cheap-tier:handoff -->\nno close\n")
    _put(root, "agents/tp-drafter.md", "never gh pr merge, never --no-verify\n")
    _put(root, "agents/tp-runbook.md", "never write ci_local_stamp; never --force\n")
    got = find_violations(root)
    assert "skills/tp-guide/SKILL.md: unclosed cheap-tier stub" in got
    assert "skills/tp-guide/SKILL.md: 'cheap_tier_cli.py spec' outside a stub" in got
    assert "agents/tp-drafter.md: names 'gh pr merge'" in got
    assert "agents/tp-drafter.md: bypass flag '--no-verify'" in got
    assert "agents/tp-runbook.md: names 'ci_local_stamp'" in got
    assert not any("tp-runbook.md: bypass" in v for v in got)  # its no-bypass line predates


def test_dispatch_doc_checks_fire(tmp_path):
    root = _tree(tmp_path)
    doc = (root / DISPATCH_DOC).read_text(encoding="utf-8")
    doc = doc.replace("--rung <spec.rung>", "--rung R").replace("alt:<slot>", "alt")
    (root / DISPATCH_DOC).write_text(doc + "\nnever --no-verify\n", encoding="utf-8")
    got = find_violations(root)
    assert f"{DISPATCH_DOC}: bypass flag '--no-verify'" in got
    assert f"{DISPATCH_DOC}: lacks 'alt:<slot>'" in got
    assert f"{DISPATCH_DOC}: record step lacks '--rung <spec.rung>'" in got
    (root / DISPATCH_DOC).unlink()
    assert f"{DISPATCH_DOC}: missing" in find_violations(root)
