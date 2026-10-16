"""child_sandbox.py — the Bash-sandbox block an attempt worktree is launched with.

design: strata-classifier-cost-followups §B1 (task 2.1)

A Strata child's Bash runs inside Claude Code's own sandbox (bubblewrap) once the
repo opts in, so its writes are limited to the working folder. That default set
leaves out the two places an attempt task must write: the worktree's shared
**git common dir** (a linked worktree commits into `<top>/.git`, not into its own
folder) and the run's **TMPDIR** root — wherever it is, since (Task 2.6 live
proof) `/tmp` is not in the default set either, and an unset `TMPDIR` leaves the
child no writable temp dir at all, so `prepare` names one. `merge_settings` grants both by
merging the sandbox block into `<worktree>/.claude/settings.local.json` —
project-local settings, so no second `--settings` flag is needed and a launcher
that adds its own cannot drop it.

An existing file is **merged, never replaced**: other keys and other `sandbox`
keys stay, and the allowed-domain / write-path lists are unioned with existing
entries first. A file that does not parse is left byte-for-byte untouched and
reported, because a half-understood settings file is a child that launches with
someone's policy silently dropped. The write is atomic (temp file in the same
dir, then `os.replace`), and the file is kept out of `git status` by appending
the path once to the repo's `info/exclude` unless git already ignores it.

`sandbox.filesystem.denyWrite` re-closes what granting the common dir re-opens:
`<common>/hooks` and `<common>/config` are reachable from a sandboxed Bash (the
Edit/Write denies do not bind Bash), so both are denied. Stdlib only; every git
call runs with the repo-local git env scrubbed (`task_scope._git_env`), so a
hook-exported `GIT_DIR` can never point this at the committing repo.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import task_scope  # the shipped git-env scrub (`git_env` is dev-only, never ships)

SETTINGS_RELPATH = ".claude/settings.local.json"
GIT_TIMEOUT_S = 10

# §B1: the PyPI hosts the sandboxed child may reach (install + test only).
PYPI_HOSTS = ["pypi.org", "files.pythonhosted.org"]

# The block's fixed part. `filesystem` is filled per worktree by `write_paths`
# and `deny_paths`; `network.allowedDomains` is the closed §B1 set.
SANDBOX_BLOCK = {
    "enabled": True,
    "failIfUnavailable": False,
    "network": {"allowedDomains": list(PYPI_HOSTS)},
    "filesystem": {"allowWrite": [], "denyWrite": []},
}


def _git(worktree, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(worktree), *args], capture_output=True,
                              text=True, timeout=GIT_TIMEOUT_S, env=task_scope._git_env())
    except (OSError, subprocess.SubprocessError):
        return None


def _rev_parse(worktree, *args: str) -> str:
    """`git rev-parse <args>` resolved to an absolute real path. "" on any failure."""
    proc = _git(worktree, "rev-parse", *args)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return ""
    raw = proc.stdout.strip()
    path = raw if os.path.isabs(raw) else os.path.join(str(worktree), raw)
    return os.path.realpath(path)


def git_common_dir(worktree) -> str:
    """The repo's git common dir (the seat's `.git` for a linked worktree). "" if none."""
    return _rev_parse(worktree, "--git-common-dir")


def _under(child: str, parent: str) -> bool:
    """True when `child` is `parent` or inside it (both already realpaths)."""
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def write_paths(worktree, env) -> list[str]:
    """The write grants the sandbox's default set is missing, in order.

    The git common dir first, then `env["TMPDIR"]` wherever it is — only skipped
    when it is unset or already inside the worktree, which the default set
    covers. `/tmp` is **not** in the default set (Task 2.6 live proof), so it
    gets a grant like any other path. Paths are realpaths: the sandbox compares
    real paths.
    """
    paths = []
    common = git_common_dir(worktree)
    if common:
        paths.append(common)
    tmpdir = str((env or {}).get("TMPDIR") or "")
    if tmpdir:
        root = os.path.realpath(tmpdir)
        if not _under(root, os.path.realpath(str(worktree))):
            paths.append(root)
    return paths


def deny_paths(worktree) -> list[str]:
    """Re-close what granting the common dir opens: its `hooks` and `config`."""
    common = git_common_dir(worktree)
    return [] if not common else [os.path.join(common, "hooks"),
                                  os.path.join(common, "config")]


def _union(existing, new: list[str]) -> list[str]:
    """`new` appended to `existing` (existing entries first, no duplicates)."""
    out = [x for x in existing if isinstance(x, str)] if isinstance(existing, list) else []
    out += [x for x in new if x not in out]
    return out


def _merged_sandbox(old, allow: list[str], deny: list[str]) -> dict:
    """`SANDBOX_BLOCK` over `old`: every other `sandbox` key kept, lists unioned."""
    sandbox = dict(old) if isinstance(old, dict) else {}
    sandbox["enabled"] = SANDBOX_BLOCK["enabled"]
    sandbox["failIfUnavailable"] = SANDBOX_BLOCK["failIfUnavailable"]
    network = dict(sandbox["network"]) if isinstance(sandbox.get("network"), dict) else {}
    network["allowedDomains"] = _union(network.get("allowedDomains"), PYPI_HOSTS)
    sandbox["network"] = network
    fs = dict(sandbox["filesystem"]) if isinstance(sandbox.get("filesystem"), dict) else {}
    fs["allowWrite"] = _union(fs.get("allowWrite"), allow)
    fs["denyWrite"] = _union(fs.get("denyWrite"), deny)
    sandbox["filesystem"] = fs
    return sandbox


def _write_atomic(path: Path, data: dict) -> str:
    """Write `data` as `path` atomically. "" on success, the reason why not."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
            os.replace(tmp, path)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except (OSError, ValueError) as exc:
        return f"cannot write {path}: {exc}"
    return ""


