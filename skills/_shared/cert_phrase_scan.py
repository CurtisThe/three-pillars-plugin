"""Certifying-phrase scan: find prose that claims a guard binds without a record.

design: audit-pass-does-not-bind (Task 5.1; detailed-design.md §Interfaces [F5][R8][R9]).

A hit is `{text, field, matched}`:
  * `PHRASES` are high-precision literals ("non-vacuous", "mutation-proved", ...);
  * the proximity form is `GUARD_NOUN (GAP_WORD){0,2} VERB` — plural and base
    forms (`guards bind`, `the tests catch it`, `the lint does not bind`); bare
    `binds` or `would catch` with no guard noun are not hits;
  * a nearby negator suppresses nothing (amended 2026-09-25, [R8]): `no test
    catches it` is a hit like `the test catches it`. Describe a guard that does
    not bind without the certifying wording;
  * `matched` — the same field carries `[cert:<id>]` for a returned claim; the
    tag alone binds (amended 2026-09-25, [R9]: the sentence need not repeat the
    guard path). A member field (council summaries) carries no tags and needs
    the guard path (the part before `::`) of some returned claim.

`scan(text, claims)` scans a markdown artifact: `parse_section` locates the
`## Guards certified` section, whose body is never scanned; a missing section
is one synthetic hit; a body that is exactly `No guard claims.` (`is_no_claims`:
its only non-blank line, never a substring such as the template placeholder that
quotes it) makes every hit unmatched; tags are matched per paragraph. Only hits
with `matched is False` escalate (the fold counts nothing else).

`scan_envelope(env, members, *, slot)` (Task 5.2 [D][R8], N16) runs on every
Slot 4/8 audit return: `summary` and each `findings[*].description`; in Slot 8
also each council member's R1 `argument_summary` and R2 `counter_argument`
(round bundles are flattened) — never `suggested_fix`. Claims default to the
envelope's `guard_claims`. Both slots keep every hit: an unmatched hit in a
Slot 4 return escalates exactly as in Slot 8 (fail-closed), whether or not the
guard it names exists yet.

KNOWN BYPASS: a certification phrased outside PHRASES and the proximity form escapes the scan.
"""

from __future__ import annotations

import re

PHRASES = (
    "non-vacuous", "nonvacuous", "not vacuous", "mutation-proved", "mutation proved",
    "mutation-tested", "mutation-verified", "red-then-green", "red on the parent", "seen red",
)
GUARD_NOUN = r"(?:tests?|checks?|guards?|lints?|gates?|assertions?|invariants?|pins?)"
# Words that may sit between the guard noun and the verb; `n't` contractions too.
GAP_WORDS = ("really", "actually", "now", "genuinely", "still", "does", "would", "will",
             "not", "never", "cannot")
VERB = r"(?:bind|binds|catch|catches|caught|go\s+red|goes\s+red|went\s+red)"
SECTION_HEADING = "## Guards certified"
NO_CLAIMS = "No guard claims."

_LITERAL_RE = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(p) for p in PHRASES)
                         + r")(?![\w-])", re.IGNORECASE)
_GAP_WORD = "|".join([*GAP_WORDS, r"[a-z]+n['\u2019]t"])
_PROXIMITY_RE = re.compile(
    rf"\b{GUARD_NOUN}\s+(?:(?:{_GAP_WORD})\s+){{0,2}}?{VERB}\b", re.IGNORECASE)
_TAG_RE = re.compile(r"\[cert:([^\]\s]+)\]")
_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)


def _guard_path(claim: dict) -> str:
    return str(claim.get("guard") or "").partition("::")[0]


def _matched(field_text: str, claims: list[dict], *, member: bool) -> bool:
    if member:
        return any(_guard_path(c) and _guard_path(c) in field_text for c in claims)
    tagged = set(_TAG_RE.findall(field_text))
    return any(c.get("id") in tagged for c in claims)


def _raw_hits(text: str):
    """Yield `(start, end)` for every literal and proximity match."""
    for regex in (_LITERAL_RE, _PROXIMITY_RE):
        for m in regex.finditer(text):
            yield m.start(), m.end()


