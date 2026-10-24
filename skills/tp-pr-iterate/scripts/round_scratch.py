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
`r<N>` dir inside its owner; `reap_exec_dirs` (called by `reproduce.py` once the
replies are merged) deletes the angles' exec dirs; `tail_check` validates `tail/envelope.json`
against `schemas/round-tail.v1.json`.

CLI: `prepare | flush | remove | tail-check | put` (exit 2 + one JSON line on
refusal; `put`, the sub-agents' only write path, is `round_put.py`). The CLI itself
is `round_scratch_cli.py` — `main` here is the thin wrapper its entry point calls,
so `round_scratch.py prepare …` and `rs.main([...])` both keep working. Stdlib only.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import angles as angles_mod  # noqa: E402 — first: it puts skills/_shared on sys.path
import angle_tree  # noqa: E402
import agent_ref  # noqa: E402,I001 — the one spawn-reference resolver
import budget_clock  # noqa: E402
import finder_segments  # noqa: E402
import proof_reap  # noqa: E402
import review_instructions  # noqa: E402
import review_prep  # noqa: E402
import run_scratch  # noqa: E402 — the run's in-tree TMPDIR shape
from repo_config_load import load_repo_config  # noqa: E402

SCHEMA_PATH = _HERE.parent / "schemas" / "round-tail.v1.json"
MANIFEST = "angles.json"
REPLY = "reply.md"
TAIL = "tail"
PREP = "prep"
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


_EXEC_NOTE = (
    "\n\nExec dir: run code, archives and repros in `{exec_dir}` through Bash. Never put "
    "them under the reply dir, and never create them with the Write or Edit tool.\n")


def _strip_round(round_dir: Path) -> list[str]:
    """Strip every real angle subdir of `round_dir` to its reply; never raises."""
    gone = []
    try:
        subs = sorted(p for p in Path(round_dir).iterdir()
                      if p.is_dir() and not p.is_symlink() and p.name not in (TAIL, PREP))
    except OSError as exc:
        print(f"strip skipped {round_dir}: {exc}", file=sys.stderr)
        return gone
    for sub in subs:
        try:
            removed = proof_reap.strip_angle_dir(sub)
        except OSError as exc:
            print(f"strip failed {sub.name}: {exc}", file=sys.stderr)
            continue
        for p in removed:
            rel = Path(p).relative_to(sub).as_posix()
            print(f"stripped {sub.name}/{rel}", file=sys.stderr)
            gone.append(f"{sub.name}/{rel}")
    return gone


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
        if proof_reap._terminal(path):  # closed round: no tail envelope needed
            return n + 1, f"r{n + 1}"
        raise TailFailed(f"{path.name}: no valid tail envelope ({exc})") from exc
    if action == "rerun-review":
        if is_rerun:
            raise RerunLimit(f"{path.name}: second rerun-review of round {n}")
        return n, f"r{n}.1"
    return n + 1, f"r{n + 1}"


def prepare(root, pr_url, angles, *, base, head, effort, state_path, log_path,
            repo=".", plugin_root=None, now=None, prep_dir=None,
            config=None, meta=None) -> Path:
    """Create the next round dir with per-angle subdirs and write its manifest.

    `meta` (the round plan's own keys — `mode`, `pr_base`, `security`,
    `diff_lines`) is merged into the manifest beside `started_at`, so a later round
    can tell the base it reviewed (`base`) from the PR base it grew against
    (`pr_base`). `None` leaves today's bytes exactly.

    `prep_dir` (a prep work dir W whose `meta.json` head is `head`) is moved to
    `R/prep/work` and rendered; each angle with a prep file gets one prompt line.
    `None` leaves today's bytes (the golden in `test_round_scratch_prep.py`).

    `repo` is the reviewed repo (default `.` — the CLI runs from the repo root,
    the same cwd its `--config .three-pillars/config.json` default is relative
    to). Its instructions status is computed once and feeds every angle's
    prompt: the file is named only when it actually exists in that repo. Each entry's
    `agent` is `angles.entry_agent(round, angle)` (the Strata `-medium` variant for a
    `local` angle on a later round) and `agent_ref` its spawn reference
    (`agent_ref.resolve` against `plugin_root`, once per distinct name; unresolvable →
    `AgentRefError`).

    The round start is stamped as `budget_round_started_at` into the existing
    iterate-state file (`budget_clock.stamp_round_start`; a missing file stays
    absent) and recorded as the manifest's `started_at`. `now` is a test seam
    (aware datetime).
    """
    # a diff past the segment threshold: one Strata finder per segment (inert under it / off Strata)
    angles = finder_segments.apply_to_round(angles, config, repo=repo, base=base, head=head)
    for a in angles:
        if not _SAFE_NAME.match(str(a.get("name", ""))) or a["name"] in (TAIL, PREP):
            raise ValueError(f"unsafe angle name for a scratch dir: {a.get('name')!r}")
    instructions_present = (
        review_instructions.status(repo, load_repo_config(repo).config) == "present")
    rev = angle_tree.head_commit(repo, head)  # each angle gets a private copy of this commit
    if rev is None:
        print(f"angle trees skipped: head {head} is not a commit in {repo}", file=sys.stderr)
    root = Path(root).absolute()
    rounds_dir = root / "rounds" / _pr_number(pr_url)
    n, ordinal = _next_ordinal(rounds_dir)
    previous = _latest(rounds_dir)
    started_at = (now or datetime.now(tz=timezone.utc)).isoformat()
    budget_clock.stamp_round_start(state_path, started_at)  # after the refusals, before any dir
    rounds_dir.mkdir(parents=True, exist_ok=True)
    round_dir = rounds_dir / ordinal
    round_dir.mkdir()  # never reused: FileExistsError if it somehow exists
    (round_dir / TAIL).mkdir()
    if previous is not None:  # superseded now: reap its exec dirs + strip its angle dirs, never fail
        cleanup_round(previous[2], strip=True)  # a round that aborted before tail-check leaks none
    prep = {}
    if prep_dir is not None:
        try:  # fail-open by contract (D11): a prep error never refuses the round
            prep_meta = json.loads((Path(prep_dir) / "meta.json").read_text(encoding="utf-8"))
            if prep_meta.get("head") != head:
                raise ValueError(f"meta.json head {prep_meta.get('head')!r} is not {head!r}")
            review_prep.move_work(prep_dir, round_dir)
            prep = review_prep.render(round_dir, angles)
        except Exception as exc:  # noqa: BLE001
            prep, why = {}, " ".join(f"{type(exc).__name__}: {exc}".split())
            with contextlib.suppress(OSError), open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"[cheap-tier] prep not applied: {why}\n")
    agents = [angles_mod.entry_agent(n, a) for a in angles]
    refs = {name: agent_ref.resolve(name, plugin_root)
            for name in dict.fromkeys(agents)}  # each distinct name resolves once
    entries = []
    for a, agent in zip(angles, agents):
        (round_dir / a["name"]).mkdir()
        reply = str(round_dir / a["name"] / REPLY)
        exec_dir = tempfile.mkdtemp(prefix=f"tp-angle-{a['name']}-",  # outside the proof root
                                    dir=run_scratch.outside_tmpdir())  # and the checkout
        tree_dir = angle_tree.make_tree(repo, rev, exec_dir) if rev and not a.get("skipped") else None
        entries.append({
            "name": a["name"], "role": a["role"], "model": a["model"],
            "agent": agent, "agent_ref": refs[agent],
            "dispatch_model": angles_mod.dispatch_model(a, config, root=repo),
            "tier": angles_mod.tier(a), "reply_path": reply, "exec_dir": exec_dir,
            "tree_dir": tree_dir,
            **{k: a[k] for k in ("skipped", "advisory", "segment") if a.get(k)},
            "prompt": angles_mod.build_prompt(a, base=base, head=head, effort=effort,
                                              reply_path=reply, round_dir=str(round_dir),
                                              put_script=str(_HERE / "round_scratch.py"),
                                              instructions_present=instructions_present)
            + _EXEC_NOTE.format(exec_dir=exec_dir) + angle_tree.note(exec_dir, tree_dir)
            + review_prep.prompt_suffix(prep.get(a["name"])),
        })
    manifest = {
        "pr_url": pr_url, "round": n, "ordinal": ordinal, "base": base, "head": head,
        "effort": effort, "started_at": started_at,
        **(meta or {}),
        "paths": {"proof_root": str(root), "state_path": str(Path(state_path).absolute()),
                  "log_path": str(Path(log_path).absolute())},
        "angles": entries,
    }
    (round_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return round_dir


def read_replies(round_dir) -> list[str]:
    """Each manifest angle's reply text; missing/empty → an unparseable marker, and a
    skipped (never dispatched) angle → `angles.SKIPPED_REPLY`."""
    round_dir = Path(round_dir)
    manifest = json.loads((round_dir / MANIFEST).read_text(encoding="utf-8"))
    out = []
    for e in manifest.get("angles") or ():
        if e.get("skipped"):
            out.append(angles_mod.SKIPPED_REPLY)
            continue
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


def _exec_dirs(round_dir) -> list[str]:
    """Each manifest angle's non-empty `exec_dir` string; [] on any read error."""
    try:
        entries = json.loads((Path(round_dir) / MANIFEST).read_text(encoding="utf-8")).get("angles") or []
    except (OSError, ValueError, AttributeError):
        entries = []
    return [e["exec_dir"] for e in entries
            if isinstance(e, dict) and isinstance(e.get("exec_dir"), str) and e["exec_dir"]]


def _rm_exec(d, res) -> None:
    """Delete one exec dir: missing is fine, a failure is a stderr line + `exec_failed`."""
    try:
        shutil.rmtree(d, ignore_errors=False)
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"exec dir not deleted {d}: {exc}", file=sys.stderr)
        res["exec_failed"].append(d)


