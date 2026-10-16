#!/usr/bin/env python3
"""
Deterministic plan audit — structural consistency checks.

Verifies:
  1. Task completeness: every task has required fields
  2. Module coverage: every detailed-design module appears in a plan task
     (declared File/Targets paths first; a text-only match is a NOTE)
  3. Interface coverage: every detailed-design interface mentioned in plan
  4. Phase alignment: plan phases match the declared Implementation Order
     (a non-canonical order is one INCOMPLETE)
  5. File existence: declared paths resolve against the repo root,
     earlier-task aware (plan_files); a non-canonical File field is a NOTE
  6. Targets: a malformed **Targets** field is an ERROR; a missing one a NOTE
     (non-canonical, not runnable), never a failure (audit_targets.py)
  7. Oracle / Entry point / criteria pins (audit_oracle.py): ERRORs on a
     `plan-schema: 2` plan, NOTEs (on stderr) without the marker; spike exempt

Usage: python3 audit_plan.py <design-dir> [--spike|--light]
  --spike: Hypothesis/Try/Evaluate fields; skips detailed-design.md checks.
  --light: detailed-design.md not required (module/interface coverage and
           phase alignment skipped); standard File/Test/Red/Green completeness
           and budget annotations enforced; divergent weight-class is an ERROR.
Exit code: 1 = ERROR/MISSING/INCONSISTENT/INCOMPLETE, 0 = pass (WARN-only
           allowed), 2 = bad input. Every exit-0 run (clean or WARN-only) writes
           the pass artifact (a WARN-only run records its WARN count); a failing
           run writes nothing.
"""

import sys
import re
import subprocess
from pathlib import Path
from collections import defaultdict, namedtuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from weight_class import check_consistency as weight_class_consistency  # noqa: E402
from audit_artifact import write_pass_artifact  # noqa: E402
from audit_oracle import LEGACY_NOTE, check_fields, plan_schema  # noqa: E402
import plan_files  # noqa: E402 — declared **File** field grammar + existence
from design_phases import parse_implementation_order  # noqa: E402 — declared phase list
from task_scope_files import norm_path, parse_files  # noqa: E402
from task_targets import parse_targets  # noqa: E402
from plan_sections import (  # noqa: E402,F401 — moved out; re-exported for callers and tests
    extract_interface_names, extract_module_files, extract_section,
)


