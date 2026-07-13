"""aider_install_check.py — per-user state for the optional aider install prompt.

Mirrors `branch_protection_check.py` in shape:
- Cheap-path early-exit on a populated state file.
- Atomic JSON write under `~/.three-pillars/` (or `$XDG_CONFIG_HOME/three-pillars/`
  when set).
- One-shot decisions stick — sticky decline never re-prompts; `remind_later`
  schedules a future re-fire.

Schema (per design.md Experiment 4):

  {
    "offered_at":    str | None,  # ISO8601 UTC — when the user first saw the prompt
    "decided":       bool,        # True once the user picked install/decline
    "installed_via": str | None,  # "uv-tool" | "pipx" | "project-venv:<path>" | "manual"
    "declined":      bool,        # sticky — True means no further prompts
    "remind_after":  str | None   # ISO8601 UTC — re-fire prompt only after this time
  }

UX-state interpretation table:

  | decided | declined | installed_via | remind_after  | meaning                       |
  |---------|----------|---------------|---------------|-------------------------------|
  | True    | False    | "<installer>" | None          | accepted + installed          |
  | True    | True     | None          | None          | declined (sticky)             |
  | False   | False    | None          | "<timestamp>" | remind-later, prompt fires    |
  |         |          |               |               | again after timestamp passes  |
  | False   | False    | None          | None          | never offered (fresh state)   |

The helper is dependency-free (stdlib only). Public callers:

  - skills/_shared/first-run.md (the preflight integration in design.md
    Experiment 1 — calls `cheap_check()` on every tp-* skill invocation)
  - the agent body of the first-run prompt branch (calls `mark_offered()`,
    `mark_installed()`, `mark_declined()`, `mark_remind_later()`)

This is the first per-user (not per-repo) state file in three-pillars. The
per-repo config lives at `<repo>/.three-pillars/config.json`; this lives at
`~/.three-pillars/aider-install.json` (XDG-respecting). Co-locating them under
the same directory name keeps the convention readable: anything under
`.three-pillars/` is three-pillars state.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


_REMIND_DEFAULT_DAYS = 7


@dataclass
class State:
    offered_at: Optional[str] = None
    decided: bool = False
    installed_via: Optional[str] = None
    declined: bool = False
    remind_after: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "offered_at": self.offered_at,
            "decided": self.decided,
            "installed_via": self.installed_via,
            "declined": self.declined,
            "remind_after": self.remind_after,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "State":
        return cls(
            offered_at=data.get("offered_at"),
            decided=bool(data.get("decided", False)),
            installed_via=data.get("installed_via"),
            declined=bool(data.get("declined", False)),
            remind_after=data.get("remind_after"),
        )


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def state_file_path() -> Path:
    """Resolve the per-user state file path.

    Honors `$XDG_CONFIG_HOME` when set: `$XDG_CONFIG_HOME/three-pillars/aider-install.json`.
    Otherwise: `~/.three-pillars/aider-install.json`.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "three-pillars" / "aider-install.json"
    return Path.home() / ".three-pillars" / "aider-install.json"


def read(path: Optional[Path] = None) -> State:
    """Read state from disk. Returns a fresh State if the file does not exist."""
    target = path or state_file_path()
    if not target.exists():
        return State()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Corrupt file → treat as missing. Don't try to repair silently — next
        # write will overwrite cleanly.
        return State()
    return State.from_dict(data)


def write(state: State, path: Optional[Path] = None) -> None:
    """Atomic write of state to disk."""
    target = path or state_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=target.parent,
        prefix=".aider-install.",
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(state.to_dict(), tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, target)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


@dataclass
class CheapCheck:
    """What the cheap-path check decided.

    `action`: one of "skip-decided", "skip-remind-pending", "needs-prompt",
              "needs-prompt-remind-elapsed".
    `state`: the loaded state (useful for the prompt branch).
    """

    action: str
    state: State


def cheap_check(path: Optional[Path] = None) -> CheapCheck:
    """Hot-path check: should the install prompt fire?

    Single file read + JSON parse. Returns "skip-*" actions for the
    steady-state cases (decided or remind-pending) — the caller proceeds
    immediately. Returns "needs-prompt*" when the prompt branch should fire.
    """
    state = read(path)
    if state.decided:
        return CheapCheck(action="skip-decided", state=state)
    if state.remind_after:
        try:
            when = _parse_iso_utc(state.remind_after)
        except ValueError:
            # Corrupt timestamp — treat as elapsed so the prompt re-fires
            # rather than silently sticking forever.
            return CheapCheck(action="needs-prompt-remind-elapsed", state=state)
        if datetime.now(timezone.utc) < when:
            return CheapCheck(action="skip-remind-pending", state=state)
        return CheapCheck(action="needs-prompt-remind-elapsed", state=state)
    return CheapCheck(action="needs-prompt", state=state)


def mark_offered(path: Optional[Path] = None) -> State:
    """Record that the prompt was shown. Caller still needs to capture the choice."""
    state = read(path)
    if state.offered_at is None:
        state.offered_at = _now_iso_utc()
    write(state, path)
    return state


