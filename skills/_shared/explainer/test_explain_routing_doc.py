"""test_explain_routing_doc.py — the schema and the doc state what `role_engines.explainer` means.

Covers explainer-agent plan Task 7.1: the schema's
`role_engines.properties.explainer.description` and the `role_engines` section of
`repo-config.md` each state the key's three meanings (unset: Sonnet drafts; `local`:
Strata, Sonnet when no backend or busy; `opus`: Opus drafts every kind) and that the
Opus check has no key.

The meanings are keyed by role_engine's own vocabulary (`role_engine.ENGINES` plus
"unset"), so a new engine value fails this test until both texts state its meaning
(skills/_shared/test-fragility.md §2). A meaning counts as stated when one clause of
the text (a sentence or a `;` part) carries all of its terms, case-insensitive.

Both files ship in skills/_shared beside the explainer package and are found from this
file's own path; no repo doc tree is read.
"""
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import role_engine  # noqa: E402

ROLE = "explainer"
SCHEMA_PATH = _SHARED_DIR / "repo-config.schema.json"
DOC_PATH = _SHARED_DIR / "repo-config.md"

# meaning -> the terms one clause must carry together.
MEANINGS = {
    "unset": ("unset", "sonnet"),
    "local": ("`local`", "strata", "sonnet", "no backend", "busy"),
    "opus": ("`opus`", "every kind"),
    "check": ("opus check", "no key"),
}


def _clauses(text: str) -> list:
    """`text` cut into sentences and `;` parts, whitespace-normalized and lowercased."""
    flat = " ".join(text.split()).lower()
    return [c for c in re.split(r"(?<=[.;])\s+", flat) if c]


def missing_meanings(text: str) -> set:
    """The MEANINGS keys no single clause of `text` states."""
    clauses = _clauses(text)
    return {name for name, terms in MEANINGS.items()
            if not any(all(t in c for t in terms) for c in clauses)}


def _schema_description() -> str:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    block = schema["properties"][role_engine.CONFIG_KEY]
    assert ROLE in block["properties"], f"schema {role_engine.CONFIG_KEY} has no {ROLE} key"
    return block["properties"][ROLE].get("description", "")


def _doc_section() -> str:
    """The `role_engines` bullet of repo-config.md and its indented continuation lines."""
    lines = DOC_PATH.read_text(encoding="utf-8").splitlines()
    head = f"- `{role_engine.CONFIG_KEY}`"
    start = next((i for i, ln in enumerate(lines) if ln.startswith(head)), None)
    assert start is not None, f"repo-config.md has no {head} bullet"
    section = [lines[start]]
    for ln in lines[start + 1:]:
        if not ln[:1].isspace():
            break
        section.append(ln)
    return "\n".join(section)


def test_meanings_cover_the_engine_vocabulary():
    assert set(MEANINGS) - {"check"} == {"unset", *role_engine.ENGINES}


def test_checker_is_not_vacuous():
    assert missing_meanings("The explainer drafts briefs.") == set(MEANINGS)
    stated = ("Unset = Sonnet drafts. `local` = Strata (Sonnet when no backend or busy); "
              "`opus` = Opus drafts every kind. The Opus check has no key.")
    assert missing_meanings(stated) == set()
    # Terms split across two clauses do not state a meaning.
    assert "local" in missing_meanings("`local` = Strata. Sonnet when no backend or busy.")


@pytest.mark.parametrize("source", ["schema", "doc"])
def test_text_states_every_explainer_meaning(source):
    text = _schema_description() if source == "schema" else _doc_section()
    if source == "doc":
        assert f"`{ROLE}`" in text, "the role_engines section does not name the explainer key"
    assert missing_meanings(text) == set(), (
        f"{source} misses explainer meanings: {sorted(missing_meanings(text))}")
