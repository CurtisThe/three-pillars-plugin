#!/usr/bin/env python3
"""repo_config_load.py — runtime validation of `.three-pillars/config.json`.

design: consumer-repo-parity (Phase 1)

`prune_invalid(config, schema)` walks a JSON document against the *exact*
keyword subset the shipped schema uses and removes only the keys that fail,
one warning per removal; valid siblings stay. Typing is jsonschema's
(draft 2020-12): a `bool` is never an `integer`; an `integer` is an `int` or
an integral `float`. The walk is post-order: a node that fails after its
children are pruned is dropped whole with one warning. `schema_version`
failing is fatal: it returns `({}, [upgrade message])`, keeping "older code
reading a newer config fails closed".

`load_repo_config(repo_root, *, source="worktree")` reads the working tree or
`git show HEAD:` (the gate), prunes it, and returns `ConfigLoad(config,
warnings, status)` — never raising. `update_config(root, dotted_key, value)`
sets one key, validates (any prune warning is a `ValueError`) and writes
atomically (temp + `os.replace`); an absent file is seeded with
`{"schema_version": 1}`, never half-created on an invalid value. `main(argv)`
is the `set` CLI. Stdlib-only: a gate/helper dependency, no third-party imports.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

os_replace = os.replace  # seam the atomic-write test monkeypatches (rename failure)

# The exact keyword subset the real schema uses. A keyword outside it fails
# test_repo_config_prune.py::test_real_schema_uses_no_keyword_outside_the_subset,
# so the subset cannot drift silently.
SUPPORTED_KEYWORDS = frozenset({
    "type", "properties", "additionalProperties", "required",
    "enum", "const", "minimum", "maximum", "exclusiveMinimum",
    "minLength", "items",
})

# Schema-relative path to the shipped schema (Task 1.2's `load_repo_config`
# reads it from here; a missing `schema_version` is the one fatal condition).
SCHEMA_PATH = Path(__file__).resolve().parent / "repo-config.schema.json"


def _is_type(value, name: str) -> bool:
    """jsonschema (draft 2020-12) typing, not Python's `isinstance`.

    A `bool` is never an `integer` or `number` (unlike `isinstance(True, int)`);
    an `integer` is an `int` or an integral `float` (6.0 passes); `number` is
    any int/float except bool; `null` is `None`; `string` is `str`.
    """
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and value.is_integer()
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    return True  # an unrecognized type name is not a constraint


def _json_equal(a, b) -> bool:
    """Compare as jsonschema's `enum`/`const` do: bool-to-bool only, numbers
    by value (`1 == 1.0`), otherwise by identity of type and value."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def _enum_match(value, options) -> bool:
    return any(_json_equal(value, option) for option in options)


