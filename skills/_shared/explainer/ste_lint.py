"""explainer/ste_lint.py — the deterministic STE-80 lint for explain envelopes.

Public API:
    DESCRIPTION_MAX_WORDS   25   a description sentence longer than this is a soft miss
    LIST_ITEM_MAX_WORDS     20   a list-item sentence longer than this is a soft miss
    HARD_MAX_WORDS          30   any sentence longer than this is a hard fail
    MAX_PASSIVE_PCT         20   passive sentences allowed, % of all sentences
    MAX_SOFT_MISS_PCT       10   soft-length misses allowed, % of all sentences
    BANNED                       closed tuple of banned idioms and filler
    lint(env) -> {"passed": bool, "issues": [{path, sentence, rule}, ...]}

Fields and forms. lint reads every sentence-bearing field, in envelope order,
named as evidence_refs names them: ``ste_summary``,
``sections[<i>].items[<j>]``, ``confidence_note``. The summary and the note
are description prose. A section item is a list item, unless it carries
``"form": "description"`` (FORM_KEY / DESCRIPTION). Section titles are
headings, not sentences, and are not linted. A malformed field (not a dict,
text not a string) is skipped: shape is explain_envelope's job.

Sentences. ``**`` markup is stripped first. A sentence ends at ``.``, ``!``,
``?``, ``;`` or ``:`` followed by whitespace, and at a newline; a mark inside
a backticked code span or inside parentheses never ends one. In each
sentence a code span counts as one word, text inside parentheses is not
counted, and a word is a whitespace token holding a letter or digit. A
sentence with no counted word is not a sentence.

Rules (one issue per sentence per rule; the rule names are the contract):
    soft-length   over its field's limit (25 description, 20 list item), up to 30
    hard-length   over HARD_MAX_WORDS words
    passive       a be-verb, optionally one word, then a word ending -ed/-en
                  (a heuristic; it reads the counted text)
    banned        a BANNED entry, any case, outside code spans; a one-word
                  entry also matches its inflections (leverage -> leveraging)

``passed`` is True when there is no hard-length and no banned issue, soft
misses are at most MAX_SOFT_MISS_PCT % of the sentences, and passive
sentences at most MAX_PASSIVE_PCT %. Passive and soft issues are reported
even when the ratios pass.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DESCRIPTION_MAX_WORDS = 25
LIST_ITEM_MAX_WORDS = 20
HARD_MAX_WORDS = 30
MAX_PASSIVE_PCT = 20
MAX_SOFT_MISS_PCT = 10

FORM_KEY = "form"
DESCRIPTION = "description"

RULE_SOFT_LENGTH = "soft-length"
RULE_HARD_LENGTH = "hard-length"
RULE_PASSIVE = "passive"
RULE_BANNED = "banned"

# Closed list of idioms and filler (detailed-design §Interfaces names the
# first seven). skills/_shared/ste-writing.md lists every entry.
BANNED = (
    "leverage", "utilize", "utilise", "seamless", "robust", "simply",
    "obviously", "basically", "essentially", "under the hood",
    "out of the box", "low-hanging fruit", "game changer", "cutting-edge",
    "best-in-class",
)

BE_VERBS = ("am", "is", "are", "was", "were", "be", "been", "being")

_CODE_RE = re.compile(r"`[^`\n]*`")
_PAREN_RE = re.compile(r"\([^()]*\)")
_BOUNDARY_RE = re.compile(r"[.!?;:](?=\s)|\n")
_WORD_RE = re.compile(r"\w")
_CODE_WORD = "CODE"
_PASSIVE_RE = re.compile(
    r"\b(?:" + "|".join(BE_VERBS) + r")\s+(?:[\w'-]+\s+)?\w+(?:ed|en)\b",
    re.IGNORECASE)


def _banned_pattern(entry: str) -> re.Pattern:
    words = entry.split()
    body = r"\s+".join(re.escape(w) for w in words)
    tail = r"\w*" if len(words) == 1 else r"\b"
    return re.compile(r"\b" + body + tail, re.IGNORECASE)


_BANNED_RES = tuple(_banned_pattern(entry) for entry in BANNED)


def _mask(text: str) -> str:
    """``text`` with code spans and parenthesised text blanked, same length."""
    def blank(m):
        return "_" * len(m.group(0))

    masked = _CODE_RE.sub(blank, text)
    while True:
        nxt = _PAREN_RE.sub(blank, masked)
        if nxt == masked:
            return masked
        masked = nxt


def _sentences(text: str) -> list:
    """Split ``text`` (``**`` already stripped) into stripped sentences."""
    out, start = [], 0
    for m in _BOUNDARY_RE.finditer(_mask(text)):
        out.append(text[start:m.end()])
        start = m.end()
    out.append(text[start:])
    return [s.strip() for s in out if s.strip()]


def _counted(sentence: str) -> str:
    """The sentence as counted: code spans as one word, no parenthesised text."""
    text = _CODE_RE.sub(_CODE_WORD, sentence)
    while True:
        nxt = _PAREN_RE.sub(" ", text)
        if nxt == text:
            return text
        text = nxt


def _word_count(counted: str) -> int:
    return sum(1 for tok in counted.split() if _WORD_RE.search(tok))


def _is_banned(sentence: str) -> bool:
    text = _CODE_RE.sub(_CODE_WORD, sentence)
    return any(rx.search(text) for rx in _BANNED_RES)


def _fields(env) -> list:
    """(path, text, word limit) for every lintable field, in envelope order."""
    if not isinstance(env, dict):
        return []
    found = [("ste_summary", env.get("ste_summary"), DESCRIPTION_MAX_WORDS)]
    sections = env.get("sections")
    for i, sec in enumerate(sections if isinstance(sections, list) else []):
        items = sec.get("items") if isinstance(sec, dict) else None
        for j, item in enumerate(items if isinstance(items, list) else []):
            limit = (DESCRIPTION_MAX_WORDS if isinstance(item, dict)
                     and item.get(FORM_KEY) == DESCRIPTION
                     else LIST_ITEM_MAX_WORDS)
            found.append((f"sections[{i}].items[{j}]", item, limit))
    found.append(("confidence_note", env.get("confidence_note"),
                  DESCRIPTION_MAX_WORDS))
    return [(path, item["text"], limit) for path, item, limit in found
            if isinstance(item, dict) and isinstance(item.get("text"), str)]


def _sentence_rules(sentence: str, limit: int):
    """The rules ``sentence`` breaks, or None when it holds no counted word."""
    counted = _counted(sentence)
    words = _word_count(counted)
    if words == 0:
        return None
    rules = []
    if words > HARD_MAX_WORDS:
        rules.append(RULE_HARD_LENGTH)
    elif words > limit:
        rules.append(RULE_SOFT_LENGTH)
    if _PASSIVE_RE.search(counted):
        rules.append(RULE_PASSIVE)
    if _is_banned(sentence):
        rules.append(RULE_BANNED)
    return rules


def lint(env) -> dict:
    """Lint every sentence of ``env``; see the module docstring for the rules."""
    issues: list = []
    total = 0
    for path, text, limit in _fields(env):
        for sentence in _sentences(text.replace("**", "")):
            rules = _sentence_rules(sentence, limit)
            if rules is None:
                continue
            total += 1
            issues.extend({"path": path, "sentence": sentence, "rule": rule}
                          for rule in rules)
    counts = {rule: sum(1 for i in issues if i["rule"] == rule)
              for rule in (RULE_SOFT_LENGTH, RULE_HARD_LENGTH, RULE_PASSIVE,
                           RULE_BANNED)}
    passed = (counts[RULE_HARD_LENGTH] == 0 and counts[RULE_BANNED] == 0
              and counts[RULE_SOFT_LENGTH] * 100 <= MAX_SOFT_MISS_PCT * total
              and counts[RULE_PASSIVE] * 100 <= MAX_PASSIVE_PCT * total)
    return {"passed": passed, "issues": issues}
