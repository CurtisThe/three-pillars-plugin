#!/usr/bin/env python3
"""fragility_repo_rules.py — per-repo fragility rules: schema, load, validate, matchers, CLI.

design: fragile-test-prevention (detailed-design-lint §Per-repo rules)

`RULES_PATH` holds `{"schema_version": 1, "rules": [...]}`, a closed schema: `id`
(`[a-z0-9-]+`, unique, not a generic id), `kind` (a key of `KINDS`), `params` (the kind's
one non-empty parameter), non-empty `reason`/`approved_by`, ISO `date`; optional
`applies_to` (`APPLIES_TO`, default `all`) and `gating` (bool, default false). `load` gives
`RepoRules(rules, errors)`: none of either for an absent file; no rule if any error, each
naming the file and the rule, so a broken file is never silently dropped (lint exit 2).
Each kind is a generic rule's AST shape with a parameter: `forbidden-call` on `dotted(func)`,
`forbidden-literal-name` a name glob on a `deny-literal` literal, `forbidden-read-assert` a
glob on the constant path read (`ROOT / "a/b.json"` is `a/b.json`, matched whole or after a
`/`) in the `md-read-assert` shape. The CLI (`validate`, `add`) is the learn skills' writer.
stdlib-only.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import fnmatch
import functools
import json
import os
import re
import string
import sys
from pathlib import Path
from typing import Callable, Iterator, NamedTuple

from fragility_ast import (_own_nodes, bound_names, dotted, is_test_file, per_tree,
                           skill_paths_path, skill_text_path, walk_once)
from fragility_registry import RULES
from fragility_rules_flag import _asserts_on_prose
from fragility_rules_gating import Finding, _collection_literal, _scopes

RULES_PATH = Path(".three-pillars", "fragility-rules.json")
SCHEMA_VERSION = 1
APPLIES_TO = ("tests", "production", "all")
_GENERIC_IDS = frozenset(rule.id for rule in RULES)
_ID_CHARS = frozenset(string.ascii_lowercase + string.digits + "-")
_PATH_CALLS = frozenset({"Path", "pathlib.Path", "PurePath", "pathlib.PurePath", "open",
                         "io.open"})
_PATH_STEPS = frozenset({"resolve", "absolute", "expanduser", "open"})
_READ_CALLS = frozenset({"read", "read_text", "read_bytes", "readlines"})
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
_MAX_HOPS = 8


class RepoRule(NamedTuple):
    """One rule. Its fields are the schema's closed key set; a default marks a key optional."""
    id: str
    kind: str
    params: dict
    reason: str
    approved_by: str
    date: str
    applies_to: str = "all"
    gating: bool = False


class RepoRules(NamedTuple):
    rules: list[RepoRule]
    errors: list[str]


NO_RULES = RepoRules([], [])
_REQUIRED = tuple(key for key in RepoRule._fields if key not in RepoRule._field_defaults)
Lines = Iterator[tuple[int, int]]


# --- the matchers ---------------------------------------------------------------------

def _forbidden_calls(tree: ast.AST, call: str) -> Lines:
    for node in walk_once(tree):
        if isinstance(node, ast.Call) and dotted(node.func) == call:
            yield node.lineno, node.end_lineno


def _forbidden_literals(tree: ast.AST, name_glob: str) -> Lines:
    for node in walk_once(tree):
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        if targets and _collection_literal(node.value) and any(
                isinstance(t, ast.Name) and fnmatch.fnmatchcase(t.id, name_glob)
                for t in targets):
            yield node.lineno, node.end_lineno


def _const_path(node: ast.AST, env: dict, hops: int = 0) -> str | None:
    """The constant path an expression names (a non-constant head dropped), else None."""
    if hops >= _MAX_HOPS:
        return None
    path = skill_paths_path(node)
    if path is not None:
        return path
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return _const_path(env[node.id], env, hops + 1) if node.id in env else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        tail = _const_path(node.right, env, hops + 1)
        head = _const_path(node.left, env, hops + 1) if tail else None
        return f"{head}/{tail}" if head else tail
    if not isinstance(node, ast.Call):
        return None
    if dotted(node.func) in _PATH_CALLS and node.args:
        return _const_path(node.args[0], env, hops + 1)
    if isinstance(node.func, ast.Attribute) and node.func.attr in _PATH_STEPS:
        return _const_path(node.func.value, env, hops + 1)
    return None


def _globbed(path: str | None, glob: str) -> bool:
    return path is not None and (fnmatch.fnmatchcase(path, glob)
                                 or fnmatch.fnmatchcase(path, "*/" + glob))


