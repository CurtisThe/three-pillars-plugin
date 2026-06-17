#!/usr/bin/env python3
"""
Deterministic plan audit — structural consistency checks.

Verifies:
  1. Task completeness: every task has required fields
  2. Module coverage: every detailed-design module referenced in plan
  3. Interface coverage: every detailed-design interface mentioned in plan
  4. Phase alignment: plan phases match detailed-design phases
  5. File existence: modified files exist, new file parents exist

Usage: python3 audit_plan.py <design-dir> [--spike|--light]
  --spike: Spike mode — expects Hypothesis/Try/Evaluate fields instead of
           File/Test/Red/Green. Skips detailed-design.md checks entirely.
  --light: Light mode — detailed-design.md not required (module/interface
           coverage and phase alignment skipped), but the standard
           File/Test/Red/Green field completeness and budget annotations
           are still enforced. Divergent weight-class frontmatter between
           design.md and its siblings is reported as ERROR.
Exit code: 0 = pass, 1 = issues found, 2 = bad input
"""

import sys
import re
from pathlib import Path
from collections import defaultdict, namedtuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from weight_class import check_consistency as weight_class_consistency  # noqa: E402


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

# Mode enum (audit finding M2): each audit mode derives the three decisions
# the old `spike_mode` boolean coupled — whether detailed-design.md is
# loaded/required, whether the structural-coverage checks (module/interface
# coverage + phase alignment) run, and which task field set the plan uses.
# `light` is production work, not experiments: it drops the detailed-design
# requirement like spike but keeps the standard File/Test/Red/Green fields.
ModeConfig = namedtuple("ModeConfig", "load_detailed check_coverage field_set")
MODES = {
    "standard": ModeConfig(load_detailed=True, check_coverage=True, field_set=STANDARD_FIELDS),
    "spike": ModeConfig(load_detailed=False, check_coverage=False, field_set=SPIKE_FIELDS),
    "light": ModeConfig(load_detailed=False, check_coverage=False, field_set=STANDARD_FIELDS),
}

# Per-phase token-budget cap (in thousands). Each plan.md phase is dispatched
# under one `phase-implement` slot by /tp-run-full-design, whose soft budget is
# 200k in that orchestrator's static budget table (skills/tp-run-full-design/
# SKILL.md → ## Per-slot budget table). This constant is the source of truth for
# CODE; the same 200k figure is ALSO stated in prose in that budget table and in
# tp-plan/SKILL.md (neither can import this constant), so those copies must be
# updated in lockstep if the slot budget changes (plan §Task 7.2).
PER_PHASE_BUDGET_CAP_K = 200

# A continuation block ends at the next field marker, the next task heading,
# or the next phase/section heading. Hoisted per detailed-design §audit_plan
# so future field extractors can share the same boundary.
_FIELD_BOUNDARY_RE = re.compile(r"^(?:\*\*[A-Za-z ]+\*\*:|### Task |## )")


def extract_tasks(plan_text, spike_mode=False, fields=None):
    """Extract tasks from plan.md.

    ``fields`` (a MODES field_set) takes precedence; the ``spike_mode``
    boolean is kept for callers/tests that predate the mode enum.
    """
    tasks = []
    current_task = None
    current_phase = None
    fields_to_check = fields or (SPIKE_FIELDS if spike_mode else STANDARD_FIELDS)

    lines = plan_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        pm = _PHASE_NUM_RE.match(line)
        if pm:
            current_phase = int(pm.group(1))
            i += 1
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
            i += 1
            continue

        if current_task:
            current_task["raw"] += line + "\n"
            matched_field = None
            for field in fields_to_check:
                fm = re.match(rf"^\*\*{re.escape(field)}\*\*:\s*(.*)", line)
                if fm:
                    inline = fm.group(1).strip()
                    if inline:
                        current_task["fields"][field] = inline
                    else:
                        # Continuation mode: gather subsequent lines until the
                        # next boundary marker. Track ``` fences so a code
                        # block containing `## `, `### Task `, or `**X**:`
                        # doesn't truncate the field value early.
                        collected = []
                        j = i + 1
                        in_fence = False
                        while j < len(lines):
                            stripped = lines[j].lstrip()
                            if stripped.startswith("```"):
                                in_fence = not in_fence
                                collected.append(stripped)
                                j += 1
                                continue
                            if not in_fence and _FIELD_BOUNDARY_RE.match(lines[j]):
                                break
                            collected.append(stripped)
                            j += 1
                        # Trim trailing blank lines so empty buffers stay empty.
                        while collected and not collected[-1].strip():
                            collected.pop()
                        current_task["fields"][field] = "\n".join(collected)
                        # Capture the continuation body in raw too, then resume
                        # the outer loop at the boundary line.
                        for k in range(i + 1, j):
                            current_task["raw"] += lines[k] + "\n"
                        matched_field = (field, j)
                    break
            if matched_field is not None:
                i = matched_field[1]
                continue
        i += 1

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
    """Find phase names from the Implementation Order section.

    Accepts both `### Phase N:` (existing convention) and `## Phase N:`
    (some legacy / hand-edited detailed designs). The h2 shape places
    phase headings as siblings of Implementation Order, which
    `extract_section` would otherwise truncate; so we scan from the
    Implementation Order heading forward until the next non-Phase `## `
    heading.
    """
    lines = detailed.split("\n")
    phases = []
    in_section = False
    for line in lines:
        if not in_section:
            if re.match(r"^##\s+Implementation Order", line, re.IGNORECASE):
                in_section = True
            continue
        # Boundary: another `## ` heading that is NOT `## Phase` ends the section.
        if re.match(r"^##\s+", line) and not re.match(r"^#{2,3}\s+Phase\s+\d+:", line):
            break
        m = re.match(r"^#{2,3}\s+Phase\s+\d+:\s*(.+)", line)
        if m:
            phases.append(m.group(1).strip())
    return phases


