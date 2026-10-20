#!/usr/bin/env python3
"""Design weight-class axis — frontmatter parse/write, rubric, consistency check.

The weight class declares how much ceremony a design carries
(``just-do-it | light | spike | full``). It lives in a YAML-ish frontmatter
block at the top of design artifacts; ``design.md`` is authoritative.
Protocol doc: skills/_shared/weight-class.md.

Stdlib only — frontmatter is a flat ``key: value`` block parsed by regex,
same discipline as the other _shared helpers (no YAML lib).
"""
import argparse
import re
import sys
from pathlib import Path

VALID_CLASSES = ("just-do-it", "light", "spike", "full")

_KV_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$")


def parse_frontmatter(text: str) -> dict:
    """Parse a leading ``---`` frontmatter block into a flat key/value dict.

    Returns ``{}`` when the block is absent, unclosed, or not at the very
    start of the text. Non-``key: value`` lines inside the block are skipped.
    Never raises on arbitrary input.
    """
    if not isinstance(text, str):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    result = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return result
        m = _KV_RE.match(line)
        if m and m.group(2):
            result[m.group(1)] = m.group(2)
    return {}  # opening fence never closed -> malformed


def read_class(design_dir: Path) -> tuple:
    """Return ``(class, source)`` for a design directory.

    ``design.md`` frontmatter is authoritative: a valid ``weight-class`` value
    yields ``(value, "frontmatter")``. Anything else — missing design.md,
    missing/malformed frontmatter, unknown class value — fails safe to
    ``("full", "default")`` (more checking, never less).
    """
    design_md = Path(design_dir) / "design.md"
    try:
        text = design_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ("full", "default")
    klass = parse_frontmatter(text).get("weight-class")
    if klass in VALID_CLASSES:
        return (klass, "frontmatter")
    return ("full", "default")


def read_review_weight(design_dir: Path) -> tuple:
    """Return ``(weight, source)`` — how much review a design carries.

    A frontmatter ``review-weight`` naming a valid class wins
    (``(value, "review-weight")``). Anything else — key absent, unknown value,
    no design.md — falls back to ``read_class``, which fails safe to
    ``("full", "default")`` (more review, never less).
    """
    design_md = Path(design_dir) / "design.md"
    try:
        text = design_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return read_class(design_dir)
    weight = parse_frontmatter(text).get("review-weight")
    if weight in VALID_CLASSES:
        return (weight, "review-weight")
    return read_class(design_dir)


_AXIS_LEVELS = ("low", "medium", "high")


def recommend_class(risk, blast_radius, reversibility, novelty) -> tuple:
    """Map the four rubric axes to ``(class, justification)``.

    Each axis takes ``low | medium | high``. Reversibility is inverted —
    ``high`` reversibility is good (minimal concern). Mapping: all four
    minimal -> just-do-it; novelty high -> spike; at most one axis medium,
    none high -> light; otherwise -> full. Ties and unknown axis values
    resolve heavier (full). The justification names the deciding axis.
    """
    axes = {
        "risk": risk,
        "blast_radius": blast_radius,
        "reversibility": reversibility,
        "novelty": novelty,
    }
    for name, value in axes.items():
        if value not in _AXIS_LEVELS:
            return ("full", f"{name} value {value!r} is unknown — resolving heavier")
    # Normalize to concern levels: reversibility high (easy to undo) = low concern.
    concern = dict(axes)
    concern["reversibility"] = {"high": "low", "medium": "medium", "low": "high"}[
        reversibility
    ]
    if all(level == "low" for level in concern.values()):
        return ("just-do-it", "all axes minimal")
    if novelty == "high":
        return ("spike", "novelty is high — the approach is unknown")
    highs = [name for name, level in concern.items() if level == "high"]
    mediums = [name for name, level in concern.items() if level == "medium"]
    if not highs and len(mediums) == 1:
        return ("light", f"only {mediums[0]} is medium; no axis is high")
    if highs:
        return ("full", f"{highs[0]} concern is high")
    return ("full", f"multiple medium axes: {', '.join(mediums)}")


_SIBLING_ARTIFACTS = ("seed.md", "detailed-design.md", "plan.md")


def check_consistency(design_dir: Path) -> list:
    """Findings for sibling artifacts whose weight-class diverges from design.md.

    GUARD (plan-audit F3): gates on ``read_class`` source == "frontmatter" —
    when the class comes from the default (design.md absent, frontmatter-free,
    or invalid value), the check passes vacuously so legacy dirs stay clean.
    Missing sibling files are skipped, never findings; a present sibling
    without frontmatter IS a finding (the stamp should have propagated).
    """
    design_dir = Path(design_dir)
    klass, source = read_class(design_dir)
    if source != "frontmatter":
        return []
    findings = []
    for name in _SIBLING_ARTIFACTS:
        sibling = design_dir / name
        try:
            text = sibling.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        sibling_class = parse_frontmatter(text).get("weight-class")
        if sibling_class is None:
            findings.append(
                f"{name}: missing weight-class frontmatter "
                f"(design.md declares '{klass}')"
            )
        elif sibling_class != klass:
            findings.append(
                f"{name}: weight-class '{sibling_class}' diverges from "
                f"design.md's '{klass}'"
            )
    return findings


