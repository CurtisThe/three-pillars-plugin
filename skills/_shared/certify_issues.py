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

`apply_to_fragment(pending, fragment, known_issues)` (design: living-doc-fragments 1.12) files the same
entries, under the same placeholders and claim-key dedupe, into the design's fragment
`three-pillars-docs/changes/<slug>.md` under `## Known issues — add` instead, after the blocks already
there; a design branch never edits a living doc, so the docs next to `known_issues` are only read (for the
keys and placeholders already filed). A fragment that is absent or empty gains its frontmatter first
(`slug` = the file stem, `kind: design`, today), and a fragment without the section gains it at the end.
Nothing new to file leaves the fragment untouched.

`LIVE_ISSUE_DOCS` / `ISSUE_ID_DOCS` / `COLD_ISSUE_DOCS` are the shared issue-doc tuples
(design: skill-context-diet D5b): ID readers read `ISSUE_ID_DOCS`; the cold
`known_issues_archive.md` holds demoted bodies and is never read for IDs.
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import low_doc_parts  # noqa: E402  (the one list of the Low-doc parts)

PENDING_MARK = "<!-- certification known-issues pending v1 -->"
PLACEHOLDER = "M?"
SWEEP_MISS = ("not-binding", "false-red")
SELF_OK = ("binds", "known-bypass")
MEDIUM = "## Medium"
FRAGMENT_ADD = "## Known issues — add"
_DOCS = "three-pillars-docs/"
# Part 1 plus every numbered Low part (design: basesync-count-line-and-low-headroom 2.1).
# A repo with no Low doc still resolves none of them, so it behaves exactly as before.
LIVE_ISSUE_DOCS = (_DOCS + "known_issues.md", *low_doc_parts.PART_RELS)
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


def _mint(pending: str, filed: set, taken: set) -> tuple[list[str], list[str]]:
    """The (placeholder ids, blocks) `pending` adds over the claim keys `filed` and ids `taken`."""
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
    return ids, blocks


def apply(pending: str, known_issues, resolved=None) -> list[str]:
    """Insert the pending entries under `## Medium`; return the placeholder ids filed."""
    known_issues = Path(known_issues)
    resolved = Path(resolved) if resolved else known_issues.parent / "known_issues_resolved.md"
    low = "\n".join(_read(known_issues.parent / Path(r).name)
                     for r in low_doc_parts.PART_RELS)  # every Low part, in part order
    text = _read(known_issues)
    archive = _read(resolved) + "\n" + low  # every other ID doc: dedupe only
    lines = text.splitlines(keepends=True)
    at = next((i for i, ln in enumerate(lines) if ln.rstrip() == MEDIUM), None)
    if at is None:
        raise ValueError(f"{known_issues}: no '{MEDIUM}' section to file into")
    filed = set(keys_in(text)) | set(keys_in(archive))
    taken = set(_M_NEW_RE.findall(text)) | set(_M_NEW_RE.findall(archive))
    ids, blocks = _mint(pending, filed, taken)
    if not blocks:
        return []
    insert = at + 1
    while insert < len(lines) and not lines[insert].strip():
        insert += 1
    head = lines[:at + 1] + ["\n"]
    known_issues.write_text("".join(head + blocks + lines[insert:]), encoding="utf-8")
    return ids


def _section_end(lines: list[str], start: int) -> int:
    """The index of the next `## ` heading after line `start` (outside a code fence), else the end."""
    fence = False
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("```"):
            fence = not fence
        elif not fence and lines[i].startswith("## "):
            return i
    return len(lines)


def apply_to_fragment(pending: str, fragment, known_issues) -> list[str]:
    """File the pending entries under the fragment's `## Known issues — add`; return the ids filed."""
    fragment, known_issues = Path(fragment), Path(known_issues)
    docs = "\n".join([_read(known_issues)] + [_read(known_issues.parent / Path(rel).name)
                                              for rel in ISSUE_ID_DOCS])
    text = _read(fragment)
    ids, blocks = _mint(pending, set(keys_in(docs)) | set(keys_in(text)),
                        set(_M_NEW_RE.findall(docs)) | set(_M_NEW_RE.findall(text)))
    if not blocks:
        return []
    body = "".join(blocks)
    lines = text.splitlines(keepends=True)
    at = next((i for i, ln in enumerate(lines) if ln.rstrip() == FRAGMENT_ADD), None)
    if not text.strip():
        day = datetime.date.today().isoformat()
        out = f"---\nslug: {fragment.stem}\nkind: design\ndate: {day}\n---\n\n{FRAGMENT_ADD}\n\n{body}"
    elif at is None:
        out = f"{text.rstrip(chr(10))}\n\n{FRAGMENT_ADD}\n\n{body}"
    else:
        end = _section_end(lines, at)
        while end > at + 1 and not lines[end - 1].strip():
            end -= 1
        out = "".join(lines[:end]).rstrip("\n") + "\n\n" + body + "".join(lines[end:])
    fragment.parent.mkdir(parents=True, exist_ok=True)
    fragment.write_text(out.rstrip("\n") + "\n", encoding="utf-8")
    return ids
