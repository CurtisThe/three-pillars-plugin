#!/usr/bin/env python3
"""
Deterministic plan audit — structural consistency checks.

Verifies:
  1. Task completeness: every task has required fields
  2. Module coverage: every detailed-design module referenced in plan
  3. Interface coverage: every detailed-design interface mentioned in plan
  4. Phase alignment: plan phases match detailed-design phases
  5. File existence: modified files exist, new file parents exist

Usage: python3 audit_plan.py <design-dir> [--spike]
  --spike: Spike mode — expects Hypothesis/Try/Evaluate fields instead of
           File/Test/Red/Green. Skips detailed-design.md checks entirely.
Exit code: 0 = pass, 1 = issues found, 2 = bad input
"""

import sys
import re
from pathlib import Path
from collections import defaultdict


def read_file(path):
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return None


def extract_section(text, header_re, level=2):
    """Extract content under a heading matching header_re at given level."""
    prefix = "#" * level
    lines = text.split("\n")
    start = end = None
    for i, line in enumerate(lines):
        if start is None:
            if re.match(rf"^{prefix}\s+{header_re}", line, re.IGNORECASE):
                start = i + 1
        else:
            if re.match(rf"^#{{1,{level}}}\s+", line):
                end = i
                break
    if start is None:
        return ""
    return "\n".join(lines[start:end])


def extract_bullets(text):
    return [
        m.group(1).strip()
        for line in text.split("\n")
        if (m := re.match(r"\s*[-*]\s+(.+)", line))
    ]


def extract_bold_names(text):
    names = []
    for line in text.split("\n"):
        m = re.match(r"\s*[-*]\s+\*\*(.+?)\*\*", line) or re.match(
            r"\s*\d+\.\s+\*\*(.+?)\*\*", line
        )
        if m:
            names.append(m.group(1).strip())
    return names


STANDARD_FIELDS = ("File", "Test", "Red", "Green", "Refactor", "Done when", "Status")
SPIKE_FIELDS = ("Hypothesis", "Try", "Evaluate", "Status")


def extract_tasks(plan_text, spike_mode=False):
    """Extract tasks from plan.md."""
    tasks = []
    current_task = None
    current_phase = None
    fields_to_check = SPIKE_FIELDS if spike_mode else STANDARD_FIELDS

    for line in plan_text.split("\n"):
        pm = re.match(r"^##\s+Phase\s+(\d+)", line)
        if pm:
            current_phase = int(pm.group(1))
            continue

        tm = re.match(r"^###\s+Task\s+([\d.]+):\s*(.+)", line)
        if tm:
            if current_task:
                tasks.append(current_task)
            current_task = {
                "id": tm.group(1),
                "name": tm.group(2).strip(),
                "phase": current_phase,
                "fields": {},
                "raw": "",
            }
            continue

        if current_task:
            current_task["raw"] += line + "\n"
            for field in fields_to_check:
                fm = re.match(rf"^\*\*{re.escape(field)}\*\*:\s*(.+)", line)
                if fm:
                    current_task["fields"][field] = fm.group(1).strip()

    if current_task:
        tasks.append(current_task)
    return tasks


def backtick_paths(text):
    """Extract backtick-wrapped file paths from text."""
    return re.findall(r"`([^`\s]+\.[a-zA-Z]\w*)`", text)


def extract_module_files(detailed):
    section = extract_section(detailed, r"Module Structure")
    return [
        m.group(1)
        for line in section.split("\n")
        if (m := re.match(r"\s*[-*]\s+`([^`]+)`", line))
    ]


def extract_interface_names(detailed):
    section = extract_section(detailed, r"Interfaces")
    names = []
    for line in section.split("\n"):
        m = re.match(r"^###\s+`(.+?)`", line)
        if m:
            names.append(m.group(1).strip())
    return names


def extract_design_phases(detailed):
    section = extract_section(detailed, r"Implementation Order")
    return [
        m.group(1).strip()
        for line in section.split("\n")
        if (m := re.match(r"^###\s+Phase\s+\d+:\s*(.+)", line))
    ]


# ── Checks ────────────────────────────────────────────────


def check_completeness(tasks, spike_mode=False):
    """Every task must have required fields with non-empty values."""
    required = ("Hypothesis", "Try", "Evaluate") if spike_mode else ("File", "Test", "Red", "Green", "Done when")
    issues = []
    for t in tasks:
        missing = [f for f in required if f not in t["fields"]]
        empty = [
            f
            for f in required
            if f in t["fields"] and not t["fields"][f].strip()
        ]
        if missing:
            issues.append(
                (
                    "INCOMPLETE",
                    f"Task {t['id']}: {t['name']}",
                    f"Missing fields: {', '.join(missing)}",
                )
            )
        if empty:
            issues.append(
                (
                    "INCOMPLETE",
                    f"Task {t['id']}: {t['name']}",
                    f"Empty fields: {', '.join(empty)}",
                )
            )
    return issues


def check_module_coverage(tasks, modules):
    """Every file in detailed-design Module Structure must appear in a plan task."""
    task_files = set()
    for t in tasks:
        task_files.update(backtick_paths(t["fields"].get("File", "")))
        task_files.update(backtick_paths(t["raw"]))
    issues = []
    for mod in modules:
        if not any(mod in tf or tf in mod for tf in task_files):
            issues.append(
                (
                    "MISSING",
                    None,
                    f"Module `{mod}` in detailed design has no plan task",
                )
            )
    return issues


def check_interface_coverage(tasks, interfaces):
    """Every interface in detailed-design must be mentioned in the plan."""
    plan_blob = " ".join(t["name"] + " " + t["raw"] for t in tasks)
    issues = []
    for iface in interfaces:
        func = re.match(r"(\w+)", iface)
        if func and func.group(1) not in plan_blob:
            issues.append(
                (
                    "MISSING",
                    None,
                    f"Interface `{iface}` in detailed design not found in plan",
                )
            )
    return issues


