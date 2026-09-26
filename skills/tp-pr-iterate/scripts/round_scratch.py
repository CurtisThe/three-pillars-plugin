"""round_scratch — per-round, per-angle scratch dirs and the round manifest.

design: iterate-convergence-budget (Task 6.2)

`prepare` creates a fresh dir `root/rounds/<pr>/r<N>` (or `r<N>.1` after a
`rerun-review` tail) with one subdir per angle plus `tail/`, and writes
`angles.json` — the path authority for the round: `paths{proof_root,
state_path, log_path}`, `pr_url`, `round`, `ordinal`, `base`, `head` and one
entry per angle (name, role, model, tier, reply_path, prompt). The round number
is derived from the dirs (cold-resume safe), never from memory; a dir is never
reused. `read_replies` turns a missing or empty reply into an unparseable
string, so a clobbered sibling becomes a sentinel and blocks (fail-closed).
`flush_log` moves the loop log into decisions.md; `safe_remove` deletes only an
`r<N>` dir inside its owner; `tail_check` validates `tail/envelope.json`
against `schemas/round-tail.v1.json`.

CLI: `prepare | flush | remove | tail-check` (exit 2 + one JSON line on refusal).
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import angles as angles_mod  # noqa: E402

SCHEMA_PATH = _HERE.parent / "schemas" / "round-tail.v1.json"
MANIFEST = "angles.json"
REPLY = "reply.md"
TAIL = "tail"
ENVELOPE = "envelope.json"
TAIL_FAILED = {"terminal": "needs-human-attention", "reason": "tail-failed"}

_ROUND_RE = re.compile(r"^r(\d+)(\.1)?$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PR_RE = re.compile(r"/pull/(\d+)")


class RerunLimit(RuntimeError):
    """A second `rerun-review` of the same round."""


class TailFailed(RuntimeError):
    """The latest round's tail left no valid envelope."""


class RemoveRefused(ValueError):
    """`safe_remove` target is not an `r<N>` dir inside its owner."""


def _pr_number(pr_url: str) -> str:
    m = _PR_RE.search(str(pr_url))
    if not m:
        raise ValueError(f"not a PR url: {pr_url!r}")
    return m.group(1)


def _latest(rounds_dir: Path):
    """→ (N, is_rerun, path) of the newest round dir, or None."""
    found = []
    if rounds_dir.is_dir():
        for p in rounds_dir.iterdir():
            m = _ROUND_RE.match(p.name)
            if m and p.is_dir() and not p.is_symlink():
                found.append((int(m.group(1)), bool(m.group(2)), p))
    return max(found, key=lambda t: (t[0], t[1])) if found else None


def _next_ordinal(rounds_dir: Path) -> tuple[int, str]:
    latest = _latest(rounds_dir)
    if latest is None:
        return 1, "r1"
    n, is_rerun, path = latest
    try:
        env = json.loads((path / TAIL / ENVELOPE).read_text(encoding="utf-8"))
        action = env["action"]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise TailFailed(f"{path.name}: no valid tail envelope ({exc})") from exc
    if action == "rerun-review":
        if is_rerun:
            raise RerunLimit(f"{path.name}: second rerun-review of round {n}")
        return n, f"r{n}.1"
    return n + 1, f"r{n + 1}"


