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
order. Each `M?` becomes a placeholder ID `M-new-<slug>`, never a number: the
numbering pass (`number_issues.py`) assigns the number at landing, per
`issue-id-placeholders.md`, so two branches never pick the same one (L162).
`<slug>` is `cert-` plus the kebab-cased claim key (`sweep-01#s2` →
`cert-sweep-01-s2`), suffixed `-2`, `-3`, … when that placeholder is already
headed in `known_issues.md` ∪ `known_issues_low.md` ∪ `known_issues_resolved.md` (the
`ISSUE_ID_DOCS` siblings) or earlier in the batch. An entry whose key is already filed in
any of them is skipped, so a re-run applies nothing twice.

`LIVE_ISSUE_DOCS` / `ISSUE_ID_DOCS` / `COLD_ISSUE_DOCS` are the shared issue-doc tuples
(design: skill-context-diet D5b): ID readers read `ISSUE_ID_DOCS`; the cold
`known_issues_archive.md` holds demoted bodies and is never read for IDs.
"""
from __future__ import annotations

import re
from pathlib import Path

PENDING_MARK = "<!-- certification known-issues pending v1 -->"
PLACEHOLDER = "M?"
SWEEP_MISS = ("not-binding", "false-red")
SELF_OK = ("binds", "known-bypass")
MEDIUM = "## Medium"
_DOCS = "three-pillars-docs/"
LIVE_ISSUE_DOCS = (_DOCS + "known_issues.md", _DOCS + "known_issues_low.md")
ISSUE_ID_DOCS = LIVE_ISSUE_DOCS + (_DOCS + "known_issues_resolved.md",)
COLD_ISSUE_DOCS = (_DOCS + "known_issues_resolved.md", _DOCS + "known_issues_archive.md")
_KEY_RE = re.compile(r"\[certification ([^\]\s]+#[^\]\s]+)\]")
_M_NEW_RE = re.compile(r"^###\s+(M-new-[a-z0-9]+(?:-[a-z0-9]+)*)(?=[ \t:(])", re.MULTILINE)
_NON_SLUG = re.compile(r"[^a-z0-9]+")
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


def placeholder_id(key: str, taken: set) -> str:
    """`M-new-cert-<kebab key>`, suffixed `-2`, `-3`, … until it is not in `taken`."""
    base = "M-new-" + "-".join(filter(None, ["cert", _NON_SLUG.sub("-", key.lower()).strip("-")]))
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def apply(pending: str, known_issues, resolved=None) -> list[str]:
    """Insert the pending entries under `## Medium`; return the placeholder ids filed."""
    known_issues = Path(known_issues)
    resolved = Path(resolved) if resolved else known_issues.parent / "known_issues_resolved.md"
    low = known_issues.parent / Path(LIVE_ISSUE_DOCS[1]).name
    text = _read(known_issues)
    archive = _read(resolved) + "\n" + _read(low)  # every other ID doc: dedupe only
    lines = text.splitlines(keepends=True)
    at = next((i for i, ln in enumerate(lines) if ln.rstrip() == MEDIUM), None)
    if at is None:
        raise ValueError(f"{known_issues}: no '{MEDIUM}' section to file into")
    filed = set(keys_in(text)) | set(keys_in(archive))
    taken = set(_M_NEW_RE.findall(text)) | set(_M_NEW_RE.findall(archive))
    ids, blocks = [], []
    for block in _entries(pending):
        keys = keys_in(block.splitlines()[0])
        if not keys or keys[0] in filed:
            continue
        pid = placeholder_id(keys[0], taken)
        ids.append(pid)
        blocks.append(block.replace(f"### {PLACEHOLDER}:", f"### {pid}:", 1) + "\n")
        filed.add(keys[0])
        taken.add(pid)
    if not blocks:
        return []
    insert = at + 1
    while insert < len(lines) and not lines[insert].strip():
        insert += 1
    head = lines[:at + 1] + ["\n"]
    known_issues.write_text("".join(head + blocks + lines[insert:]), encoding="utf-8")
    return ids
