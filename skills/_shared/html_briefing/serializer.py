"""html_briefing/serializer.py — canonical compact answer-string grammar.

Defines the grammar the HTML briefing's "Assemble answers" button emits and
that the operator pastes into the terminal prompt.

Grammar (defined here, documented in tp-promote/SKILL.md Steps 5-6):
  - ``defaults``                    → accept every drafter default
  - otherwise one override per line (newline-separated, NEVER comma-separated):
    - single-select: ``2b``         (question 2 → option b)
    - multi-select:  ``4a c``       (question 4 → options a AND c, space-sep)
    - free-text:     ``3: text``    (everything after ': ' to end-of-line)
  - unmentioned questions keep their default.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Union


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Question:
    """One question in a batched confirm block.

    Attributes:
        number:  1-based question index (used as key in serialized form).
        kind:    'single' | 'multi' | 'free'.
        options: list of (letter, label) pairs; empty for free-text.
        default: default selection — str for single/free, list[str] for multi.
        chosen:  current/operator selection — same type as default.
    """
    number: int
    kind: str  # 'single' | 'multi' | 'free'
    options: list  # [(letter, label), ...]
    default: Union[str, list]
    chosen: Union[str, list]


@dataclass
class ConfirmModel:
    """The full set of questions for one promote-round batched confirm."""
    questions: list  # list[Question]

    @property
    def selections(self) -> dict:
        """Return {question.number: question.chosen} for all questions.

        Multi-select selections are normalized to sorted lists: option order is
        not meaningful for a multi-select, so the round-trip guarantee
        ``parse(serialize(model)) == model.selections`` must hold regardless of
        the order the caller supplied ``chosen`` in.
        """
        return {
            q.number: (sorted(q.chosen) if q.kind == "multi" else q.chosen)
            for q in self.questions
        }

    def _by_number(self) -> dict:
        """Return {number: Question} lookup."""
        return {q.number: q for q in self.questions}


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------

def serialize_answers(model: ConfirmModel) -> str:
    """Serialize model.selections to the canonical compact answer string.

    Returns the literal ``"defaults"`` when every question's chosen equals its
    default.  Otherwise returns one override per line (newline-separated) in
    question-number order, only for questions that differ from their default.
    """
    overrides = []
    for q in sorted(model.questions, key=lambda q: q.number):
        if _is_default(q):
            continue
        overrides.append(_serialize_question(q))

    if not overrides:
        return "defaults"
    return "\n".join(overrides)


def _is_default(q: Question) -> bool:
    """Return True when chosen equals default (order-independent for multi)."""
    if q.kind == "multi":
        return sorted(q.chosen) == sorted(q.default)
    return q.chosen == q.default


def _serialize_question(q: Question) -> str:
    """Serialize a single non-default question to one line."""
    if q.kind == "free":
        if "\n" in q.chosen or "\r" in q.chosen:
            raise ValueError(
                "free-text answers are single-line; a newline is not representable "
                "in the compact grammar"
            )
        return f"{q.number}: {q.chosen}"
    if q.kind == "multi":
        letters = " ".join(sorted(q.chosen))
        return f"{q.number}{letters}"
    # single
    return f"{q.number}{q.chosen}"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Two separate regexes, tried in order per line.
# Regex 1: free-text — colon + exactly one literal space, body captured verbatim.
# Leading \s* tolerates operator indentation before the number only.
_FREE_RE = re.compile(r"^\s*(?P<num>\d+):\ (?P<free_body>.*)$")

# Regex 2: single/multi — optional letter(s) or bare number (empty multi-select).
_SELECT_RE = re.compile(r"^\s*(?P<num>\d+)(?P<letters>[a-z](?:\s+[a-z])*)?\s*$")


def parse_answer_string(s: str, model: ConfirmModel) -> dict:
    """Parse a compact answer string back to {question_number: selection}.

    ``"defaults"`` → every question's default.
    Otherwise split on newlines; each non-empty line is one override token.

    Raises:
        ValueError: for any token that is malformed, references an unknown
            question number, or uses an unrecognized option letter.
    """
    by_num = model._by_number()

    # Start with defaults for every question
    result: dict = {q.number: _copy_default(q) for q in model.questions}

    # Strip only surrounding newlines/carriage-returns, NOT spaces — so that a
    # free-text body on the last line whose answer ends with spaces is preserved.
    # We still need to detect the literal "defaults" token (which has no spaces).
    outer_stripped = s.strip("\r\n")
    if outer_stripped.strip() == "defaults":
        return result

    for raw_line in outer_stripped.splitlines():
        # Do NOT strip the whole raw_line — that would destroy free-text body
        # edge whitespace.  Instead each regex anchors its own leading \s*.
        # Skip lines that are entirely blank (empty or whitespace-only).
        if not raw_line.strip():
            continue
        _apply_token(raw_line, by_num, result)

    return result


def _copy_default(q: Question) -> Any:
    if q.kind == "multi":
        return sorted(q.default)
    return q.default


def _apply_token(token: str, by_num: dict, result: dict) -> None:
    """Parse one override token and apply it to result in-place.

    Tries _FREE_RE first (colon + one literal space as separator, body verbatim),
    then _SELECT_RE (letter(s) or bare number).  Raises ValueError if neither
    regex matches.
    """
    # Try free-text regex first
    m_free = _FREE_RE.match(token)
    if m_free:
        num = int(m_free.group("num"))
        if num not in by_num:
            raise ValueError(
                f"Question number {num} not found in the confirm model "
                f"(valid: {sorted(by_num)})."
            )
        q = by_num[num]
        if q.kind != "free":
            raise ValueError(
                f"Token {token!r} uses free-text syntax but question {num} "
                f"is kind={q.kind!r}."
            )
        result[num] = m_free.group("free_body")
        return

    # Try select regex (single/multi)
    m_sel = _SELECT_RE.match(token)
    if m_sel:
        num = int(m_sel.group("num"))
        if num not in by_num:
            raise ValueError(
                f"Question number {num} not found in the confirm model "
                f"(valid: {sorted(by_num)})."
            )
        q = by_num[num]
        letters_str = m_sel.group("letters")
        if letters_str is None:
            # bare question number → empty multi-select
            if q.kind != "multi":
                raise ValueError(
                    f"Token {token!r} is a bare question number but question {num} "
                    f"is kind={q.kind!r}; only a multi-select may have an empty "
                    "selection."
                )
            result[num] = []
        else:
            letters = letters_str.split()
            valid_letters = {opt[0] for opt in q.options}
            for letter in letters:
                if letter not in valid_letters:
                    raise ValueError(
                        f"Unknown option letter {letter!r} for question {num}. "
                        f"Valid: {sorted(valid_letters)}."
                    )
            if q.kind == "multi":
                result[num] = sorted(letters)
            else:
                # single: must be exactly one letter
                if len(letters) != 1:
                    raise ValueError(
                        f"Question {num} is single-select but got multiple letters: "
                        f"{letters!r}."
                    )
                result[num] = letters[0]
        return

    raise ValueError(
        f"Malformed answer token: {token!r}. "
        "Expected 'defaults', '<n><letter>', '<n><a> <b>', or '<n>: text'."
    )