def _fail_reason(value, schema: dict) -> str | None:
    """The reason `value` fails `schema`, or None if it passes.

    Only the `SUPPORTED_KEYWORDS` subset is consulted; annotation keywords are
    ignored. Type-scoped constraints apply only when the type allows `value`
    (`minLength` to strings, numeric bounds to numbers), as in JSON Schema.
    """
    type_spec = schema.get("type")
    if type_spec is not None:
        names = type_spec if isinstance(type_spec, list) else [type_spec]
        if not any(_is_type(value, n) for n in names):
            return f"type {type_spec!r}"
    if "enum" in schema and not _enum_match(value, schema["enum"]):
        return f"not in {schema['enum']}"
    if "const" in schema and not _json_equal(value, schema["const"]):
        return f"not equal to {schema['const']!r}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"< minimum {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"> maximum {schema['maximum']}"
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return f"<= exclusiveMinimum {schema['exclusiveMinimum']}"
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return f"shorter than minLength {schema['minLength']}"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return f"missing required key {key!r}"
    return None


def _walk(node, schema: dict, dotted: str, warnings: list) -> tuple:
    """Post-order: prune the children, then check the node's own constraints.

    Returns `(kept, dropped)` — the pruned value, and True when the node
    itself failed and was dropped whole (exactly one warning for the node;
    any children it removed warned for themselves first).
    """
    def join(segment: str) -> str:
        return f"{dotted}.{segment}" if dotted else segment

    if isinstance(node, list):
        items_schema = schema.get("items")
        kept = []
        for index, item in enumerate(node):
            child, dropped = _walk(item, items_schema or {}, join(str(index)), warnings)
            if not dropped:
                kept.append(child)
        node = kept
    elif isinstance(node, dict):
        props = schema.get("properties") or {}
        extra = schema.get("additionalProperties")
        kept = {}
        for key, value in node.items():
            child, dropped = _walk(value, props.get(key, {}), join(key), warnings)
            if dropped:
                continue
            if key not in props and extra is False:
                warnings.append(f"config: dropped {join(key)} (unknown key)")
                continue
            kept[key] = child
        node = kept
    reason = _fail_reason(node, schema)
    if reason is not None:
        path = f"{dotted} " if dotted else ""
        warnings.append(f"config: dropped {path}({reason})")
        return None, True
    return node, False


def prune_invalid(config: dict, schema: dict) -> tuple:
    """Prune the keys of `config` that fail `schema`, keeping valid siblings.

    Returns `(pruned_config, warnings)`. When the schema gates on a required
    `schema_version` (the shipped schema does) and the prune leaves no valid one,
    the whole config is absent: `({}, [upgrade message])` — older code reading
    a newer (or missing) version fails closed.
    """
    warnings: list = []
    pruned, _ = _walk(config, schema, "", warnings)
    requires_version = "schema_version" in schema.get("required", [])
    if requires_version and (not isinstance(pruned, dict) or "schema_version" not in pruned):
        upgrade = (
            "config: schema_version is missing or not the supported version 1; "
            "the whole config is ignored (older code reading a newer config fails "
            "closed — upgrade to a release that recognizes the new schema_version)"
        )
        return {}, [upgrade]
    if pruned is None:  # the config root itself failed its own constraints
        return {}, warnings
    return pruned, warnings


# --- Task 1.2: load / update / the `set` CLI ----------------------------------

CONFIG_FILE = Path(".three-pillars") / "config.json"
ConfigLoad = namedtuple("ConfigLoad", ("config", "warnings", "status"))


def _read_raw(root: Path, source: str):
    """The raw config text, or None when absent (file, HEAD, or no repo)."""
    if source == "head":
        proc = subprocess.run(
            ["git", "-C", str(root), "show", "HEAD:" + str(CONFIG_FILE)],
            capture_output=True, text=True)
        return proc.stdout if proc.returncode == 0 else None
    return (root / CONFIG_FILE).read_text(encoding="utf-8")


def load_repo_config(repo_root, *, source: str = "worktree") -> "ConfigLoad":
    """Read and prune the repo config; never raises.

    `source="worktree"` reads the working tree; `source="head"` reads
    `git show HEAD:` (the gate's provenance — an uncommitted edit cannot
    change what it returns). Invalid keys are pruned with one warning each;
    a missing file is `absent`, bad JSON / a non-object / an unreadable file
    is `unreadable` (both: `config={}` + one warning). A fatal
    `schema_version` failure keeps `status="ok"` with `config={}` and the
    upgrade warning (the reader distinguishes it by the empty config).
    """
    root = Path(repo_root)
    try:
        raw = _read_raw(root, source)
    except FileNotFoundError:
        return ConfigLoad({}, [f"config: {CONFIG_FILE} absent"], "absent")
    except (OSError, UnicodeError) as exc:
        # UnicodeError: a non-UTF-8 file (worktree read or `git show` decode) is
        # "unreadable" too — a ValueError, not an OSError, so caught explicitly.
        return ConfigLoad({}, [f"config: {CONFIG_FILE} unreadable: {exc}"], "unreadable")
    if raw is None:
        return ConfigLoad({}, [f"config: {CONFIG_FILE} absent"], "absent")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return ConfigLoad({}, [f"config: not valid JSON: {exc}"], "unreadable")
    if not isinstance(data, dict):
        return ConfigLoad({}, [f"config: {CONFIG_FILE} must be a JSON object"], "unreadable")
    pruned, warnings = prune_invalid(data, _load_schema())
    return ConfigLoad(pruned, warnings, "ok")


_SCHEMA: dict | None = None  # loaded once (lazily) from SCHEMA_PATH


def _load_schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA


def update_config(repo_root, dotted_key: str, value) -> None:
    """Set `dotted_key` to `value`, validate, and write atomically.

    Starts from the existing file, or `{"schema_version": 1}` when the file
    is absent (plan retry 3: seed, not raise). The set config is pruned; ANY
    prune warning — the new key failing, or a fatal `schema_version` — raises
    `ValueError` with the file byte-identical; an absent file on an invalid
    value creates nothing (validated before the directory is made). The write
    is temp + `os.replace`; a failed rename is cleaned up and raises.
    """
    root = Path(repo_root)
    path = root / CONFIG_FILE
    parts = [p for p in dotted_key.split(".") if p]
    if not parts:
        raise ValueError("a dotted key is required (e.g. ci.expects_github_checks)")
    schema = _load_schema()

    if not path.exists():
        base = {"schema_version": 1}  # absent: seed, not raise (plan retry 3)
    else:
        try:
            base = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"cannot update: {CONFIG_FILE} unreadable: {exc}") from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"cannot update: {CONFIG_FILE} is not valid JSON: {exc}") from exc
        if not isinstance(base, dict):
            raise ValueError(f"cannot update: {CONFIG_FILE} must be a JSON object")

    candidate = json.loads(json.dumps(base))  # a detached copy, then set + prune
    node = candidate
    for part in parts[:-1]:
        child = node.get(part)
        if child is None:
            child = {}
            node[part] = child
        if not isinstance(child, dict):
            raise ValueError(f"cannot set {dotted_key}: segment {part!r} is not an object")
        node = child
    node[parts[-1]] = value
    pruned, warnings = prune_invalid(candidate, schema)
    if warnings:  # any warning is a raise: the new key failed, or an existing
        raise ValueError(  # key would be pruned, or schema_version is fatal
            f"update rejected (file untouched): {dotted_key} — " + "; ".join(warnings))

    # The write: only reached on a clean result. Atomic temp + rename.
    cfg_dir = root / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(cfg_dir), prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(pruned, indent=2) + "\n")
        try:
            os_replace(tmp, str(path))
        except BaseException as exc:
            raise ValueError(f"cannot update: atomic rename failed: {exc}") from exc
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def main(argv) -> int:
    """`repo_config_load.py set <dotted.key> <json-value> [--repo P]`.

    Exits 0 on a written config; 1 with the error on stderr (file untouched)
    on a non-JSON value, an invalid value, an unreadable file, or a bad
    `schema_version`. `--repo` defaults to `git rev-parse --show-toplevel`.
    """
    args = list(argv or [])
    if args[:1] != ["set"] or len(args) < 3:
        print("usage: repo_config_load.py set <dotted.key> <json-value> [--repo P]",
              file=sys.stderr)
        return 1
    key, raw_value, rest = args[1], args[2], args[3:]
    repo = None
    if rest[:1] == ["--repo"]:
        if len(rest) < 2:
            print("usage: --repo <path>", file=sys.stderr)
            return 1
        repo, rest = rest[1], rest[2:]
    if rest:
        print(f"unrecognized arguments: {' '.join(rest)}", file=sys.stderr)
        return 1
    try:
        try:
            value = json.loads(raw_value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"value is not JSON: {raw_value!r}") from exc
        if repo is None:
            proc = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True)
            if proc.returncode != 0 or not proc.stdout.strip():
                raise ValueError("not inside a git repository (and no --repo "
                                 "given); pass --repo <path>")
            repo = Path(proc.stdout.strip())
        update_config(repo, key, value)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
