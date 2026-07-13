#!/usr/bin/env python3
"""tp_spec.py — implementation backend for the /tp-spec skill.

Subcommands:
  add      <design>   Scaffold spec-delta.md from template (refuse-to-clobber)
  validate <design>   Validate spec-delta.md via validate_artifact('spec', Path)
                      then run spec_drift scan over the domain base
  merge    <design>   Merge spec-delta.md into domain base via spec_delta.merge()

All functions are importable for tests.  CLI entry-point: main(argv).

Exit codes: 0 ok / 1 BLOCKED or DRIFT / 2 usage error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

_SHARED = Path(__file__).resolve().parent.parent / "_shared"
sys.path.insert(0, str(_SHARED))

import project_root as _pr  # noqa: E402  (needs _SHARED on sys.path)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Module-relative fallback root — used ONLY when the invocation cwd is not
# inside a git repo (e.g. the dev-repo pytest lane importing this module
# directly). In plugin mode this module lives in the plugin cache, so a
# __file__-anchored root would point at the CACHE, not the consumer repo under
# operation; _default_repo() therefore resolves cwd-first via
# project_root.find_project_root() and only falls back to this constant when
# there is no surrounding git repo. [plugin-mode-parity H1]
_FALLBACK_ROOT = Path(__file__).resolve().parent.parent.parent
# The scaffold template ships WITH this module, so it stays __file__-anchored.
_TEMPLATE = Path(__file__).resolve().parent / "templates" / "spec-delta.template.md"


def _default_repo() -> Path:
    """The project repo under operation, resolved from cwd (plugin-safe).

    Falls back to the module-relative root only when cwd is not a git repo.
    """
    root = _pr.find_project_root()
    return root if root is not None else _FALLBACK_ROOT


def _default_designs_root() -> Path:
    return _default_repo() / "three-pillars-docs" / "tp-designs"


def _default_specs_dir() -> Path:
    return _default_repo() / "three-pillars-docs" / "specs"


# ---------------------------------------------------------------------------
# Task 3.2 — cmd_add
# ---------------------------------------------------------------------------

def cmd_add(
    design_name: str,
    designs_root: Optional[Path] = None,
    template_path: Optional[Path] = None,
) -> int:
    """Scaffold spec-delta.md from template into the design directory.

    Returns 0 on success (including no-op when file already exists).
    Returns non-zero if the design directory does not exist.
    """
    dr = designs_root or _default_designs_root()
    tpl = template_path or _TEMPLATE
    design_dir = dr / design_name

    if not design_dir.is_dir():
        print(
            f"error: design directory not found: {design_dir}",
            file=sys.stderr,
        )
        return 1

    delta_path = design_dir / "spec-delta.md"
    if delta_path.exists():
        print(
            f"spec-delta.md already exists at {delta_path} — leaving untouched (refuse-to-clobber)",
            file=sys.stderr,
        )
        return 0

    template_text = tpl.read_text(encoding="utf-8")
    delta_path.write_text(template_text)
    print(f"created: {delta_path}")
    return 0


# ---------------------------------------------------------------------------
# Task 3.3 — cmd_validate
# ---------------------------------------------------------------------------

def cmd_validate(
    delta_path: Path,
    specs_dir: Optional[Path] = None,
    repo: Optional[Path] = None,
) -> int:
    """Validate delta_path using validate_artifact('spec', Path(delta_path)).

    On BLOCKED: prints the JSON verdict to stderr and returns 1.
    On PASS: runs spec_drift scan over specs_dir; returns its exit code.

    Uses validate_artifact(artifact_type, path) — type-first, Path arg.
    The nonexistent .validate(text, type) signature is never referenced here.
    """
    import validate_artifact as _va
    import spec_drift as _sd

    sd = specs_dir or _default_specs_dir()
    repo_root = repo or _default_repo()

    # Call the real validator: type-first, Path arg
    verdict = _va.validate_artifact("spec", Path(delta_path))

    if verdict.verdict == "BLOCKED":
        violations = [
            {
                "code": v.code,
                "message": v.message,
                "location": v.location,
                "severity": v.severity,
            }
            for v in verdict.violations
        ]
        print(
            json.dumps({"verdict": "BLOCKED", "violations": violations}),
            file=sys.stderr,
        )
        return 1

    # Validation passed — run drift scan over the specs tree
    drift_exit = _sd.main(["scan", str(sd), "--repo", str(repo_root)])
    return drift_exit


# ---------------------------------------------------------------------------
# Task 3.4 — cmd_merge
# ---------------------------------------------------------------------------

def cmd_merge(
    design_name: str,
    designs_root: Optional[Path] = None,
    specs_dir: Optional[Path] = None,
    domain: Optional[str] = None,
) -> int:
    """Merge spec-delta.md into the domain base spec via spec_delta.merge().

    Finds: tp-designs/<design>/spec-delta.md (delta)
           specs/<domain>/spec.md (base)

    domain defaults to design_name.

    Returns 0 on success or skip (no delta).
    Returns 1 on MergeConflict, SpecParseError, or missing base.
    """
    import spec_delta as _sd

    dr = designs_root or _default_designs_root()
    sd = specs_dir or _default_specs_dir()
    dom = domain or design_name

    delta_path = dr / design_name / "spec-delta.md"

    if not delta_path.exists():
        print(
            f"no spec-delta.md found at {delta_path} — skipping merge (no-op)",
        )
        return 0

    base_path = sd / dom / "spec.md"
    if not base_path.exists():
        print(
            f"error: base spec not found at {base_path}",
            file=sys.stderr,
        )
        return 1

    base_text = base_path.read_text(encoding="utf-8")
    delta_text = delta_path.read_text(encoding="utf-8")

    try:
        merged = _sd.merge(base_text, [delta_text])
    except (_sd.MergeConflict, _sd.SpecParseError) as exc:
        # Surface the JSON verdict, leave base unchanged
        if isinstance(exc, _sd.MergeConflict):
            issues = [
                {
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                    "location": i.location,
                }
                for i in exc.issues
            ]
            print(
                json.dumps({"verdict": "BLOCKED", "errors": issues}),
                file=sys.stderr,
            )
        else:
            print(
                json.dumps({"verdict": "BLOCKED", "errors": [
                    {"severity": "ERROR", "code": "parse-error",
                     "message": str(exc), "location": "parse"}
                ]}),
                file=sys.stderr,
            )
        return 1

    base_path.write_text(merged)
    print(f"merged: {delta_path} → {base_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _usage() -> None:
    print(
        "usage: tp_spec.py {add <design> | validate <design> [--domain <dom>] "
        "| merge <design> [--domain <dom>]} [--repo <path>]",
        file=sys.stderr,
    )


def _pop_flag(rest: list[str], flag: str) -> "tuple[Optional[str], list[str]]":
    """Pop `<flag> <value>` from rest; return (value_or_None, filtered_rest)."""
    out: list[str] = []
    value: Optional[str] = None
    i = 0
    while i < len(rest):
        if rest[i] == flag and i + 1 < len(rest):
            value = rest[i + 1]
            i += 2
            continue
        out.append(rest[i])
        i += 1
    return value, out


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        _usage()
        return 2

    subcmd, rest = argv[0], argv[1:]

    # --repo overrides the cwd-resolved project root (add/validate/merge).
    repo_arg, rest = _pop_flag(rest, "--repo")
    repo = Path(repo_arg).resolve() if repo_arg else _default_repo()
    designs_root = repo / "three-pillars-docs" / "tp-designs"
    specs_dir = repo / "three-pillars-docs" / "specs"

    if subcmd == "add":
        if not rest:
            print("usage: tp_spec.py add <design> [--repo <path>]", file=sys.stderr)
            return 2
        return cmd_add(rest[0], designs_root=designs_root)

    if subcmd == "validate":
        if not rest:
            print("usage: tp_spec.py validate <design> [--domain <dom>] [--repo <path>]", file=sys.stderr)
            return 2
        domain, rest = _pop_flag(rest, "--domain")
        design_name = rest[0]
        delta_path = designs_root / design_name / "spec-delta.md"
        if not delta_path.exists():
            print(f"error: spec-delta.md not found: {delta_path}", file=sys.stderr)
            return 2
        return cmd_validate(delta_path=delta_path, specs_dir=specs_dir, repo=repo)

    if subcmd == "merge":
        if not rest:
            print("usage: tp_spec.py merge <design> [--domain <dom>] [--repo <path>]", file=sys.stderr)
            return 2
        domain, rest = _pop_flag(rest, "--domain")
        design_name = rest[0]
        return cmd_merge(
            design_name=design_name,
            designs_root=designs_root,
            specs_dir=specs_dir,
            domain=domain,
        )

    print(f"unknown subcommand: {subcmd!r}", file=sys.stderr)
    _usage()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