def _reapable(d) -> bool:
    """A real (non-symlink) absolute `tp-angle-*` dir directly under the system temp,
    tempfile's temp or `run_scratch.outside_tmpdir()` — where `prepare` makes them."""
    try:
        p = Path(d)
        parents = {os.path.realpath(x) for x in (tempfile.gettempdir(), run_scratch._SYSTEM_TMP,
                                                 run_scratch.outside_tmpdir()) if x}
        real_parent = os.path.realpath(p.parent)
        return (p.is_absolute() and p.name.startswith("tp-angle-") and not p.is_symlink()
                and real_parent in parents
                and os.path.realpath(p) == os.path.join(real_parent, p.name))
    except (OSError, ValueError, TypeError):
        return False


def reap_exec_dirs(round_dir) -> dict:
    """Delete each angle's exec dir once its reply is merged (`reproduce.py`, before the
    clean-round scratch check). Guarded (`_reapable`): any other path is left in place and
    listed in `exec_refused`. Never raises; `cleanup_round` stays the idempotent backstop."""
    res = {"exec_failed": [], "exec_refused": []}
    for d in _exec_dirs(round_dir):
        if _reapable(d):
            _rm_exec(d, res)
        else:
            print(f"exec dir left in place (not a tp-angle temp dir) {d}", file=sys.stderr)
            res["exec_refused"].append(d)
    return res


def cleanup_round(round_dir, *, strip) -> dict:
    """Delete every manifest angle's exec dir; strip the angle dirs when `strip`.

    Never raises: a failed deletion is one stderr line and an `exec_failed` entry.
    """
    round_dir = Path(round_dir)
    res = {"exec_failed": [], "stripped": []}
    for d in _exec_dirs(round_dir):
        _rm_exec(d, res)
    if strip:
        res["stripped"] = _strip_round(round_dir)
    return res


def _closing(round_dir) -> bool:
    try:
        env = json.loads((Path(round_dir) / TAIL / ENVELOPE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(env, dict) and env.get("terminal") is not None


def _load_config(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _refuse(payload) -> int:
    print(json.dumps(payload))
    return 2


def main(argv=None) -> int:
    """The CLI entry point — `round_scratch_cli.main`, imported lazily.

    `round_scratch.py prepare …` runs as a subprocess and tests call `rs.main([...])`,
    so this name stays here; the commands themselves (and the `round_plan` delegation)
    live in `round_scratch_cli`, which reaches back through this module's attributes.
    """
    import round_scratch_cli  # noqa: PLC0415 — lazy: it imports this module at module level
    return round_scratch_cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