def _is_read(node: ast.AST, env: dict, helpers, glob: str, hops: int = 0) -> bool:
    """A read of a path `glob` matches, a name bound to one, a `helpers` call, or off one."""
    if hops >= _MAX_HOPS:
        return False
    if isinstance(node, ast.Name):
        return node.id in env and _is_read(env[node.id], env, helpers, glob, hops + 1)
    if isinstance(node, ast.Subscript):
        return _is_read(node.value, env, helpers, glob, hops + 1)
    if not isinstance(node, ast.Call):
        return False
    skill = skill_text_path(node)
    if skill is not None:
        return _globbed(skill, glob)
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in helpers
    return isinstance(func, ast.Attribute) and (
        (func.attr in _READ_CALLS and _globbed(_const_path(func.value, env), glob))
        or _is_read(func.value, env, helpers, glob, hops + 1))


@per_tree
def _module_functions(tree: ast.AST) -> list[tuple[str, dict, list[ast.AST]]]:
    """`(name, env, returned values)` per module-level function: the walk of its body
    and its bindings, done once per module however many rows of the rules file ask."""
    module_env = bound_names(tree)
    return [(fn.name, module_env | bound_names(fn),
             [n.value for n in _own_nodes(fn) if isinstance(n, ast.Return) and n.value is not None])
            for fn in tree.body if isinstance(fn, _DEFS)]


def _forbidden_read_asserts(tree: ast.AST, path_glob: str) -> Lines:
    """An assert searching or prefix-matching a value read from a matching path; a
    module-level function returning such a read counts as the read (one hop)."""
    helpers = {name for name, env, returned in _module_functions(tree)
               if any(_is_read(value, env, (), path_glob) for value in returned)}
    for nodes, scope in _scopes(tree):
        is_read = functools.partial(_is_read, env=scope.env, helpers=helpers, glob=path_glob)
        for node in nodes:
            if isinstance(node, ast.Assert) and _asserts_on_prose(node.test, is_read):
                yield node.lineno, node.end_lineno


KINDS: dict[str, tuple[str, Callable[[ast.AST, str], Lines]]] = {
    "forbidden-call": ("call", _forbidden_calls),
    "forbidden-literal-name": ("name_glob", _forbidden_literals),
    "forbidden-read-assert": ("path_glob", _forbidden_read_asserts),
}


def visit(tree: ast.AST, path: str, rules) -> list[Finding]:
    """The findings of the per-repo `rules` that apply to `path`'s side, by line."""
    if not rules:
        return []
    side = "tests" if is_test_file(path) else "production"
    found = {}
    for rule in rules:
        if rule.applies_to in ("all", side):
            param, matcher = KINDS[rule.kind]
            for line, end in matcher(tree, rule.params[param]):
                found[(line, rule.id)] = Finding(rule.id, line, end)
    return [found[key] for key in sorted(found)]


# --- validate and load ------------------------------------------------------------------