def check_phase_alignment(tasks, design_phases):
    """Plan phase count should match detailed-design Implementation Order."""
    plan_phases = sorted(set(t["phase"] for t in tasks if t["phase"]))
    if len(plan_phases) != len(design_phases):
        return [
            (
                "INCONSISTENT",
                None,
                f"Plan has {len(plan_phases)} phase(s), detailed design has {len(design_phases)}",
            )
        ]
    return []


def check_file_existence(tasks):
    """Modified files should exist; new files should have valid parent dirs."""
    issues = []
    for t in tasks:
        ff = t["fields"].get("File", "")
        for path in backtick_paths(ff):
            p = Path(path)
            if "modify" in ff.lower() and not p.exists():
                issues.append(
                    (
                        "WARN",
                        f"Task {t['id']}",
                        f"`{path}` marked for modification does not exist",
                    )
                )
            elif "new" in ff.lower() and not p.parent.exists():
                issues.append(
                    (
                        "WARN",
                        f"Task {t['id']}",
                        f"Parent dir for new file `{path}` does not exist",
                    )
                )
    return issues


# ── Main ──────────────────────────────────────────────────


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    spike_mode = "--spike" in flags

    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} <design-dir> [--spike]", file=sys.stderr)
        sys.exit(2)

    d = Path(args[0])
    design = read_file(d / "design.md")
    plan = read_file(d / "plan.md")

    required_files = [("design.md", design), ("plan.md", plan)]
    if not spike_mode:
        detailed = read_file(d / "detailed-design.md")
        required_files.append(("detailed-design.md", detailed))
    else:
        detailed = None

    for name, content in required_files:
        if not content:
            print(f"ERROR: {name} not found in {d}")
            sys.exit(2)

    # Extract structural elements
    tasks = extract_tasks(plan, spike_mode=spike_mode)

    print("=" * 60)
    print(f"PLAN AUDIT — DETERMINISTIC CHECKS{' (SPIKE MODE)' if spike_mode else ''}")
    print("=" * 60)
    print()

    if spike_mode:
        # Spike mode: check design.md for hypothesis/experiments coverage
        hypothesis = extract_section(design, r"Hypothesis")
        experiments = extract_section(design, r"Experiments")
        success = extract_section(design, r"Success Criteria")
        plan_phase_count = len(set(t["phase"] for t in tasks if t["phase"]))
        print(f"Design:   hypothesis={'yes' if hypothesis.strip() else 'MISSING'}, "
              f"experiments={'yes' if experiments.strip() else 'MISSING'}, "
              f"success criteria={'yes' if success.strip() else 'MISSING'}")
        print(f"Plan:     {len(tasks)} tasks across {plan_phase_count} phases")
        print()

        # Spike checks: completeness + deliverable presence
        all_issues = check_completeness(tasks, spike_mode=True)

        # Check each phase has a Deliverable line
        phase_deliverables = set()
        for line in plan.split("\n"):
            pm = re.match(r"^##\s+Phase\s+(\d+)", line)
            if pm:
                current = int(pm.group(1))
            if re.match(r"^\*\*Deliverable\*\*:", line):
                phase_deliverables.add(current if 'current' in dir() else 0)
        phases_in_plan = set(t["phase"] for t in tasks if t["phase"])
        for p in phases_in_plan:
            if p not in phase_deliverables:
                all_issues.append(("INCOMPLETE", f"Phase {p}", "Missing **Deliverable** line"))

    else:
        modules = extract_module_files(detailed)
        interfaces = extract_interface_names(detailed)
        d_phases = extract_design_phases(detailed)
        in_scope = extract_bullets(extract_section(design, r"In scope", 3))
        entities = extract_bold_names(extract_section(design, r"Entities"))
        behaviors = extract_bold_names(extract_section(design, r"Behaviors"))

        print(
            f"Design:   {len(in_scope)} in-scope, "
            f"{len(entities)} entities, {len(behaviors)} behaviors"
        )
        print(
            f"Detailed: {len(modules)} modules, "
            f"{len(interfaces)} interfaces, {len(d_phases)} phases"
        )
        plan_phase_count = len(set(t["phase"] for t in tasks if t["phase"]))
        print(f"Plan:     {len(tasks)} tasks across {plan_phase_count} phases")
        print()

        # Run all standard checks
        all_issues = (
            check_completeness(tasks)
            + check_module_coverage(tasks, modules)
            + check_interface_coverage(tasks, interfaces)
            + check_phase_alignment(tasks, d_phases)
            + check_file_existence(tasks)
        )

    if not all_issues:
        print("RESULT: ALL CHECKS PASSED")
        print()
        print("Verified: task fields, module coverage, interface coverage,")
        print("phase alignment, file existence.")
        return 0

    cats = defaultdict(list)
    for typ, ctx, msg in all_issues:
        cats[typ].append((ctx, msg))

    for cat in ("MISSING", "INCONSISTENT", "INCOMPLETE", "WARN"):
        if cat in cats:
            print(f"--- {cat} ({len(cats[cat])}) ---")
            for ctx, msg in cats[cat]:
                if ctx:
                    print(f"  [{ctx}]")
                print(f"  {msg}")
                print()

    total = len(all_issues)
    summary = ", ".join(f"{len(v)} {k}" for k, v in cats.items())
    print(f"TOTAL: {total} issues ({summary})")

    return 1 if any(t in ("MISSING", "INCONSISTENT") for t, _, _ in all_issues) else 0


if __name__ == "__main__":
    sys.exit(main())