def mark_installed(via: str, path: Optional[Path] = None) -> State:
    """Record an accepted install. `via` identifies the installer (e.g. "uv-tool")."""
    state = read(path)
    state.decided = True
    state.declined = False
    state.installed_via = via
    state.remind_after = None
    if state.offered_at is None:
        state.offered_at = _now_iso_utc()
    write(state, path)
    return state


def mark_declined(path: Optional[Path] = None) -> State:
    """Sticky decline — no further prompts will fire."""
    state = read(path)
    state.decided = True
    state.declined = True
    state.installed_via = None
    state.remind_after = None
    if state.offered_at is None:
        state.offered_at = _now_iso_utc()
    write(state, path)
    return state


def mark_remind_later(
    days: int = _REMIND_DEFAULT_DAYS, path: Optional[Path] = None
) -> State:
    """Defer the decision. Prompt re-fires after `days` have elapsed."""
    state = read(path)
    state.decided = False
    state.declined = False
    state.installed_via = None
    future = datetime.now(timezone.utc) + timedelta(days=days)
    state.remind_after = future.strftime("%Y-%m-%dT%H:%M:%SZ")
    if state.offered_at is None:
        state.offered_at = _now_iso_utc()
    write(state, path)
    return state


def detect_project_venv(repo_root: Path) -> Optional[Path]:
    """Probe `repo_root` for a usable project-local virtualenv.

    Returns the venv root path when `.venv/bin/python` or `venv/bin/python`
    exists, else None. Intentionally narrow — does not branch on uv / poetry /
    pipenv / pyenv-virtualenv tool detection (see plan.md Task 1.2 for the
    scope-narrowing rationale).
    """
    for name in (".venv", "venv"):
        candidate = repo_root / name
        if (candidate / "bin" / "python").exists():
            return candidate
    return None


def aider_on_path() -> bool:
    """True iff `aider` is callable from PATH."""
    return shutil.which("aider") is not None


def install_user_level() -> tuple[str, str]:
    """Try `uv tool install aider-chat` then `pipx install aider-chat`.

    Returns (installer, outcome) where installer is "uv-tool" | "pipx" | "manual"
    and outcome is "installed" or a fallback marker like "manual-print" when both
    installers are missing.
    """
    for installer, cmd in (
        ("uv-tool", ["uv", "tool", "install", "aider-chat"]),
        ("pipx", ["pipx", "install", "aider-chat"]),
    ):
        binary = installer.split("-", 1)[0]  # "uv" or "pipx"
        if shutil.which(binary) is None:
            continue
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return installer, "installed"
        # Try the next installer if this one was present but failed.
        continue
    return "manual", "manual-print"


def install_project_venv(venv_path: Path) -> tuple[str, str]:
    """Install aider into the venv at `venv_path` using its bundled pip.

    Returns ("project-venv:<relative-name>", outcome) where outcome is
    "installed" or "failed". No shell activation required — `<venv>/bin/pip`
    writes to the venv's site-packages directly.
    """
    pip = venv_path / "bin" / "pip"
    if not pip.exists():
        return f"project-venv:{venv_path.name}", "failed"
    result = subprocess.run(
        [str(pip), "install", "aider-chat"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return f"project-venv:{venv_path.name}", "installed"
    return f"project-venv:{venv_path.name}", "failed"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Aider install state helper.")
    parser.add_argument(
        "action",
        choices=[
            "read",
            "cheap-check",
            "mark-offered",
            "mark-installed",
            "mark-declined",
            "mark-remind-later",
            "detect-venv",
            "path",
        ],
        help="Operation to perform.",
    )
    parser.add_argument("--via", default=None, help="Installer tag for mark-installed.")
    parser.add_argument("--days", type=int, default=_REMIND_DEFAULT_DAYS)
    parser.add_argument("--repo", default=".", help="Repo root for detect-venv.")
    parser.add_argument(
        "--state-file",
        default=None,
        help="Override state file path (testing).",
    )
    args = parser.parse_args()
    path = Path(args.state_file).expanduser() if args.state_file else None

    if args.action == "read":
        print(json.dumps(read(path).to_dict(), indent=2, sort_keys=True))
    elif args.action == "cheap-check":
        result = cheap_check(path)
        print(json.dumps({"action": result.action, "state": result.state.to_dict()}, indent=2, sort_keys=True))
    elif args.action == "mark-offered":
        print(json.dumps(mark_offered(path).to_dict(), indent=2, sort_keys=True))
    elif args.action == "mark-installed":
        if args.via is None:
            parser.error("--via is required for mark-installed")
        print(json.dumps(mark_installed(args.via, path).to_dict(), indent=2, sort_keys=True))
    elif args.action == "mark-declined":
        print(json.dumps(mark_declined(path).to_dict(), indent=2, sort_keys=True))
    elif args.action == "mark-remind-later":
        print(json.dumps(mark_remind_later(args.days, path).to_dict(), indent=2, sort_keys=True))
    elif args.action == "detect-venv":
        venv = detect_project_venv(Path(args.repo).resolve())
        print(json.dumps({"venv": str(venv) if venv else None}, indent=2))
    elif args.action == "path":
        print(state_file_path())