def _filled(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _iso_date(value) -> bool:
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def _rule_errors(rule: dict, seen: set) -> list[str]:
    """What is wrong with one rule object (`seen`: the ids of the rules before it)."""
    errors = [f"missing {key!r}" for key in _REQUIRED if key not in rule]
    errors += [f"unknown key {key!r}" for key in rule if key not in RepoRule._fields]
    rule_id, kind, params = rule.get("id"), rule.get("kind"), rule.get("params")
    if "id" in rule and not (isinstance(rule_id, str) and rule_id and set(rule_id) <= _ID_CHARS):
        errors.append("id must match [a-z0-9-]+")
    elif rule_id in seen or rule_id in _GENERIC_IDS:
        errors.append("duplicate id" if rule_id in seen else "id is a generic rule id")
    if "kind" in rule and kind not in KINDS:
        errors.append(f"unknown kind {kind!r}")
    elif kind in KINDS:
        want, params = KINDS[kind][0], params if isinstance(params, dict) else {}
        errors += [f"unknown param {key!r}" for key in params if key != want]
        if not _filled(params.get(want)):
            errors.append(f"param {want!r} is missing or empty")
    errors += [f"{key!r} is empty" for key in ("reason", "approved_by")
               if key in rule and not _filled(rule[key])]
    if "date" in rule and not _iso_date(rule["date"]):
        errors.append("date must be an ISO YYYY-MM-DD date")
    if rule.get("applies_to", "all") not in APPLIES_TO:
        errors.append(f"applies_to must be one of {', '.join(APPLIES_TO)}")
    if not isinstance(rule.get("gating", False), bool):
        errors.append("gating must be true or false")
    return errors


def validate(data) -> list[str]:
    """Every schema error of a parsed rules document; a rule's errors name the rule."""
    if not isinstance(data, dict):
        return ["the document must be an object"]
    errors = [f"unknown key {key!r}" for key in data if key not in ("schema_version", "rules")]
    version = data.get("schema_version")
    if not (type(version) is int and version == SCHEMA_VERSION):
        errors.append(f"schema_version must be {SCHEMA_VERSION}, not {version!r}")
    rules = data.get("rules")
    if not isinstance(rules, list):
        return [*errors, "rules must be a list"]
    seen: set[str] = set()
    for index, rule in enumerate(rules):
        rule_id = rule.get("id") if isinstance(rule, dict) else None
        named = isinstance(rule_id, str) and rule_id
        label = f"rule {rule_id!r}" if named else f"rule #{index}"
        found = _rule_errors(rule, seen) if isinstance(rule, dict) else ["not an object"]
        errors += [f"{label}: {error}" for error in found]
        if named:
            seen.add(rule_id)
    return errors


def load(root: str | Path, path: str | Path | None = None) -> RepoRules:
    """The per-repo rules of `path` (default `<root>/RULES_PATH`). Absent: no rule and no
    error. Any error: no rule, and errors naming the file."""
    path = Path(root) / RULES_PATH if path is None else Path(path)
    if not path.exists():
        return RepoRules([], [])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return RepoRules([], [f"{path}: cannot read the rules file: {exc}"])
    errors = validate(data)
    if errors:
        return RepoRules([], [f"{path}: {error}" for error in errors])
    return RepoRules([RepoRule(**rule) for rule in data["rules"]], [])


# --- the CLI: validate and add ------------------------------------------------------------

def _read(path: Path) -> dict:
    """The parsed file, or an empty document if absent; OSError/ValueError if unreadable."""
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "rules": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: dict) -> None:
    """Write through a temp file beside `path`, then `os.replace`: a failure leaves the old
    file (or none) as it was and removes the temp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _report(path: Path, errors: list[str], code: int) -> int:
    for error in errors:
        print(f"{path}: {error}", file=sys.stderr)
    return code


def _cmd_validate(root: str) -> int:
    """Exit 0 for a valid or absent file, 1 for schema errors, 2 if it cannot be read."""
    path = Path(root) / RULES_PATH
    try:
        errors = validate(_read(path))
    except (OSError, ValueError) as exc:
        return _report(path, [f"cannot read the rules file: {exc}"], 2)
    return _report(path, errors, 1 if errors else 0)


def _cmd_add(args: argparse.Namespace) -> int:
    """Exit 0 once added; 1 if the rule is invalid or a duplicate (nothing written); 2 if the
    file is already broken or the write fails (it is never extended, nor left half-written)."""
    path = Path(args.root) / RULES_PATH
    try:
        params = json.loads(args.params)
    except ValueError:
        params = args.params
    value = params.get(KINDS.get(args.kind, ("",))[0], "") if isinstance(params, dict) else ""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{args.kind} {value}".lower()).strip("-")
    rule = {"id": slug if args.id is None else args.id, "kind": args.kind, "params": params,
            "reason": args.reason, "approved_by": args.approved_by,
            "date": datetime.date.today().isoformat(), "applies_to": args.applies_to,
            "gating": args.gating}
    try:
        data = _read(path)
        if errors := validate(data):
            return _report(path, errors, 2)
        data["rules"].append(rule)
        if errors := validate(data):
            return _report(path, errors, 1)
        _write(path, data)
    except (OSError, ValueError) as exc:
        return _report(path, [f"cannot update the rules file: {exc}"], 2)
    print(f"{path}: added rule {rule['id']!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fragility_repo_rules.py",
                                     description="Validate or extend the per-repo rules file.")
    where = argparse.ArgumentParser(add_help=False)
    where.add_argument("--root", default=".", help="the repo root (default: the working dir)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", parents=[where], help="exit 0 valid, 1 invalid, 2 unreadable")
    add = commands.add_parser("add", parents=[where], help="append one rule, atomically")
    for flag in ("kind", "params", "reason", "approved-by"):
        add.add_argument(f"--{flag}", required=True)
    add.add_argument("--applies-to", default="all")
    add.add_argument("--gating", action="store_true")
    add.add_argument("--id", help="default: a slug of the kind and its parameter")
    args = parser.parse_args(argv)
    return _cmd_validate(args.root) if args.command == "validate" else _cmd_add(args)


if __name__ == "__main__":
    sys.exit(main())
