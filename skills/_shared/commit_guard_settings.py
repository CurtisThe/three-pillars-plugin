"""commit_guard_settings.py — the commit guard's shared foundation (H2 / S1).

The pieces `commit_guard` and `commit_guard_hooks` both need, held here so
neither imports the other: the `Refused` exception (carrying the cause and
the two manual snippets), the guard's constants (`BODY_VERSION`,
`HOOK_NAMES`, the sentinel regex), the per-clone marker paths under the git
common dir, and the block/snippet builders. Plus the S1 `--no-verify` deny
merge into `.claude/settings.json` (part E §`deny_no_verify=True` (S1)).

Stdlib plus `bootstrap_immunization._hooks_dir` (function-local); no import
of `commit_guard` or `commit_guard_hooks`, so either may import this module.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

# Bumped with every change to hooks/tp-commit-guard.sh. test_commit_guard.py
# pins the file's sha256 against BODY_SHA256, so an unversioned body edit
# fails (part E §sentinel body).
BODY_VERSION = 1
BODY_SHA256 = "93c4ed095f97a519b8cc5aeb0de8d9ccaf59495ac022ed890c29b13944ada6ba"

HOOK_NAMES = ("pre-commit", "commit-msg")
_GUARD_SCRIPT = Path(__file__).resolve().parent / "hooks" / "tp-commit-guard.sh"
_SENTINEL_BEGIN_RE = re.compile(r"^# three-pillars: commit-guard BEGIN v?(\d*)\s*$")
_SENTINEL_END = "# three-pillars: commit-guard END"


class Refused(Exception):
    """A hook in this repo refused the guard.

    Carries the human-readable `cause` and the two `snippets` (one for
    `pre-commit`, one for `commit-msg`, each the exact lines to add by hand);
    `apply` writes nothing before raising and the CLI exits 3 with the cause
    and the snippets.
    """

    def __init__(self, cause: str, snippets: tuple = ()):
        self.cause = cause
        self.snippets = snippets
        super().__init__(cause)


def _git(repo, *args) -> str | None:
    """`git <args>` in `repo`; the stripped stdout, or None on non-zero exit."""
    proc = subprocess.run(["git", *args], cwd=str(repo),
                          capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip()


def _common_dir(repo) -> Path | None:
    """`git rev-parse --path-format=absolute --git-common-dir`, or None."""
    out = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(out) if out else None


def _hooks_dir(repo) -> Path | None:
    """The hooks dir git consults — ``bootstrap_immunization._hooks_dir``
    (``git rev-parse --git-path hooks``: honours ``core.hooksPath`` and the
    common dir), made absolute; None when git cannot say."""
    from bootstrap_immunization import _hooks_dir as resolve  # noqa: PLC0415
    found = resolve(Path(repo))
    return Path(os.path.abspath(found)) if found else None


def manual_marker(repo) -> Path:
    """The per-clone refusal marker (part E §Refusals):
    `<git-common-dir>/three-pillars/commit-guard-manual`."""
    return _common_dir(repo) / "three-pillars" / "commit-guard-manual"


def declined_marker(repo) -> Path:
    """The per-clone decline marker (part E §CLI):
    `<git-common-dir>/three-pillars/commit-guard-declined`."""
    return _common_dir(repo) / "three-pillars" / "commit-guard-declined"


def block_lines(hook_name: str) -> list:
    """The full sentinel block for `hook_name`: BEGIN, the pinned body, the
    call line, END."""
    begin = f"# three-pillars: commit-guard BEGIN v{BODY_VERSION}"
    body = _GUARD_SCRIPT.read_text(encoding="utf-8").splitlines()
    call = f'_tp_commit_guard {hook_name} "$@" || exit $?'
    return [begin, *body, call, _SENTINEL_END]


def snippets_for(cause: str) -> tuple:
    """The two manual snippets (part E §Refusals), one per hook: the exact
    lines to add by hand right after the hook's shebang — the whole sentinel
    block with its call line, so a later ``apply`` finds it and records
    ``applied_at``."""
    return tuple(f"# {name}: {cause}\n" + "\n".join(block_lines(name)) + "\n"
                 for name in HOOK_NAMES)


SETTINGS_REL = Path(".claude") / "settings.json"

# The exact rules S1 denies, in canonical order.
DENY_RULES = (
    "Bash(git commit --no-verify:*)",
    "Bash(git commit -n:*)",
)


def _merge_into_deny(deny: object) -> list:
    """The new `deny` list: every user entry first (order and values intact),
    then each missing rule in canonical order. A non-list value is treated
    as absent."""
    kept = list(deny) if isinstance(deny, list) else []
    return kept + [rule for rule in DENY_RULES if rule not in kept]


def merge_deny(repo) -> list:
    """Merge `DENY_RULES` into `<repo>/.claude/settings.json`
    `permissions.deny` and return the resulting list.

    Absent file or absent keys: created with the two rules. Existing user
    entries — deny, allow, or any other top-level key — are never touched.
    Idempotent: a second call leaves the file byte-identical.
    """
    root = Path(repo)
    path = root / SETTINGS_REL
    data: dict = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{SETTINGS_REL} is not a JSON object")
    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    deny = _merge_into_deny(permissions.get("deny"))
    permissions["deny"] = deny
    data["permissions"] = permissions

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
    return deny
