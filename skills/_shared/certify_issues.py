"""certify_issues — file certification misses as known issues (`issues render` / `apply`).

design: audit-pass-does-not-bind (Task 9.4; detailed-design.md §Interfaces [B]). Shipped;
reached through `certify_ledger.py issues …` (resolved like every shared script).

`render(results, self_result)` returns the pending list: one `### M?:` entry per
`not-binding` / `false-red` claim of a ledger result, and one per self claim
whose status is not `binds` / `known-bypass`, so an unmet self-certification is
filed rather than silent. Each heading carries its key `[certification
<name>#<id>]` (`name` = the result's `name` less any `.claims.json`, e.g. `sweep-01`
or `self`: the certify-sweep runbook names results `sweep-01.claims.json`).

`apply(pending, known_issues, resolved)` inserts the entries directly under
`## Medium` in `known_issues.md`, above the first existing entry, in pending
order. Each `M?` becomes the next free Medium id, re-derived at apply time over
the `### M<n>` headings of `known_issues.md` ∪ `known_issues_resolved.md`, so
an id allocated by anyone since `render` is never reused. An entry whose key is
already filed in either file is skipped, so a re-run applies nothing twice.
"""
from __future__ import annotations

import re
from pathlib import Path

PENDING_MARK = "<!-- certification known-issues pending v1 -->"
PLACEHOLDER = "M?"
SWEEP_MISS = ("not-binding", "false-red")
SELF_OK = ("binds", "known-bypass")
MEDIUM = "## Medium"
_KEY_RE = re.compile(r"\[certification ([^\]\s]+#[^\]\s]+)\]")
_M_RE = re.compile(r"^###\s+M(\d+)\b", re.MULTILINE)
TAIL_MAX = 300
CLAIMS_SUFFIX = ".claims.json"


def stem(name) -> str:
    """A result's key name: its `name` without a trailing `.claims.json`."""
    name = str(name)
    return name[:-len(CLAIMS_SUFFIX)] if name.endswith(CLAIMS_SUFFIX) else name


def _entry_text(name: str, entry: dict, *, self_row: bool) -> str:
    key = f"{name}#{entry.get('id')}"
    status = entry.get("status")
    guard = entry.get("guard") or "(unknown guard)"
    what = "self-certification unmet" if self_row else f"guard {status}"
    reasons = ", ".join(entry.get("reasons") or []) or "none"
    red = (entry.get("evidence") or {}).get("red") or []
    tail = " ".join(str(red[0].get("tail", "")).split())[-TAIL_MAX:] if red else ""
    lines = [
        f"### {PLACEHOLDER}: certification {what} — `{guard}` [certification {key}]",
        "",
        f"**Found by**: `certify.py run` over `{name}.claims.json`, claim `{entry.get('id')}`: "
        f"status `{status}`, reasons `{reasons}`.",
    ]
    if tail:
        lines.append(f"**RED evidence (tail)**: `{tail}`")
    lines.append("**Fix**: repair the guard (or its record) until it certifies `binds`; this "
                 "entry is filed, not fixed, by the certification run.")
    return "\n".join(lines) + "\n"


def render(results: list[dict], self_result: dict | None) -> str:
    """The pending known-issues list for `results` (ledger) and `self_result`."""
    blocks = []
    for res in results:
        for entry in res.get("claims") or []:
            if entry.get("status") in SWEEP_MISS:
                blocks.append(_entry_text(stem(res.get("name")), entry, self_row=False))
    if self_result is not None:
        for entry in self_result.get("claims") or []:
            if entry.get("status") not in SELF_OK:
                blocks.append(_entry_text(stem(self_result.get("name")), entry, self_row=True))
    return PENDING_MARK + "\n\n" + "\n".join(blocks)


def keys_in(text: str) -> list[str]:
    """Every `[certification <name>#<id>]` key in `text`, in order."""
    return _KEY_RE.findall(text or "")


def _entries(pending: str) -> list[str]:
    """The `### ` blocks of a pending list, each ending in one newline."""
    parts = re.split(r"(?m)^(?=### )", pending)
    return [p.rstrip("\n") + "\n" for p in parts if p.startswith("### ")]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def next_free(*texts: str) -> int:
    """One past the highest `### M<n>` heading across `texts`."""
    return max((int(n) for t in texts for n in _M_RE.findall(t)), default=0) + 1


def apply(pending: str, known_issues, resolved=None) -> list[str]:
    """Insert the pending entries under `## Medium`; return the ids assigned."""
    known_issues = Path(known_issues)
    resolved = Path(resolved) if resolved else known_issues.parent / "known_issues_resolved.md"
    text, archive = _read(known_issues), _read(resolved)
    lines = text.splitlines(keepends=True)
    at = next((i for i, ln in enumerate(lines) if ln.rstrip() == MEDIUM), None)
    if at is None:
        raise ValueError(f"{known_issues}: no '{MEDIUM}' section to file into")
    filed = set(keys_in(text)) | set(keys_in(archive))
    ids, blocks, n = [], [], next_free(text, archive)
    for block in _entries(pending):
        keys = keys_in(block.splitlines()[0])
        if not keys or keys[0] in filed:
            continue
        ids.append(f"M{n}")
        blocks.append(block.replace(f"### {PLACEHOLDER}:", f"### M{n}:", 1) + "\n")
        filed.add(keys[0])
        n += 1
    if not blocks:
        return []
    insert = at + 1
    while insert < len(lines) and not lines[insert].strip():
        insert += 1
    head = lines[:at + 1] + ["\n"]
    known_issues.write_text("".join(head + blocks + lines[insert:]), encoding="utf-8")
    return ids