def _keep_out_of_git(worktree) -> None:
    """Append the settings path once to `info/exclude` unless git ignores it already."""
    proc = _git(worktree, "check-ignore", "-q", SETTINGS_RELPATH)
    if proc is not None and proc.returncode == 0:
        return
    exclude = _rev_parse(worktree, "--git-path", "info/exclude")
    if not exclude:
        return
    try:
        Path(exclude).parent.mkdir(parents=True, exist_ok=True)
        current = Path(exclude).read_text(encoding="utf-8") if os.path.exists(exclude) else ""
        if SETTINGS_RELPATH in current.splitlines():
            return
        with open(exclude, "a", encoding="utf-8") as handle:
            handle.write(("" if not current or current.endswith("\n") else "\n"))
            handle.write(SETTINGS_RELPATH + "\n")
    except OSError:
        return


def merge_settings(worktree, env=None) -> tuple[bool, str]:
    """Merge the sandbox block into `<worktree>/.claude/settings.local.json`.

    `env=None` means `os.environ` (Task 2.2 passes its own env through, so a
    run's `TMPDIR` is never dropped). Returns `(True, "")` once the file holds
    the block, else `(False, why)` — an existing file that does not parse is
    left untouched rather than replaced.
    """
    env = os.environ if env is None else env
    path = Path(str(worktree)) / SETTINGS_RELPATH
    data: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return False, f"{path} is not readable settings JSON: {exc}"
        if not isinstance(loaded, dict):
            return False, f"{path} holds JSON that is not an object"
        data = loaded
    data["sandbox"] = _merged_sandbox(data.get("sandbox"), write_paths(worktree, env),
                                      deny_paths(worktree))
    why = _write_atomic(path, data)
    if why:
        return False, why
    _keep_out_of_git(worktree)
    return True, ""


# --- the switch, the availability check, the per-site decision (§B2, task 2.2) ---

