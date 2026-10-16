"""Failure classes and fingerprints for the escalation ladder (stdlib only)."""
import posixpath
import re

import red_commit_gate

_SIZE = r"file-size-guard|inv #34"
_FIXTURE = r"fixture '[^']+' not found|FileNotFoundError: .*fixtures?/"

# Data, first match wins. field: reason | tail | row (row-aware, see _row_match).
CLASSES: tuple[dict, ...] = (
    {"name": "size-split", "field": "tail", "pattern": _SIZE, "target": "opus-medium"},
    {"name": "size-split", "field": "row", "pattern": r"^unlisted file: ", "target": "opus-medium"},
    {"name": "unlisted-file", "field": "reason", "pattern": r"^unlisted file: ", "target": "opus-medium"},
    {"name": "out-of-scope-pin", "field": "row", "pattern": r"FAILED (\S+)", "target": "opus-medium"},
    {"name": "missing-fixture", "field": "tail", "pattern": _FIXTURE, "target": "opus-medium"},
    {"name": "no-oracle", "field": "reason", "pattern": r"^no oracle", "target": "opus-medium"},
    # A call the child's permission lists refused is matched by _refused() before this scan (so it
    # outranks size-split); the row is here so target_for resolves it. Never a same-rung retry —
    # the same lists would refuse it again — so the target is the in-process rung above.
    {"name": "permission-refused", "field": "flag", "pattern": r"^permission-refused: ",
     "target": "sonnet-medium"},
)


def normalize(reason: str) -> str:
    m = re.match(r"runaway: (wall-clock|generation)", reason)
    if m:
        return f"runaway: {m.group(1)}"
    if reason.startswith("runaway"):
        return "runaway"
    s = re.sub(r"(?<![0-9a-zA-Z])[0-9a-f]{7,40}(?![0-9a-zA-Z])", "<sha>", reason)
    s = re.sub(r"(?:/tmp|/var/folders|/private/tmp)/\S*", "<tmp>", s)
    return re.sub(r"\d+ commits?", "N commits", s)


def _targets(row: dict) -> set[str]:
    specs = (row.get("test") or {}).get("specs") or []
    return {*(row.get("files") or []), *specs}


def _row_match(c: dict, reason: str, tail: str, row: dict | None) -> bool:
    if not row:
        return False
    if c["name"] == "size-split":  # unlisted new file next to a listed one
        if not re.search(c["pattern"], reason):
            return False
        p = reason.split(": ", 1)[1].strip()
        d, stem = posixpath.dirname(p), posixpath.splitext(posixpath.basename(p))[0]
        return any(posixpath.dirname(f) == d
                   and stem.startswith(posixpath.splitext(posixpath.basename(f))[0])
                   for f in row.get("files") or [])
    ids = re.findall(c["pattern"], tail)  # out-of-scope-pin
    tg = _targets(row)
    paths = {t.split("::")[0] for t in tg}
    return any(i not in tg and i.split("::")[0] not in paths for i in ids)


_REFUSED = "permission-refused: "

# Bare file-editing tools the child already holds through its worktree `Edit(//<wt>/**)` rule
# (child_permissions._worktree_rules covers every file-editing tool). A refusal of one of these is
# the open inner-agent Write/Edit denial (b2-proof), not a rule the lists lack: there is no allow
# rule to add, the worker falls back to a Bash heredoc, and a same-rung retry is productive. The
# flag stays in ev["flags"] (logged in the [tier] entry); it just never picks the class.
GRANTED_FILE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def _refused(flags) -> bool:
    """Any `permission-refused: <rule>` flag (Task 1.5's reply banner, read by build_evidence)
    whose rule is not a bare file-editing tool the child holds anyway (`GRANTED_FILE_TOOLS`)."""
    return any(str(f).startswith(_REFUSED) and str(f)[len(_REFUSED):].strip() not in GRANTED_FILE_TOOLS
               for f in flags or [])


# The watchdog's fast catch (hook_refusal_scan): `runaway: hook-refused: <hook tail>`.
HOOK_REFUSED_REASON = "runaway: hook-refused: "
HOOK_REFUSED = "hook-refused"


def hook_refused_reason(reason: str, hook_tail: str = "") -> str:
    """The verdict reason of a `hook-refused` task: `hook-refused: ` + the hook tail (the rest of a
    `runaway: hook-refused: ` reason, else `hook_tail`), whitespace collapsed, last 300 chars."""
    body = reason[len(HOOK_REFUSED_REASON):] if reason.startswith(HOOK_REFUSED_REASON) else hook_tail
    return f"{HOOK_REFUSED}: " + re.sub(r"\s+", " ", str(body)).strip()[-300:]


def classify(outcome: str, reason: str, *, hook_tail: str = "", row: dict | None = None,
             flags: list | None = None, first_commit: bool = False) -> str:
    if outcome in ("PASS", "PASS-unverified"):
        return "pass"
    if outcome == "env-error":
        return "env"
    if outcome == "unavailable":
        return "unavailable"
    if reason.startswith(HOOK_REFUSED_REASON):  # before the generic runaway: the tail classes first
        rest = reason[len(HOOK_REFUSED_REASON):]
        return next((f"deterministic:{c['name']}" for c in CLASSES
                     if c["field"] == "tail" and re.search(c["pattern"], rest)), HOOK_REFUSED)
    if re.match(r"runaway: ", reason):
        return "runaway"
    if _refused(flags):  # before the scan: a refused call outranks size-split
        return "deterministic:permission-refused"
    hook = outcome == "hook-failed"
    for c in CLASSES:
        f = c["field"]
        if f == "flag":  # decided by _refused() above, never by the hook tail or row scan
            continue
        if f == "reason":
            hit = re.search(c["pattern"], reason)
        elif f == "tail":
            hit = re.search(c["pattern"], hook_tail)
        else:  # row-based classes fire on a hook failure, or an unlisted reason
            hit = _row_match(c, reason, hook_tail, row) and (hook or c["name"] == "size-split")
        if hit:
            return f"deterministic:{c['name']}"
    if hook and first_commit and red_commit_gate.failing_paths(hook_tail):
        return HOOK_REFUSED  # a test hook refused the attempt's first (Red) commit; no class fixed it
    return "quality"


def fingerprint(outcome: str, reason: str, failing: list[str]) -> str:
    return f"{classify(outcome, reason)}|{','.join(sorted(failing))}|{normalize(reason)}"


def target_for(klass: str) -> str | None:
    if klass.startswith("deterministic:"):
        name = klass.split(":", 1)[1]
        for c in CLASSES:
            if c["name"] == name:
                return c["target"]
    return None
