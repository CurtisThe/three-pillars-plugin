"""skill_invocations.py — the commands a markdown file runs, read from its structured spans only.

design: living-doc-fragments, Task 1.11 (the wiring-test helper of plan §SKILL wiring tests).
A wiring test must not pin skill prose (skills/_shared/test-fragility.md §1-2). It asks
``invocations(md_path, script, *, fill=None, root=None)`` for the argv of every ``python3 …/<script> …``
command in the file's inline code spans and fenced lines (``skill_spans.code_spans`` + ``tokens_of``),
then checks or runs that argv; prose and frontmatter are never read. A span that does not split into
tokens is skipped (``skill_refs.check`` reports it).

Each result is the argv from the interpreter on (``["python3", "<script path>", *args]``); a ``cd x &&``
prefix, a pipe or a redirect is cut away. ``fill`` maps a name to its value and fills every ``{name}``
placeholder (an unmapped one stays as written); ``root`` replaces a leading ``$TP_ROOT`` (or the
plugin-root variable, braced or not) in a token. To run one, swap ``argv[0]`` for ``sys.executable``.

``skill_spans`` is dev-only (``dev_only_shared``) and tier_guard forbids a shipped file to import it, so
``invocations`` takes it through ``pytest.importorskip`` (the guarded form): in a plugin copy the calling
test skips, and this module still imports. Stdlib only (pytest is loaded inside ``invocations``).
"""
from __future__ import annotations

import re
import sys
from itertools import groupby, takewhile
from pathlib import Path, PurePosixPath

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

_CONTROL = frozenset({"|", "||", "&&", ";", "&"})
_REDIRECT = re.compile(r"^\d*>|^<$")
_ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
_FILL = re.compile(r"\{([^{}\s]+)\}")
_ROOT = re.compile(r"^\$(?:\{(?:TP_ROOT|CLAUDE_PLUGIN_ROOT)\}|(?:TP_ROOT|CLAUDE_PLUGIN_ROOT))")


def _commands(tokens: list[str]) -> list[list[str]]:
    """The simple commands of a token list: split at control operators, each cut at its first redirect."""
    groups = (list(g) for sep, g in groupby(tokens, key=_CONTROL.__contains__) if not sep)
    return [list(takewhile(lambda t: not _REDIRECT.match(t), g)) for g in groups]


def _python_call(cmd: list[str], script: str) -> list[str] | None:
    """``cmd`` from its ``python3`` token on when it runs ``script`` (any directory), else None."""
    start = next((i for i, t in enumerate(cmd) if not _ASSIGN.match(t)), len(cmd))
    cmd = cmd[start:]
    if not cmd or cmd[0] not in ("python3", "python"):
        return None
    target = next((t for t in cmd[1:] if not t.startswith("-")), None)
    return cmd if target and PurePosixPath(target).name == script else None


def _filled(token: str, fill: dict, root) -> str:
    token = _FILL.sub(lambda m: str(fill.get(m.group(1), m.group(0))), token)
    return _ROOT.sub(str(root), token) if root is not None else token


def invocations(md_path, script: str, *, fill: dict | None = None, root=None) -> list[list[str]]:
    """The argv of every ``python3 …/<script> …`` command in ``md_path``'s code spans, in file order."""
    import pytest

    skill_spans = pytest.importorskip("skill_spans")  # dev-only module: the guarded form
    found: list[list[str]] = []
    for _line, span, shell in skill_spans.code_spans(Path(md_path).read_text(encoding="utf-8")):
        try:
            tokens = skill_spans.tokens_of(span, shell)
        except ValueError:
            continue
        for cmd in _commands(tokens):
            call = _python_call(cmd, script)
            if call:
                found.append([_filled(t, fill or {}, root) for t in call])
    return found
