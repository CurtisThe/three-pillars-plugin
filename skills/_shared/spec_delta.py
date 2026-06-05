#!/usr/bin/env python3
"""spec_delta.py — parse / validate / merge-or-refuse engine for delta-specs.

Mirrors OpenSpec's delta-spec format: a base spec keys requirements by exact name
(`### Requirement: <name>`, scenarios `#### Scenario:`); a change delta carries
`## ADDED/MODIFIED/REMOVED/RENAMED Requirements` sections merged into the base.

Refusal-first (the three-pillars answer to OpenSpec's known parallel-merge data-loss
bug): the engine FAILS LOUD — `parse_delta` raises on unparseable input rather than a
silent empty no-op, and `merge` raises `MergeConflict` on any ambiguity (missing target,
name collision, one requirement touched twice in a delta, or — the parallel-edit bug —
two concurrent deltas touching the same requirement) rather than silently overwriting.

CLI:
    python3 skills/_shared/spec_delta.py validate <delta.md> [--base <base.md>]
    python3 skills/_shared/spec_delta.py merge <base.md> <delta.md> [<delta2.md> ...]

Exit codes: 0 ok; 1 BLOCKED (JSON verdict on stderr, mirroring validate_design_floor.py);
2 usage error. Pure stdlib: re, sys, json, pathlib, dataclasses.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
RECOGNIZED = ("ADDED", "MODIFIED", "REMOVED", "RENAMED")

REQ_RE = re.compile(r"^###\s+Requirement:\s*(?P<name>.*?)\s*$")
SECTION_RE = re.compile(r"^##\s+(?P<kind>[A-Za-z]+)\s+Requirements\s*$")
SCENARIO_RE = re.compile(r"^####\s+Scenario:")
L12_HEADER_RE = re.compile(r"^#{1,2}\s")  # level-1/2 header ends the requirements region
RENAME_LINE_RE = re.compile(
    r"^\s*-\s*(?P<dir>FROM|TO):\s*`?###\s+Requirement:\s*(?P<name>.*?)`?\s*$"
)


@dataclass
class Requirement:
    name: str
    block: str          # full markdown block incl. its `### Requirement:` header
    scenarios: int


@dataclass
class Spec:
    preamble: str
    requirements: dict[str, Requirement]  # name -> Requirement, insertion-ordered
    trailing: str = ""  # any level-1/2 section after the requirements (preserved; surrounding whitespace normalized on re-serialize)


@dataclass
class DeltaOp:
    kind: str
    name: str
    block: str | None = None
    scenarios: int = 0
    from_name: str | None = None


@dataclass
class Delta:
    ops: list[DeltaOp]


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    location: str


class SpecParseError(Exception):
    """Unparseable delta/spec — fail loud, never a silent no-op."""


class MergeConflict(Exception):
    """Ambiguous merge — refuse rather than silently overwrite."""

    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__(
            "; ".join(f"{i.code}@{i.location}" for i in self.issues) or "merge conflict"
        )


def _norm(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def parse_spec(text: str) -> Spec:
    lines = _norm(text)
    req_idx = [i for i, ln in enumerate(lines) if REQ_RE.match(ln)]
    if not req_idx:
        # Normalize via `lines` (not raw `text`) so CRLF/mixed newlines are
        # deterministic here too, matching the with-requirements path below.
        return Spec(preamble="\n".join(lines).rstrip("\n"), requirements={}, trailing="")
    first = req_idx[0]
    trailing_start = len(lines)
    for j in range(first + 1, len(lines)):
        if L12_HEADER_RE.match(lines[j]):  # first `#`/`##` after requirements begins trailing
            trailing_start = j
            break
    preamble = "\n".join(lines[:first]).rstrip("\n")
    region = lines[first:trailing_start]
    trailing = "\n".join(lines[trailing_start:]).strip("\n")
    if any(REQ_RE.match(ln) for ln in trailing.split("\n")):
        # a `#`/`##` header split the requirements; refuse rather than silently drop the rest
        raise SpecParseError("requirement(s) found after a section break — ambiguous spec, refusing")
    reqs: dict = {}
    starts = [k for k, ln in enumerate(region) if REQ_RE.match(ln)]
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(region)
        block_lines = region[s:e]
        name = REQ_RE.match(block_lines[0]).group("name")
        block = "\n".join(block_lines).rstrip("\n")
        scen = sum(1 for ln in block_lines if SCENARIO_RE.match(ln))
        if name in reqs:
            raise SpecParseError(f"duplicate requirement in base spec: {name!r}")
        reqs[name] = Requirement(name=name, block=block, scenarios=scen)
    return Spec(preamble=preamble, requirements=reqs, trailing=trailing)


def _parse_section_ops(kind: str, body: list) -> list:
    ops = []
    starts = [k for k, ln in enumerate(body) if REQ_RE.match(ln)]
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(body)
        bl = body[s:e]
        name = REQ_RE.match(bl[0]).group("name")
        block = "\n".join(bl).rstrip("\n")
        scen = sum(1 for ln in bl if SCENARIO_RE.match(ln))
        if kind == "REMOVED":
            ops.append(DeltaOp(kind=kind, name=name))
        else:
            ops.append(DeltaOp(kind=kind, name=name, block=block, scenarios=scen))
    return ops


def _parse_renamed(body: list) -> list:
    ops, frm = [], None
    for ln in body:
        m = RENAME_LINE_RE.match(ln)
        if not m:
            if ln.strip():  # non-blank, non-FROM/TO line — fail loud, never skip silently
                raise SpecParseError(f"unparseable line in RENAMED section: {ln.strip()!r}")
            continue
        if m.group("dir") == "FROM":
            if frm is not None:
                raise SpecParseError(f"RENAMED FROM {frm!r} has no matching TO")
            frm = m.group("name")
        else:
            if frm is None:
                raise SpecParseError("RENAMED TO has no preceding FROM")
            ops.append(DeltaOp(kind="RENAMED", name=m.group("name"), from_name=frm))
            frm = None
    if frm is not None:
        raise SpecParseError(f"RENAMED FROM {frm!r} has no matching TO")
    return ops


def parse_delta(text: str) -> Delta:
    lines = _norm(text)
    sections = []
    for i, ln in enumerate(lines):
        m = SECTION_RE.match(ln)
        if m:
            kind = m.group("kind").upper()
            if kind not in RECOGNIZED:
                raise SpecParseError(f"unrecognized delta section: {ln.strip()!r}")
            sections.append((kind, i))
    if not sections:
        if text.strip():
            raise SpecParseError("delta has no recognized `## ... Requirements` section")
        return Delta(ops=[])
    for i in range(sections[0][1]):  # a `### Requirement:` before any section is orphaned
        if REQ_RE.match(lines[i]):
            raise SpecParseError("`### Requirement:` appears outside any delta section")
    ops = []
    for n, (kind, start) in enumerate(sections):
        end = sections[n + 1][1] if n + 1 < len(sections) else len(lines)
        body = lines[start + 1:end]
        sec_ops = _parse_renamed(body) if kind == "RENAMED" else _parse_section_ops(kind, body)
        if not sec_ops and any(ln.strip() for ln in body):  # non-blank body, zero ops → fail loud
            raise SpecParseError(f"{kind} section has content but no parseable requirement")
        ops.extend(sec_ops)
    if not ops and text.strip():
        raise SpecParseError("delta sections present but no operations parsed")
    return Delta(ops=ops)


def _op_targets(op: DeltaOp) -> list:
    if op.kind == "RENAMED":
        return [n for n in (op.from_name, op.name) if n is not None]
    return [op.name]


def validate(delta: Delta, base: Spec | None = None) -> list:
    """Validate ONE delta (structural + optionally against `base`). Never raises.

    Cross-delta detection (`concurrent-edit-conflict`) is intentionally NOT here — a
    single delta cannot see a peer. That check lives in `merge`'s cross-delta pass.
    """
    issues = []
    for op in delta.ops:
        loc = f"{op.kind}/{op.name}"
        if not op.name.strip():
            issues.append(Issue("ERROR", "empty-requirement-name", "requirement name is blank", loc))
        if op.kind in ("ADDED", "MODIFIED") and op.scenarios == 0:
            issues.append(Issue("ERROR", "missing-scenario", f"{op.kind} requirement has no scenario", loc))
        if op.kind == "RENAMED":
            if not (op.from_name or "").strip():
                issues.append(Issue("ERROR", "rename-missing-source", "RENAMED has no FROM name", loc))
            elif op.from_name == op.name:
                issues.append(Issue("ERROR", "rename-to-self", f"RENAMED from and to identical: {op.name!r}", loc))
    counts: dict = {}
    for op in delta.ops:
        for nm in _op_targets(op):
            counts[nm] = counts.get(nm, 0) + 1
    for nm, c in counts.items():
        if c > 1:
            issues.append(Issue("ERROR", "duplicate-op-target", f"requirement targeted by >1 op in one delta: {nm!r}", "delta"))
    if base is not None:
        names = set(base.requirements)
        removed = {op.name for op in delta.ops if op.kind == "REMOVED"}
        renamed_away = {op.from_name for op in delta.ops if op.kind == "RENAMED"}
        for op in delta.ops:
            loc = f"{op.kind}/{op.name}"
            if op.kind == "ADDED" and op.name in names:
                issues.append(Issue("ERROR", "add-existing", f"ADDED name already in base: {op.name!r}", loc))
            elif op.kind == "MODIFIED" and op.name not in names:
                issues.append(Issue("ERROR", "modify-missing-target", f"MODIFIED target absent from base: {op.name!r}", loc))
            elif op.kind == "REMOVED" and op.name not in names:
                issues.append(Issue("ERROR", "remove-missing-target", f"REMOVED target absent from base: {op.name!r}", loc))
            elif op.kind == "RENAMED":
                if op.from_name and op.from_name not in names:
                    issues.append(Issue("ERROR", "rename-missing-source", f"RENAMED source absent from base: {op.from_name!r}", loc))
                if op.name in names and op.name not in removed and op.name not in renamed_away:
                    issues.append(Issue("ERROR", "rename-target-exists", f"RENAMED target already in base: {op.name!r}", loc))
    return issues


def _cross_delta_conflicts(deltas: list) -> list:
    touch: dict = {}
    for idx, d in enumerate(deltas):
        names = set()
        for op in d.ops:
            names.update(_op_targets(op))
        for nm in names:
            touch.setdefault(nm, set()).add(idx)
    return [
        Issue("ERROR", "concurrent-edit-conflict",
              f"requirement {nm!r} edited by {len(idxs)} concurrent deltas", f"deltas:{sorted(idxs)}")
        for nm, idxs in touch.items() if len(idxs) > 1
    ]


def _rewrite_header(block: str, new_name: str) -> str:
    lines = block.split("\n")
    lines[0] = f"### Requirement: {new_name}"
    return "\n".join(lines)


def _serialize(spec: Spec) -> str:
    parts = []
    if spec.preamble.strip():
        parts.append(spec.preamble.rstrip("\n"))
    parts.extend(req.block.rstrip("\n") for req in spec.requirements.values())
    if spec.trailing.strip():
        parts.append(spec.trailing.rstrip("\n"))
    return "\n\n".join(parts) + "\n"


def merge(base_text: str, delta_texts: list[str]) -> str:
    """Apply 1+ concurrent deltas to a base spec, or REFUSE (raise) on any ambiguity."""
    if not delta_texts:
        # Fail loud: an empty delta set is not a successful no-op merge.
        raise SpecParseError("merge requires at least one delta — refusing empty delta set")
    base = parse_spec(base_text)
    deltas = [parse_delta(t) for t in delta_texts]
    issues = []
    for d in deltas:
        issues.extend(validate(d, base))
    issues.extend(_cross_delta_conflicts(deltas))
    errs = [i for i in issues if i.severity == "ERROR"]
    if errs:
        raise MergeConflict(errs)

    reqs = dict(base.requirements)
    all_ops = [op for d in deltas for op in d.ops]

    def _raise(code, msg, loc):
        raise MergeConflict([Issue("ERROR", code, msg, loc)])

    for op in (o for o in all_ops if o.kind == "RENAMED"):  # RENAMED first
        if op.from_name not in reqs:
            _raise("rename-missing-source", f"{op.from_name!r} absent", f"RENAMED/{op.name}")
        if op.name in reqs:
            _raise("rename-target-exists", f"{op.name!r} exists", f"RENAMED/{op.name}")
        reqs = {
            (op.name if k == op.from_name else k):
            (Requirement(op.name, _rewrite_header(v.block, op.name), v.scenarios)
             if k == op.from_name else v)
            for k, v in reqs.items()
        }
    for op in (o for o in all_ops if o.kind == "REMOVED"):  # then REMOVED
        if op.name not in reqs:
            _raise("remove-missing-target", f"{op.name!r} absent", f"REMOVED/{op.name}")
        del reqs[op.name]
    for op in (o for o in all_ops if o.kind == "MODIFIED"):  # then MODIFIED (in place)
        if op.name not in reqs:
            _raise("modify-missing-target", f"{op.name!r} absent", f"MODIFIED/{op.name}")
        reqs[op.name] = Requirement(op.name, op.block, op.scenarios)
    for op in (o for o in all_ops if o.kind == "ADDED"):  # ADDED last (appended)
        if op.name in reqs:
            _raise("add-existing", f"{op.name!r} exists", f"ADDED/{op.name}")
        reqs[op.name] = Requirement(op.name, op.block, op.scenarios)

    return _serialize(Spec(preamble=base.preamble, requirements=reqs, trailing=base.trailing))


def _issue_dict(i: Issue) -> dict:
    return {"severity": i.severity, "code": i.code, "message": i.message, "location": i.location}


def _blocked(errs) -> None:
    print(json.dumps({"verdict": "BLOCKED", "schema_version": SCHEMA_VERSION,
                      "errors": [_issue_dict(e) for e in errs]}), file=sys.stderr)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("validate", "merge"):
        print("usage: spec_delta.py {validate <delta> [--base <base>] | "
              "merge <base> <delta> [<delta2> ...]}", file=sys.stderr)
        return 2
    cmd, rest = argv[1], argv[2:]
    try:
        if cmd == "validate":
            base, delta_path, i = None, None, 0
            while i < len(rest):
                if rest[i] == "--base":
                    if i + 1 >= len(rest):
                        print("usage: validate <delta> [--base <base>]", file=sys.stderr)
                        return 2
                    base = parse_spec(Path(rest[i + 1]).read_text())
                    i += 2
                elif rest[i].startswith("--"):
                    print(f"unknown flag: {rest[i]}\n"
                          "usage: validate <delta> [--base <base>]", file=sys.stderr)
                    return 2
                elif delta_path is not None:
                    print(f"unexpected extra argument: {rest[i]} "
                          "(validate takes exactly one <delta>)\n"
                          "usage: validate <delta> [--base <base>]", file=sys.stderr)
                    return 2
                else:
                    delta_path, i = rest[i], i + 1
            if delta_path is None:
                print("usage: validate <delta> [--base <base>]", file=sys.stderr)
                return 2
            errs = [x for x in validate(parse_delta(Path(delta_path).read_text()), base)
                    if x.severity == "ERROR"]
            if errs:
                _blocked(errs)
                return 1
            return 0
        if len(rest) < 2:
            print("usage: merge <base> <delta> [<delta2> ...]", file=sys.stderr)
            return 2
        base_text = Path(rest[0]).read_text()
        delta_texts = [Path(p).read_text() for p in rest[1:]]
        sys.stdout.write(merge(base_text, delta_texts))
        return 0
    except FileNotFoundError as e:
        print(f"file not found: {e}", file=sys.stderr)
        return 2
    except SpecParseError as e:
        _blocked([Issue("ERROR", "parse-error", str(e), "parse")])
        return 1
    except MergeConflict as e:
        _blocked(e.issues)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