# Ceremony rungs for escalation, lightest first. ``spike`` is absent: it is a
# different axis (unknown approach), never an escalation target.
ESCALATION_ORDER = ("just-do-it", "light", "full")


def escalate(design_dir: Path, reason: str, to: str) -> str:
    """Stamp a heavier weight class into design.md and every present sibling.

    Upward only: the target must rank strictly above ``design.md``'s declared
    class in ``ESCALATION_ORDER``, so the same class, a lighter one, ``spike``
    or an unknown value raise ``ValueError`` with **no file touched**
    (de-escalation is refused by the weight-class protocol). A design whose
    class came from the default (no frontmatter) has nothing above it and is
    refused too. On success every artifact in ``_SIBLING_ARTIFACTS`` that
    exists is stamped, and the one log line for the run is returned.
    """
    design_dir = Path(design_dir)
    current, source = read_class(design_dir)
    if to not in ESCALATION_ORDER:
        raise ValueError(
            f"cannot escalate to {to!r}; expected one of {ESCALATION_ORDER}"
        )
    if source != "frontmatter" or current not in ESCALATION_ORDER:
        raise ValueError(
            f"design.md declares no escalatable weight-class (current {current!r})"
        )
    if ESCALATION_ORDER.index(to) <= ESCALATION_ORDER.index(current):
        raise ValueError(
            f"refused de-escalation: {to!r} is not heavier than {current!r}"
        )
    write_class(design_dir / "design.md", to)
    for name in _SIBLING_ARTIFACTS:
        sibling = design_dir / name
        if sibling.is_file():
            write_class(sibling, to)
    return (
        f"[tp-run-full-design] weight-class escalation: "
        f"{current} \u2192 {to} ({reason})"
    )


def write_class(artifact_path: Path, klass: str) -> None:
    """Insert or update ``weight-class`` in the artifact's frontmatter block.

    Idempotent; preserves other frontmatter keys and the document body.
    Raises ValueError on an invalid class (the file is left untouched).
    """
    if klass not in VALID_CLASSES:
        raise ValueError(
            f"invalid weight class {klass!r}; expected one of {VALID_CLASSES}"
        )
    path = Path(artifact_path)
    text = path.read_text(encoding="utf-8")
    existing = parse_frontmatter(text)
    if existing:
        # Rewrite the existing block, replacing/adding the weight-class key.
        existing["weight-class"] = klass
        body = text.splitlines(keepends=True)
        # Find the closing fence line index (parse succeeded, so it exists).
        close = next(
            i for i, line in enumerate(body[1:], start=1) if line.strip() == "---"
        )
        block = "---\n" + "".join(f"{k}: {v}\n" for k, v in existing.items()) + "---\n"
        new_text = block + "".join(body[close + 1:])
    else:
        new_text = f"---\nweight-class: {klass}\n---\n{text}"
    if new_text != text:
        path.write_text(new_text)


def main(argv=None) -> int:
    """Thin CLI over the library functions so SKILL.md steps can shell them.

    Subcommands: ``recommend --risk … --blast-radius … --reversibility …
    --novelty …`` | ``read {design_dir}`` | ``check {design_dir}`` (exit 0
    clean, 1 findings) | ``escalate {design_dir} --to {class} --reason {r}``
    (exit 0 with the log line, 1 refused).
    """
    parser = argparse.ArgumentParser(prog="weight_class.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("recommend", help="rubric: map the four axes to a class")
    for axis in ("--risk", "--blast-radius", "--reversibility", "--novelty"):
        rec.add_argument(axis, required=True)

    rd = sub.add_parser("read", help="print design.md's class and its source")
    rd.add_argument("design_dir")

    rw = sub.add_parser("review-weight", help="print the review weight alone")
    rw.add_argument("design_dir")

    chk = sub.add_parser("check", help="cross-artifact consistency findings")
    chk.add_argument("design_dir")

    esc = sub.add_parser(
        "escalate", help="stamp a heavier class into design.md + siblings"
    )
    esc.add_argument("design_dir")
    esc.add_argument("--to", required=True)
    esc.add_argument("--reason", required=True)

    args = parser.parse_args(argv)
    if args.command == "recommend":
        klass, why = recommend_class(
            args.risk, args.blast_radius, args.reversibility, args.novelty
        )
        print(f"{klass}: {why}")
        return 0
    if args.command == "read":
        klass, source = read_class(Path(args.design_dir))
        print(f"{klass} ({source})")
        return 0
    if args.command == "review-weight":
        weight, _ = read_review_weight(Path(args.design_dir))
        print(weight)
        return 0
    if args.command == "escalate":
        try:
            print(escalate(Path(args.design_dir), args.reason, args.to))
        except ValueError as exc:
            print(f"{exc}", file=sys.stderr)
            return 1
        return 0
    findings = check_consistency(Path(args.design_dir))
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
