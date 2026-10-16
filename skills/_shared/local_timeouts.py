"""Client-timeout offer for local-model runs: when wanted, when settled, what it would add.

`plan` is pure; `apply` writes only the missing keys; `decline` / `status` record and report.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repo_config_load  # noqa: E402

TIMEOUTS = {
    "CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": 1_800_000,
    "CLAUDE_STREAM_IDLE_TIMEOUT_MS": 1_800_000,
    "API_TIMEOUT_MS": 1_800_000,
    "CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS": 1_500_000,
}
MIN_CLAUDE_VERSION = (2, 1, 242)
SETTINGS_REL = Path(".claude") / "settings.json"
CONFIG_KEY = "local_implement.client_timeouts"


def _block(config: dict) -> dict:
    b = config.get("local_implement")
    return b if isinstance(b, dict) else {}


def wanted(config: dict) -> bool:
    """True when local-model implement runs are enabled or a model is `local-*`."""
    if _block(config).get("enabled") is True:
        return True
    models = config.get("models")
    if isinstance(models, dict):
        return any(isinstance(v, str) and v.startswith("local-") for v in models.values())
    return False


def _env_of(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError("settings file is not a JSON object")
    env = data.get("env", {})
    if not isinstance(env, dict):
        raise ValueError("settings 'env' is not a JSON object")
    return env


def settled(config: dict, root=None) -> bool:
    """Nothing left to offer: not wanted, already applied/declined, or settings hold all values."""
    if not wanted(config):
        return True
    rec = _block(config).get("client_timeouts")
    if isinstance(rec, dict) and (rec.get("applied_at") or rec.get("declined") is True):
        return True
    if root is None:
        return False
    path = Path(root) / SETTINGS_REL
    try:
        env = _env_of(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False
    return all(env.get(k) == str(v) for k, v in TIMEOUTS.items())


def plan(root) -> dict:
    """What applying the timeouts to `<root>/.claude/settings.json` would do."""
    path = Path(root) / SETTINGS_REL
    creates = not path.exists()
    old_text = "" if creates else path.read_text(encoding="utf-8")
    data = {} if creates else json.loads(old_text)
    env = _env_of(data)
    add, keep, same = {}, {}, []
    for k, v in TIMEOUTS.items():
        want = str(v)
        if k not in env:
            add[k] = want
        elif env[k] == want:
            same.append(k)
        else:
            keep[k] = env[k]
    new = dict(data)
    new["env"] = {**env, **add}
    new_text = json.dumps(new, indent=2) + "\n"
    diff = "".join(difflib.unified_diff(
        old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
        fromfile="/dev/null" if creates else str(path), tofile=str(path)))
    return {"path": str(path), "creates_file": creates, "add": add,
            "keep": keep, "same": same, "diff": diff}


def _write_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def apply(root, *, now=None) -> dict:
    """Add only the missing timeout keys to settings `env`, then record the offer as applied."""
    p = plan(root)
    path = Path(p["path"])
    if p["add"]:
        data = {} if p["creates_file"] else json.loads(path.read_text(encoding="utf-8"))
        data["env"] = {**_env_of(data), **p["add"]}
        _write_settings(path, data)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    values = {k: int(v) for k, v in p["add"].items()}
    values.update({k: TIMEOUTS[k] for k in p["same"]})
    record = {"applied_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "declined": False, "values": values}
    repo_config_load.update_config(root, CONFIG_KEY, record)
    return record


def decline(root) -> dict:
    """Record that the operator declined the offer."""
    record = {"applied_at": None, "declined": True, "values": {}}
    repo_config_load.update_config(root, CONFIG_KEY, record)
    return record


def _env_now(root) -> dict:
    try:
        return _env_of(json.loads((Path(root) / SETTINGS_REL).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def status(root) -> dict:
    """Where the timeout offer stands: state, drifted keys (never rewritten), one-line text."""
    config = repo_config_load.load_repo_config(root).config
    env = _env_now(root)
    rec = _block(config).get("client_timeouts")
    rec = rec if isinstance(rec, dict) else None
    drift: list = []
    if not wanted(config):
        state, line = "not-wanted", "client timeouts: not wanted (no local-model runs configured)"
    elif all(env.get(k) == str(v) for k, v in TIMEOUTS.items()):
        state, line = "applied", "client timeouts: applied"
    elif rec and rec.get("declined") is True:
        state, line = "declined", "client timeouts: declined"
    elif rec and rec.get("applied_at"):
        vals = rec.get("values") if isinstance(rec.get("values"), dict) else {}
        drift = [{"key": k, "recorded": v, "now": env.get(k)} for k, v in vals.items()
                 if env.get(k) != str(v)]
        if drift:
            state = "drifted"
            line = "client timeouts: drifted (" + ", ".join(d["key"] for d in drift) + ")"
        else:
            state, line = "applied", "client timeouts: applied"
    else:
        state, line = "unoffered", "client timeouts: not yet offered"
    return {"state": state, "drift": drift, "line": line}


# --- Task 4.4: version check + CLI ---------------------------------------------

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def claude_version(run=subprocess.run) -> tuple[int, int, int] | None:
    """The installed `claude` version as a tuple, or None on any failure."""
    try:
        out = run(["claude", "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    m = _VERSION_RE.search(out.stdout or "")
    if not m:
        return None
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def _version_ok(version) -> bool | None:
    return None if version is None else version >= MIN_CLAUDE_VERSION


def main(argv=None) -> int:
    """CLI: `offer [--root] [--claude-version]`, `apply`, `decline`, `status`."""
    parser = argparse.ArgumentParser(prog="local_timeouts",
                                     description="Client-timeout offer for local-model runs.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("offer", "apply", "decline", "status"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        if name == "offer":
            p.add_argument("--claude-version", default=None)
    ns = parser.parse_args(argv)
    root = Path(ns.root)
    try:
        config = repo_config_load.load_repo_config(root).config
        if ns.command == "offer":
            if getattr(ns, "claude_version", None):
                m = _VERSION_RE.search(ns.claude_version)
                version = tuple(int(g) for g in m.groups()) if m else None
            else:
                version = claude_version()
            result = {"wanted": wanted(config),
                      "settled": settled(config, root),
                      "version": ".".join(map(str, version)) if version else None,
                      "version_ok": _version_ok(version),
                      "plan": plan(root)}
            print(json.dumps(result))
            return 0
        if ns.command == "apply":
            print(json.dumps(apply(root)))
            return 0
        if ns.command == "decline":
            print(json.dumps(decline(root)))
            return 0
        print(json.dumps(status(root)))
        return 0
    except ValueError as exc:
        print(f"local_timeouts: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