SWITCH_ENV = "TP_CHILD_SANDBOX"  # §B2's live-proof lever: one run, no config edit
SWITCH_VALUES = ["off", "on"]  # the closed set §B2 names; anything else is `"off"` + a warning
SANDBOX_SITES = ["S1"]  # §B1: only the task worker's `--cwd` is an attempt worktree
SANDBOX_TOOLS = ["bwrap", "socat"]  # bubblewrap plus its socket relay; both must exist


def _configured(config) -> str:
    """`config["strata_spawn"]["sandbox"]` when it is a known value, else `""`."""
    section = (config or {}).get("strata_spawn") if isinstance(config, dict) else None
    value = section.get("sandbox") if isinstance(section, dict) else None
    return value if value in SWITCH_VALUES else ""


def switch(config, env: dict | None = None) -> str:
    """`"on"` / `"off"` — `env[TP_CHILD_SANDBOX]` wins, else config, else `"off"`.

    Shipped default is `"off"`: a repo opts in by setting `strata_spawn.sandbox` to
    `"on"`. An unusable env value is ignored (the config still answers); an unusable
    config value is `"off"` — `switch_warnings` says so once. `env=None` reads
    `os.environ`.
    """
    env = os.environ if env is None else env
    override = str((env or {}).get(SWITCH_ENV) or "")
    return override if override in SWITCH_VALUES else (_configured(config) or "off")


def switch_warnings(config, env: dict | None = None) -> list[str]:
    """One `W:` line when the config names a value that is neither `"on"` nor `"off"`."""
    section = (config or {}).get("strata_spawn") if isinstance(config, dict) else None
    value = section.get("sandbox") if isinstance(section, dict) else None
    if value is None or value in SWITCH_VALUES:
        return []
    return [f'W: strata_spawn.sandbox: "{value}" is not "on" or "off" — using "off"']


def available(which=shutil.which, platform=sys.platform) -> tuple[bool, str]:
    """Can the Bash sandbox run here? `(True, "")` or `(False, why)` — first miss wins."""
    if str(platform).startswith("win"):
        return False, "windows"
    for tool in SANDBOX_TOOLS:
        if not which(tool):
            return False, "no " + tool
    return True, ""


def prepare(cwd, site: str, config, env: dict | None = None) -> tuple[str, list[str]]:
    """Merge the block for `cwd` when this launch is sandboxed; `(state, warnings)`.

    Called by `cmd_start` just before the launch. States: `"off"` (switch off — no
    file, no warning), `"skipped"` (on, but a site whose cwd is not an attempt
    worktree), `"unavailable"` (on + S1 + `available()` says no: no file, one `W:`
    line naming the deny list as the only fence — the child runs unsandboxed),
    `"failed"` (the merge itself failed: no crash, one `W:` line with the reason),
    `"sandboxed"` (the file holds the block). `available` is looked up at call time
    so a test can monkeypatch this module's name. On the sandboxed path only, and
    before the merge, `env` gets a `TMPDIR` when it has none — the realpath of
    `tempfile.gettempdir()` — so that path is granted *and* the child inherits it:
    `cmd_start` passes `os.environ` here and builds the child's env from the same
    mapping right after. An unset `TMPDIR` with no grant is what left the live-proof
    child no writable temp dir (Task 2.6). `env` is untouched on every other path.
    """
    env = os.environ if env is None else env
    warns = switch_warnings(config, env)
    if switch(config, env) == "off":
        return "off", warns
    if site not in SANDBOX_SITES:
        return "skipped", warns
    ok, why = available()
    if not ok:
        return "unavailable", warns + [
            f"W: sandbox unavailable ({why}); the deny list is the only fence"]
    env.setdefault("TMPDIR", os.path.realpath(tempfile.gettempdir()))
    ok, why = merge_settings(cwd, env)
    if not ok:
        return "failed", warns + [
            f"W: sandbox merge failed ({why}); the deny list is the only fence"]
    return "sandboxed", warns