# ── Checks ────────────────────────────────────────────────


def check_completeness(tasks, spike_mode=False, fields=None):
    """Every task must have required fields with non-empty values.

    ``fields`` (a MODES field_set) takes precedence; Refactor/Status are
    optional and excluded from the required subset. The ``spike_mode``
    boolean is kept for callers/tests that predate the mode enum.
    """
    field_set = fields or (SPIKE_FIELDS if spike_mode else STANDARD_FIELDS)
    required = tuple(f for f in field_set if f not in ("Refactor", "Status"))
    issues = []
    for t in tasks:
        missing = [f for f in required if f not in t["fields"]]
        empty = [
            f
            for f in required
            if f in t["fields"] and not t["fields"][f].strip()
        ]
        if missing:
            # The same boundary regex the parser actually tries — surfaced
            # in the error so an operator can grep for the typo's shape.
            # Emit a single-field regex pinned to the first missing name so
            # the literal `\*\*<Field>\*\*` survives intact (an operator
            # grepping for the regex shouldn't see a wrapping group).
            boundary_regex = rf"^\*\*{re.escape(missing[0])}\*\*:\s*(.*)"
            # Prefer the offending line (a typo'd field marker) over the
            # head of the raw body — that's what an operator wants to see.
            excerpt_line = None
            for missing_field in missing:
                near = re.search(
                    rf"^[^\n]*\*\*\s*{re.escape(missing_field)}\s*\*\*[^\n]*",
                    t["raw"],
                    re.MULTILINE,
                )
                if near:
                    excerpt_line = near.group(0)
                    break
            excerpt = (excerpt_line or t["raw"][:80]).replace("\n", " \\n ")
            issues.append(
                (
                    "INCOMPLETE",
                    f"Task {t['id']}: {t['name']}",
                    f"Missing fields: {', '.join(missing)}; tried r'{boundary_regex}' on '{excerpt}'",
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


# Phase-number matcher (colon NOT required) — shared by task extraction and the
# spike deliverable scan so they agree on what counts as a phase header.
_PHASE_NUM_RE = re.compile(r"^##\s+Phase\s+(\d+)")
# Phase header with an OPTIONAL colon + optional name, for the budget-annotation
# scan. The colon is optional so a colonless `## Phase 3` / `## Phase 3 Name`
# header — which _PHASE_NUM_RE (and extract_tasks) still treat as a phase — is
# checked for a budget annotation rather than silently skipped.
_PHASE_HEADER_RE = re.compile(r"^##\s+Phase\s+(\d+)\s*:?\s*(.*?)\s*$")
_BUDGET_ANNOTATION_RE = re.compile(r"\(~(\d+)k\)")


def check_budget_annotations(plan_text, cap_k=PER_PHASE_BUDGET_CAP_K):
    """Each plan.md phase header must carry a `(~Nk)` budget annotation and stay
    under the per-phase cap (the `phase-implement` slot soft budget; Task 7.1).

    This is an independent predicate: it reads only plan.md phase headers — never
    the detailed-design structural counts — so it is orthogonal to the known
    house-style false positives (vacuous 0-modules/0-interfaces/0-phases and
    spurious phase-count drift) and cannot trigger or worsen them (plan §Task 7.2
    note). Both failure modes are advisory WARNs (budget is a sizing hint, not a
    hard gate; the cap is a strict upper bound, so an exact `cap_k` passes).
    """
    issues = []
    for line in plan_text.split("\n"):
        m = _PHASE_HEADER_RE.match(line)
        if not m:
            continue
        phase_n, name = m.group(1), m.group(2).strip()
        budget = _BUDGET_ANNOTATION_RE.search(name)
        if not budget:
            issues.append(
                (
                    "WARN",
                    f"Phase {phase_n}: {name}",
                    "phase header lacks a (~Nk) budget annotation "
                    f"(target the {cap_k}k per-phase cap)",
                )
            )
            continue
        k = int(budget.group(1))
        if k > cap_k:
            issues.append(
                (
                    "WARN",
                    f"Phase {phase_n}: {name}",
                    f"phase budget ~{k}k exceeds the {cap_k}k per-phase cap "
                    "(phase-implement slot soft budget) — split the phase",
                )
            )
    return issues


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


_MODE_LABELS = {"standard": "", "spike": " (SPIKE MODE)", "light": " (LIGHT MODE)"}


def check_spike_deliverables(tasks, plan):
    """Each spike phase must carry a **Deliverable** line."""
    issues = []
    phase_deliverables = set()
    current = 0  # deliverables seen before any phase header bucket under 0
    for line in plan.split("\n"):
        pm = _PHASE_NUM_RE.match(line)
        if pm:
            current = int(pm.group(1))
        if re.match(r"^\*\*Deliverable\*\*:", line):
            phase_deliverables.add(current)
    phases_in_plan = set(t["phase"] for t in tasks if t["phase"])
    for p in phases_in_plan:
        if p not in phase_deliverables:
            issues.append(("INCOMPLETE", f"Phase {p}", "Missing **Deliverable** line"))
    return issues


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if "--spike" in flags:
        mode = "spike"
    elif "--light" in flags:
        mode = "light"
    else:
        mode = "standard"
    cfg = MODES[mode]

    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} <design-dir> [--spike|--light]", file=sys.stderr)
        sys.exit(2)

    d = Path(args[0])
    design = read_file(d / "design.md")
    plan = read_file(d / "plan.md")

    required_files = [("design.md", design), ("plan.md", plan)]
    detailed = None
    if cfg.load_detailed:
        detailed = read_file(d / "detailed-design.md")
        required_files.append(("detailed-design.md", detailed))

    for name, content in required_files:
        if not content:
            print(f"ERROR: {name} not found in {d}")
            sys.exit(2)

    # Extract structural elements
    tasks = extract_tasks(plan, fields=cfg.field_set)

    print("=" * 60)
    print(f"PLAN AUDIT — DETERMINISTIC CHECKS{_MODE_LABELS[mode]}")
    print("=" * 60)
    print()

    # Mode-specific summary header
    plan_phase_count = len(set(t["phase"] for t in tasks if t["phase"]))
    if mode == "spike":
        hypothesis = extract_section(design, r"Hypothesis")
        experiments = extract_section(design, r"Experiments")
        success = extract_section(design, r"Success Criteria")
        print(f"Design:   hypothesis={'yes' if hypothesis.strip() else 'MISSING'}, "
              f"experiments={'yes' if experiments.strip() else 'MISSING'}, "
              f"success criteria={'yes' if success.strip() else 'MISSING'}")
    else:
        in_scope = extract_bullets(extract_section(design, r"In scope", 3))
        entities = extract_bold_names(extract_section(design, r"Entities"))
        behaviors = extract_bold_names(extract_section(design, r"Behaviors"))
        print(
            f"Design:   {len(in_scope)} in-scope, "
            f"{len(entities)} entities, {len(behaviors)} behaviors"
        )
        if cfg.load_detailed:
            print(
                f"Detailed: {len(extract_module_files(detailed))} modules, "
                f"{len(extract_interface_names(detailed))} interfaces, "
                f"{len(extract_design_phases(detailed))} phases"
            )
    print(f"Plan:     {len(tasks)} tasks across {plan_phase_count} phases")
    print()

    # Single check-assembly path: completeness always; the rest derived
    # from the mode config.
    all_issues = check_completeness(tasks, fields=cfg.field_set)
    if mode == "spike":
        all_issues += check_spike_deliverables(tasks, plan)
    if cfg.check_coverage:
        all_issues += (
            check_module_coverage(tasks, extract_module_files(detailed))
            + check_interface_coverage(tasks, extract_interface_names(detailed))
            + check_phase_alignment(tasks, extract_design_phases(detailed))
        )
    if mode != "spike":
        all_issues += check_file_existence(tasks) + check_budget_annotations(plan)
    # All modes: divergent/missing weight-class stamps are hard failures
    # (the declared class drives which ceremony this very audit runs).
    # Legacy frontmatter-free dirs pass vacuously — the helper gates on
    # design.md's class coming from frontmatter (plan-audit F3/F5).
    all_issues += [
        ("ERROR", None, f"weight-class consistency: {finding}")
        for finding in weight_class_consistency(d)
    ]

    if not all_issues:
        print("RESULT: ALL CHECKS PASSED")
        print()
        print("Verified: task fields, module coverage, interface coverage,")
        print("phase alignment, file existence.")
        return 0

    cats = defaultdict(list)
    for typ, ctx, msg in all_issues:
        cats[typ].append((ctx, msg))

    for cat in ("ERROR", "MISSING", "INCONSISTENT", "INCOMPLETE", "WARN"):
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

    return 1 if any(t in ("ERROR", "MISSING", "INCONSISTENT") for t, _, _ in all_issues) else 0


if __name__ == "__main__":
    sys.exit(main())