def prepare(root, pr_url, angles, *, base, head, effort, state_path, log_path) -> Path:
    """Create the next round dir with per-angle subdirs and write its manifest."""
    for a in angles:
        if not _SAFE_NAME.match(str(a.get("name", ""))) or a["name"] == TAIL:
            raise ValueError(f"unsafe angle name for a scratch dir: {a.get('name')!r}")
    root = Path(root).absolute()
    rounds_dir = root / "rounds" / _pr_number(pr_url)
    n, ordinal = _next_ordinal(rounds_dir)
    rounds_dir.mkdir(parents=True, exist_ok=True)
    round_dir = rounds_dir / ordinal
    round_dir.mkdir()  # never reused: FileExistsError if it somehow exists
    (round_dir / TAIL).mkdir()
    entries = []
    for a in angles:
        (round_dir / a["name"]).mkdir()
        reply = str(round_dir / a["name"] / REPLY)
        entries.append({
            "name": a["name"], "role": a["role"], "model": a["model"],
            "tier": angles_mod.tier(a), "reply_path": reply,
            "prompt": angles_mod.build_prompt(a, base=base, head=head, effort=effort,
                                              reply_path=reply),
        })
    manifest = {
        "pr_url": pr_url, "round": n, "ordinal": ordinal, "base": base, "head": head,
        "effort": effort,
        "paths": {"proof_root": str(root), "state_path": str(Path(state_path).absolute()),
                  "log_path": str(Path(log_path).absolute())},
        "angles": entries,
    }
    (round_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return round_dir


def read_replies(round_dir) -> list[str]:
    """Each manifest angle's reply text; missing/empty → an unparseable marker."""
    round_dir = Path(round_dir)
    manifest = json.loads((round_dir / MANIFEST).read_text(encoding="utf-8"))
    out = []
    for e in manifest.get("angles") or ():
        path = Path(e["reply_path"])
        path = path if path.is_absolute() else round_dir / path
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        out.append(text if text.strip() else f"<missing reply: {e.get('name')}>")
    return out


def flush_log(log_path, decisions_path) -> int:
    """Append the loop log to decisions.md and truncate it. → lines appended."""
    log_path = Path(log_path)
    try:
        text = log_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return 0
    with open(decisions_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    log_path.write_text("", encoding="utf-8")
    return len(lines)


def safe_remove(target, owner) -> None:
    """Delete `target` only if it is a real `r<N>` dir resolving strictly inside `owner`."""
    target, owner = Path(target), Path(owner)
    if target.is_symlink():
        raise RemoveRefused(f"{target} is a symlink")
    resolved, owner_r = target.resolve(), owner.resolve()
    if resolved == owner_r or owner_r not in resolved.parents:
        raise RemoveRefused(f"{target} is not inside {owner}")
    if not _ROUND_RE.match(resolved.name) or not resolved.is_dir():
        raise RemoveRefused(f"{target} is not a round dir")
    shutil.rmtree(resolved)


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _type_ok(value, name) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def _errors(value, schema, where="$") -> list[str]:
    """Validate the JSON-Schema subset the round-tail schema uses."""
    errs = []
    if "const" in schema and value != schema["const"]:
        return [f"{where}: expected {schema['const']!r}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where}: not in {schema['enum']}"]
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        if not any(_type_ok(value, t) for t in names):
            return [f"{where}: expected {types}"]
    if isinstance(value, int) and not isinstance(value, bool) and "minimum" in schema:
        if value < schema["minimum"]:
            errs.append(f"{where}: below {schema['minimum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{where}: too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{where}: too long")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errs += _errors(item, schema["items"], f"{where}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        errs += [f"{where}: missing {k}" for k in schema.get("required", ()) if k not in value]
        if schema.get("additionalProperties") is False:
            errs += [f"{where}: unexpected {k}" for k in value if k not in props]
        for k, sub in props.items():
            if k in value:
                errs += _errors(value[k], sub, f"{where}.{k}")
    return errs


def envelope_errors(envelope) -> list[str]:
    """Errors validating `envelope` against round-tail.v1 ([] when valid)."""
    return _errors(envelope, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def tail_check(round_dir):
    """None when `R/tail/envelope.json` is a valid round-tail.v1; else TAIL_FAILED."""
    try:
        env = json.loads((Path(round_dir) / TAIL / ENVELOPE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(TAIL_FAILED)
    return dict(TAIL_FAILED) if envelope_errors(env) else None


def _load_config(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _refuse(payload) -> int:
    print(json.dumps(payload))
    return 2


def _cmd_prepare(a) -> int:
    try:
        declared = angles_mod.load_angles(_load_config(a.config))
    except (ValueError, OSError) as exc:
        return _refuse({"terminal": "needs-human-attention", "reason": "angles-invalid",
                        "detail": str(exc)})
    try:
        r = prepare(a.root, a.pr_url, declared, base=a.base, head=a.head, effort=a.effort,
                    state_path=a.state, log_path=a.log)
    except RerunLimit as exc:
        return _refuse({"terminal": "needs-human-attention", "reason": "rerun-limit",
                        "detail": str(exc)})
    except TailFailed as exc:
        return _refuse({**TAIL_FAILED, "detail": str(exc)})
    except (ValueError, OSError) as exc:  # unsafe angle name, non-PR url, unwritable root
        return _refuse({"terminal": "needs-human-attention", "reason": "prepare-refused",
                        "detail": str(exc)})
    print(r)
    return 0


def _cmd_remove(a) -> int:
    try:
        safe_remove(a.target, a.owner)
    except RemoveRefused as exc:
        return _refuse({"refused": str(exc)})
    print(json.dumps({"removed": str(a.target)}))
    return 0


def _cmd_tail_check(a) -> int:
    failed = tail_check(a.round_dir)
    if failed:
        return _refuse(failed)
    print(json.dumps({"ok": True}))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Per-round scratch dirs for /tp-pr-iterate.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    for flag in ("--root", "--pr-url", "--base", "--head", "--state", "--log"):
        p.add_argument(flag, required=True)
    p.add_argument("--effort", default="high")
    p.add_argument("--config", default=".three-pillars/config.json")
    f = sub.add_parser("flush")
    f.add_argument("--log", required=True)
    f.add_argument("--decisions", required=True)
    r = sub.add_parser("remove")
    r.add_argument("--target", required=True)
    r.add_argument("--owner", required=True)
    t = sub.add_parser("tail-check")
    t.add_argument("--round-dir", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "prepare":
        return _cmd_prepare(a)
    if a.cmd == "flush":
        print(json.dumps({"appended": flush_log(a.log, a.decisions)}))
        return 0
    if a.cmd == "remove":
        return _cmd_remove(a)
    return _cmd_tail_check(a)


if __name__ == "__main__":
    sys.exit(main())