def scan_field(text: str, field: str, claims: list[dict], *, member: bool = False,
               match_text: str | None = None) -> list[dict]:
    """Hits in one field; `match_text` (default `text`) is where tags (member: paths) are sought."""
    text = text or ""
    matched = _matched(text if match_text is None else match_text, claims or [], member=member)
    return [{"text": " ".join(text[s:e].split()), "field": field, "matched": matched}
            for s, e in sorted(_raw_hits(text))]


def parse_section(text: str) -> dict:
    """`{present, no_claims, body, rest}` for the `## Guards certified` section."""
    lines = (text or "").splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip().lower() == SECTION_HEADING.lower()), None)
    if start is None:
        return {"present": False, "no_claims": False, "body": "", "rest": text or ""}
    end = next((j for j in range(start + 1, len(lines)) if _HEADING_RE.match(lines[j])),
               len(lines))
    body = "".join(lines[start + 1:end])
    rest = "".join(lines[:start] + lines[end:])
    return {"present": True, "no_claims": is_no_claims(body), "body": body, "rest": rest}


def is_no_claims(body: str) -> bool:
    """True only when the section's sole non-blank line is exactly `NO_CLAIMS`.

    Blank lines and whitespace at the line's ends (a trailing newline, CR) are tolerated;
    anything else — a bullet, backticks, another case, a second line, or the template
    placeholder that merely quotes the sentinel — is a claim list, not the sentinel."""
    return [ln.strip() for ln in (body or "").splitlines() if ln.strip()] == [NO_CLAIMS]


def _paragraphs(text: str):
    """Yield `(first_line_number, paragraph)` for blank-line separated blocks."""
    line, block, first = 0, [], 1
    for line, raw in enumerate(text.splitlines(), start=1):
        if raw.strip():
            if not block:
                first = line
            block.append(raw)
        elif block:
            yield first, "\n".join(block)
            block = []
    if block:
        yield first, "\n".join(block)


def scan(text: str, claims: list[dict]) -> list[dict]:
    """Scan a markdown audit artifact (section body excluded, tags per paragraph)."""
    section = parse_section(text)
    hits = []
    if not section["present"]:
        hits.append({"text": f"missing {SECTION_HEADING} section", "field": "section",
                     "matched": False})
    effective = [] if section["no_claims"] else claims
    for line, para in _paragraphs(section["rest"]):
        hits.extend(scan_field(para, f"line {line}", effective))
    return hits


# --- per-slot envelope scan (Task 5.2) --------------------------------------------------

SLOTS = (4, 8)
MEMBER_FIELDS = ("argument_summary", "counter_argument")


def _members(members) -> list[dict]:
    flat = []
    for item in members or []:
        if isinstance(item, dict) and isinstance(item.get("outputs"), list):
            flat.extend(o for o in item["outputs"] if isinstance(o, dict))
        elif isinstance(item, dict):
            flat.append(item)
    return flat


def _envelope_fields(env: dict):
    yield "summary", env.get("summary")
    for i, f in enumerate(env.get("findings") or []):
        if isinstance(f, dict):
            yield f"findings[{i}].description", f.get("description")


def scan_envelope(env: dict, members, *, slot, claims: list[dict] | None = None) -> list[dict]:
    """Hits for one audit return; see the module docstring for the per-slot rules."""
    slot = int(slot)
    if slot not in SLOTS:
        raise ValueError(f"unknown slot {slot!r}; expected one of {SLOTS}")
    if claims is None:
        claims = [c for c in env.get("guard_claims") or [] if isinstance(c, dict)]
    hits = []
    for field, text in _envelope_fields(env):
        if isinstance(text, str):
            hits.extend(scan_field(text, field, claims))
    if slot == 8:
        for i, member in enumerate(_members(members)):
            name = member.get("member") or str(i)
            for key in MEMBER_FIELDS:
                if isinstance(member.get(key), str):
                    hits.extend(scan_field(member[key], f"members[{name}].{key}", claims,
                                           member=True))
    return hits