def read_file(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


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


STANDARD_FIELDS = ("File", "Test", "Targets", "Oracle", "Entry point", "Red", "Green",
                   "Refactor", "Done when", "Status")
# Targets: audit_targets.py; Oracle and Entry point: audit_oracle.py own their presence rule
_OPTIONAL_FIELDS = ("Refactor", "Status", "Targets", "Oracle", "Entry point")
SPIKE_FIELDS = ("Hypothesis", "Try", "Evaluate", "Status")

# Mode enum (audit finding M2): each mode derives load_detailed / check_coverage /
# field_set; `light` is production work (drops detailed-design like spike).
ModeConfig = namedtuple("ModeConfig", "load_detailed check_coverage field_set")
MODES = {
    "standard": ModeConfig(load_detailed=True, check_coverage=True, field_set=STANDARD_FIELDS),
    "spike": ModeConfig(load_detailed=False, check_coverage=False, field_set=SPIKE_FIELDS),
    "light": ModeConfig(load_detailed=False, check_coverage=False, field_set=STANDARD_FIELDS),
}

# Per-phase token-budget cap (thousands): the `phase-implement` slot soft budget
# of /tp-run-full-design; keep in lockstep with that table and tp-plan/SKILL.md.
PER_PHASE_BUDGET_CAP_K = 200

# A continuation block ends at the next field marker, task heading, or phase/section heading.
_FIELD_BOUNDARY_RE = re.compile(r"^(?:\*\*[A-Za-z ]+\*\*:|### Task |## )")


def extract_tasks(plan_text, spike_mode=False, fields=None):
    """Extract tasks from plan.md. ``fields`` (a MODES field_set) takes
    precedence; the ``spike_mode`` boolean is kept for pre-mode-enum callers."""
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
            current_task = {"id": tm.group(1), "name": tm.group(2).strip(),
                            "phase": current_phase, "fields": {}, "raw": ""}
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
                        # Continuation mode: gather lines until the next boundary
                        # marker, tracking ``` fences so a code block containing a
                        # boundary-lookalike line doesn't truncate the value early.
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
                        while collected and not collected[-1].strip():
                            collected.pop()
                        current_task["fields"][field] = "\n".join(collected)
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


def repo_root(design_dir):
    """Repo root via ``git rev-parse --show-toplevel`` from the design dir; cwd on failure."""
    try:
        r = subprocess.run(
            ["git", "-C", str(design_dir), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True)
        return Path(r.stdout.strip())
    except (subprocess.CalledProcessError, OSError):
        return Path.cwd()


# ── Checks ────────────────────────────────────────────────
def check_completeness(tasks, spike_mode=False, fields=None):
    """Every task must have required fields with non-empty values. ``fields``
    (a MODES field_set) takes precedence; Refactor/Status are optional."""
    field_set = fields or (SPIKE_FIELDS if spike_mode else STANDARD_FIELDS)
    required = tuple(f for f in field_set if f not in _OPTIONAL_FIELDS)
    issues = []
    for t in tasks:
        missing = [f for f in required if f not in t["fields"]]
        empty = [
            f
            for f in required
            if f in t["fields"] and not t["fields"][f].strip()
        ]
        if missing:
            # Surface the boundary regex actually tried and the offending line.
            boundary_regex = rf"^\*\*{re.escape(missing[0])}\*\*:\s*(.*)"
            excerpt_line = None
            for missing_field in missing:
                near = re.search(
                    rf"^[^\n]*\*\*\s*{re.escape(missing_field)}\s*\*\*[^\n]*",
                    t["raw"], re.MULTILINE)
                if near:
                    excerpt_line = near.group(0)
                    break
            excerpt = (excerpt_line or t["raw"][:80]).replace("\n", " \\n ")
            issues.append(("INCOMPLETE", f"Task {t['id']}: {t['name']}",
                           f"Missing fields: {', '.join(missing)}; "
                           f"tried r'{boundary_regex}' on '{excerpt}'"))
        if empty:
            issues.append(("INCOMPLETE", f"Task {t['id']}: {t['name']}",
                           f"Empty fields: {', '.join(empty)}"))
    return issues


def _declared_task_paths(t):
    """A task's declared repo paths: the File items (lenient-parse when the
    field is non-canonical) plus the Targets files, via ``norm_path``."""
    fields = t.get("fields") or {}
    field = fields.get("File")
    if field is None:
        paths = []
    else:
        parsed = plan_files.parse_file_field(field)
        paths = [i["path"] for i in parsed["items"]] if parsed["canonical"] else parse_files(field)[0]
    return [norm_path(p) for p in paths + parse_targets(fields.get("Targets"))["files"]]


def check_module_coverage(tasks, modules):
    """Every detailed-design module appears in a plan task → ``(issues, notes)``.
    A declared-path match (equal, or under a directory entry ending ``/``) is
    silent; a legacy text-tier match is a NOTE, never a failure; neither is
    MISSING, as before.
    """
    declared = set()
    text_paths = set()
    for t in tasks:
        declared.update(_declared_task_paths(t))
        text_paths.update(backtick_paths(t["fields"].get("File", "")))
        text_paths.update(backtick_paths(t["raw"]))
    issues, notes = [], []
    for mod in modules:
        m = norm_path(mod)
        if any(m == p or (m.endswith("/") and p.startswith(m)) for p in declared):
            continue
        if any(m in tf or tf in m for tf in text_paths):
            notes.append(("NOTE", None, f"module {mod} matched only by text"))
        else:
            issues.append(("MISSING", None, f"Module `{mod}` in detailed design has no plan task"))
    return issues, notes


def check_interface_coverage(tasks, interfaces):
    """Every interface in detailed-design must be mentioned in the plan."""
    plan_blob = " ".join(t["name"] + " " + t["raw"] for t in tasks)
    issues = []
    for iface in interfaces:
        func = re.match(r"(\w+)", iface)
        if func and func.group(1) not in plan_blob:
            issues.append(
                ("MISSING", None, f"Interface `{iface}` in detailed design not found in plan"))
    return issues


def check_phase_alignment(tasks, design_phases):
    """Plan phase count should match the detailed-design declared phase list."""
    plan_phases = sorted(set(t["phase"] for t in tasks if t["phase"]))
    if len(plan_phases) != len(design_phases):
        return [
            ("INCONSISTENT", None,
             f"Plan has {len(plan_phases)} phase(s), detailed design has {len(design_phases)}")]
    return []


# Phase-number matcher (colon NOT required) — shared by task extraction and the spike scan.
_PHASE_NUM_RE = re.compile(r"^##\s+Phase\s+(\d+)")
# Phase header with OPTIONAL colon + name, for the budget-annotation scan.
_PHASE_HEADER_RE = re.compile(r"^##\s+Phase\s+(\d+)\s*:?\s*(.*?)\s*$")
_BUDGET_ANNOTATION_RE = re.compile(r"\(~(\d+)k\)")


def check_budget_annotations(plan_text, cap_k=PER_PHASE_BUDGET_CAP_K):
    """Each plan.md phase header must carry a `(~Nk)` budget annotation and stay
    under the per-phase cap (advisory WARNs; the cap is a strict upper bound,
    so an exact `cap_k` passes).
    """
    issues = []
    for line in plan_text.split("\n"):
        m = _PHASE_HEADER_RE.match(line)
        if not m:
            continue
        phase_n, name = m.group(1), m.group(2).strip()
        budget = _BUDGET_ANNOTATION_RE.search(name)
        if not budget:
            issues.append(("WARN", f"Phase {phase_n}: {name}",
                           "phase header lacks a (~Nk) budget annotation "
                           f"(target the {cap_k}k per-phase cap)"))
            continue
        k = int(budget.group(1))
        if k > cap_k:
            issues.append(("WARN", f"Phase {phase_n}: {name}",
                           f"phase budget ~{k}k exceeds the {cap_k}k per-phase cap "
                           "(phase-implement slot soft budget) — split the phase"))
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
    mode = next((m for m in ("spike", "light") if f"--{m}" in flags), "standard")
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
    zero_parse = [] if tasks else [("INCOMPLETE", None, "no parseable tasks — "
        "plan.md has zero recognized '### Task N.M:' headings (check grammar)")]

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
        print(f"Design:   {len(in_scope)} in-scope, {len(entities)} entities, "
              f"{len(behaviors)} behaviors")
        if cfg.load_detailed:
            print(f"Detailed: {len(extract_module_files(detailed))} modules, "
                  f"{len(extract_interface_names(detailed))} interfaces, "
                  f"{len(parse_implementation_order(detailed)['phases'])} phases")
    print(f"Plan:     {len(tasks)} tasks across {plan_phase_count} phases")
    print()

    # Declared Implementation Order: one INCOMPLETE when neither declared shape
    # parsed (standard only — the other modes never load detailed-design).
    order_issues = []
    design_phases = []
    if cfg.load_detailed:
        order = parse_implementation_order(detailed)
        if not order["canonical"]:
            order_issues = [("INCOMPLETE", None,
                "detailed-design.md Implementation Order is not a declared phase "
                "list (numbered `N. **Title**` items, or `### Phase N:` headings)")]
        design_phases = order["phases"]

    # Single check-assembly path: completeness always; the rest from the mode config.
    notes = []
    all_issues = zero_parse + check_completeness(tasks, fields=cfg.field_set)
    if mode == "spike":
        all_issues += check_spike_deliverables(tasks, plan)
    if cfg.check_coverage:
        module_issues, module_notes = check_module_coverage(tasks, extract_module_files(detailed))
        all_issues += (module_issues + order_issues
                       + check_interface_coverage(tasks, extract_interface_names(detailed))
                       + check_phase_alignment(tasks, design_phases))
        notes += module_notes
    if mode != "spike":
        file_issues, file_notes = plan_files.check_file_existence(tasks, root=repo_root(d))
        all_issues += file_issues + check_budget_annotations(plan)
        field_issues, field_notes = check_fields(tasks, mode, repo_root(d), plan_schema(plan))
        all_issues += field_issues
        notes += file_notes + field_notes
    for typ, ctx, msg in notes:  # reported, never failing: non-canonical tasks
        print(f"  NOTE [{ctx}] {msg}" if ctx else f"  NOTE {msg}",
              file=sys.stderr if typ == LEGACY_NOTE else sys.stdout)
    # All modes: divergent/missing weight-class stamps are hard failures. Legacy
    # frontmatter-free dirs pass vacuously (the helper gates on design.md F3/F5).
    all_issues += [("ERROR", None, f"weight-class consistency: {finding}")
                   for finding in weight_class_consistency(d)]

    if not all_issues:
        print("RESULT: ALL CHECKS PASSED")
        print()
        print("Verified: task fields, module coverage, interface coverage,")
        print("phase alignment, file existence.")
        # Clean-branch ONLY: emit the pass artifact (staleness contract for the
        # tp-phase-implement preflight) carrying a zero WARN count.
        write_pass_artifact(d, mode, warnings=[])
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

    exit_1 = ("ERROR", "MISSING", "INCONSISTENT", "INCOMPLETE")
    if any(t in exit_1 for t, _, _ in all_issues):
        # Failing run: write NO artifact (the tp-phase-implement gate must refuse).
        return 1

    # WARN-only: a PASS. Record a CURRENT artifact carrying the WARN count so
    # `--check` reports "N WARN(s)", then surface the count on the RESULT line.
    warnings = [f"[{ctx}] {msg}" if ctx else msg
                for typ, ctx, msg in all_issues if typ == "WARN"]
    write_pass_artifact(d, mode, warnings=warnings)
    print(f"RESULT: PASS ({len(warnings)} WARN)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
