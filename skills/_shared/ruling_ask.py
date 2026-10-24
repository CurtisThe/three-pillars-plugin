#!/usr/bin/env python3
"""ruling_ask.py — write one run-asked ruling file, or refuse and write nothing.

design: run-no-cards-hook Task 1.4. The ruling-file path took several
hand-built steps, so a run reached for a card; one call makes the allowed
path cheaper than the denied one. The kind is carried so an OPERATOR_ONLY
question never lands in the seat's lane. Stdlib only.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer_ruling  # noqa: E402
import ruling_file  # noqa: E402

MODEL = "run-ask"
DEFAULT_KIND = "decision"
MIN_OPTIONS, MAX_OPTIONS = 2, 4


class AskError(ValueError):
    """A refused ask (the CLI turns it into exit 2, nothing written)."""


def check_kind(kind: str) -> str:
    if kind not in finalizer_ruling.KINDS:
        raise AskError(f"bad kind {kind!r}; kinds: {', '.join(finalizer_ruling.KINDS)}")
    return kind


def parse_option(text: str) -> tuple[str, str]:
    label, sep, desc = text.partition("=")
    if not sep:
        raise AskError(f"option {text!r} must be LABEL=DESCRIPTION")
    if not label.strip():
        raise AskError(f"option {text!r} has a blank label")
    return label.strip(), desc.strip()


def build(question: str, options, recommended: str, context: str = "") -> dict:
    if not question.strip():
        raise AskError("question is blank")
    parsed = [parse_option(o) for o in options]
    if not MIN_OPTIONS <= len(parsed) <= MAX_OPTIONS:
        raise AskError(f"need {MIN_OPTIONS}-{MAX_OPTIONS} options, got {len(parsed)}")
    labels = [label for label, _ in parsed]
    if len(set(labels)) != len(labels):
        raise AskError("option labels must be unique")
    if not recommended.strip():
        raise AskError("--recommended is required")
    if recommended not in labels:
        raise AskError(f"recommended {recommended!r} not among labels: {', '.join(labels)}")
    return {"outcome": "escalate", "ruling": {"question": question, "options": [
        {"id": label, "label": label, "description": desc,
         "recommended": label == recommended} for label, desc in parsed],
        "context": context}}


def stop_key(scope: str, question: str, kind: str = DEFAULT_KIND) -> str:
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:8]
    return f"question:{kind}:{scope}:{digest}"


def ask(root, *, scope, question, options, recommended, kind=DEFAULT_KIND,
        context="", at=None) -> Path:
    check_kind(kind)
    result = build(question, options, recommended, context)
    return ruling_file.write(
        root, scope=scope, entry="run",
        stop={"source": "question", "signal": kind, "target": scope,
              "detail": {"question": question}},
        key=stop_key(scope, question, kind), result=result, model=MODEL, at=at)
