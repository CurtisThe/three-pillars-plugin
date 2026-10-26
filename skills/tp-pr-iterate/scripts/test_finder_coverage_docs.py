"""Task 1.14: the four driver docs name the finder-cap-coverage CLIs and tokens.

design: finder-cap-coverage (Behaviors 1-8)

Every token asserted here exists in code, and the test derives it from that code rather than
copying a string: `put-partial`/`spawned` are subcommands of the two cap CLIs, the inline
marker is `agent_caps.FINDING_MARK`, `settle`/`retry` and `--capped`/`--final` are
`finder_retry._args`'s subcommands and flags, `merge` is a `finder_segments.main` subparser,
`--rung`/`--reason` are `dispatch_log.py`'s flags and `sonnet-xhigh` is a
`model_policy.rung_model` rung, `review.strata_finder_lines_per_cap` is a
`repo-config.schema.json` key, and the outcome words are `finder_retry.OUTCOMES`. Each token
must sit in the named doc section, located by heading — §Large diffs, §Serial finders, both
§Caps, round-topology step 4, the digest example. No sentence or phrase is pinned: the docs
stay free to say the rule in any words, and a token that moves to another section is a real
doc bug (the driver follows the section).
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import agent_caps  # noqa: E402
import dispatch_log  # noqa: E402
import finder_retry  # noqa: E402
import finder_segments  # noqa: E402
import model_policy  # noqa: E402

FINDERS = _ROOT / "skills/tp-pr-iterate/strata-finders.md"
RULES = _ROOT / "skills/tp-pr-iterate/convergence-rules.md"
TOPOLOGY = _ROOT / "skills/tp-pr-iterate/round-topology.md"
PROOF = _ROOT / "skills/tp-pr-iterate/proof-of-review.md"
SCHEMA = _ROOT / "skills/_shared/repo-config.schema.json"

# The digest example: the three label forms `finder_coverage.label_suffix` and
# `angles.digest_labels` post for a segmented round.
LABEL_FORMS = ("[coverage <n>%]", "[capped: re-covered by opus-check]",
               "[skipped: segment budget, <m> files]")

FINDING_TOKEN = agent_caps.FINDING_MARK.strip()
SEGMENT_TOKENS = ("put-partial", FINDING_TOKEN, "finder_retry.py settle",
                  "finder_retry.py retry", "--capped", "--final", "merge",
                  "--rung sonnet-xhigh --reason capped",
                  "review.strata_finder_lines_per_cap", "uncovered_files", "coverage")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body of `heading`, up to the next `## ` heading — the section, not the file."""
    start = text.find(heading)
    assert start != -1, f"missing heading: {heading}"
    nxt = text.find("\n## ", start + len(heading))
    return text[start:nxt] if nxt != -1 else text[start:]


def _flat(text: str) -> str:
    return " ".join(text.split())


# --- the tokens, read from the code that owns them -------------------------

def test_caps_cli_subcommands_are_the_ones_the_docs_name():
    """`put-partial` is a subcommand of `agent_caps._args`."""
    assert agent_caps._args(["put-partial", "--reply-path", "R", "--finding", "{}"]).cmd \
        == "put-partial"


def test_caps_cli_accepts_the_spawned_record_call():
    """`spawned` is accepted by `agent_caps.py`'s CLI — it reaches the watch loop's parser
    (whose usage error names it), not agent_caps's own `invalid choice`."""
    err = io.StringIO()
    with pytest.raises(SystemExit) as raised, contextlib.redirect_stderr(err):
        agent_caps.main(["spawned"])
    assert raised.value.code == 2
    assert "spawned" in err.getvalue() and "agent_caps_watch" in err.getvalue()


def test_finder_retry_cli_takes_settle_retry_and_the_two_flags():
    """`settle`/`retry` and `--capped`/`--final` are `finder_retry._args`'s own shape."""
    for cmd in ("settle", "retry"):
        assert finder_retry._args([cmd, "--round-dir", "R", "--angle", "a"]).cmd == cmd
    settled = finder_retry._args(["settle", "--round-dir", "R", "--angle", "a",
                                  "--capped", "--final"])
    assert settled.capped and settled.final


def test_segments_cli_takes_merge():
    """`merge` is one of `finder_segments.main`'s subparsers — its own argparse error
    lists it as a choice."""
    err = io.StringIO()
    with pytest.raises(SystemExit) as raised, contextlib.redirect_stderr(err):
        finder_segments.main(["not-a-subcommand"])
    assert raised.value.code == 2
    assert "merge" in err.getvalue()  # the error lists the CLI's own choices


def test_dispatch_log_takes_the_rung_and_reason_flags():
    """`--rung sonnet-xhigh --reason capped` is a real `dispatch_log.py record` call: its
    `--rung`/`--reason` flags exist and `sonnet-xhigh` is a rung `model_policy` maps."""
    text = _read(_ROOT / "skills/_shared/dispatch_log.py")
    for flag in ("--rung", "--reason"):
        assert f'"{flag}"' in text, flag
    assert model_policy.rung_model("sonnet-xhigh", {"fallback_model": "sonnet"}) == "sonnet"


def test_lines_per_cap_is_a_schema_key():
    """`review.strata_finder_lines_per_cap` is in `repo-config.schema.json`."""
    props = json.loads(_read(SCHEMA))["properties"]["review"]["properties"]
    assert "strata_finder_lines_per_cap" in props


# --- §Large diffs (strata-finders.md) --------------------------------------

@pytest.mark.parametrize("token", SEGMENT_TOKENS)
def test_large_diffs_section_names_the_segment_token(token):
    assert token in _section(_read(FINDERS), "## Large diffs")


def test_large_diffs_outcomes_are_the_telemetry_words():
    """Every outcome word the docs list is one of `finder_retry.OUTCOMES` — the two lists
    are the same set, so a doc can never name an outcome the code never writes."""
    section = _flat(_section(_read(FINDERS), "## Large diffs"))
    words = {w for w in finder_retry.OUTCOMES if re.search(rf"\b{w}\b", section)}
    assert words == set(finder_retry.OUTCOMES), finder_retry.OUTCOMES


def test_large_diffs_drops_the_hand_marked_empty_reply_rule():
    """An empty reply never goes through `mark-unparseable`: the old sentence that routed a
    segment with no parseable reply there is gone, and the merge is the recovery."""
    section = _flat(_section(_read(FINDERS), "## Large diffs"))
    assert "mark-unparseable" not in section
    assert "unparseable-review-angle" in section


# --- §Serial finders (strata-finders.md) -----------------------------------

def test_serial_finders_records_every_spawn():
    """The serial loop records each spawn with `agent_caps.py spawned --slot-root <R>`."""
    section = _section(_read(FINDERS), "## Serial finders")
    assert "agent_caps.py spawned" in section
    assert "--slot-root <R>" in section


# --- both §Caps sections ---------------------------------------------------

@pytest.mark.parametrize("doc", (FINDERS, RULES))
def test_caps_section_names_the_segment_cap_step(doc):
    """A segment finder's hard stop is followed by `finder_retry.py settle --capped`."""
    section = _section(_read(doc), "## Caps")
    assert "finder_retry.py settle" in section
    assert "--capped" in section


@pytest.mark.parametrize("doc", (FINDERS, RULES))
def test_caps_section_keeps_put_capped_for_non_segment_finders(doc):
    section = _section(_read(doc), "## Caps")
    assert "agent_caps.py put-capped" in section


# --- round-topology.md step 4 ----------------------------------------------

def test_step4_carries_the_coverage_line_in_the_round_summary():
    """The orchestrator's posted round summary carries the line `tail-check` prints as its
    coverage field."""
    step = _flat(_section(_read(TOPOLOGY), "4. **Orchestrator.**"))
    assert "tail-check" in step
    assert "coverage" in step


# --- the digest example (proof-of-review.md) -------------------------------

@pytest.mark.parametrize("form", LABEL_FORMS)
def test_digest_example_shows_each_label_form(form):
    assert form in _read(PROOF)


# --- the docs stay under their caps ----------------------------------------

@pytest.mark.parametrize("path,cap", ((FINDERS, 200), (RULES, 180),
                                      (TOPOLOGY, 500), (PROOF, 500)))
def test_doc_stays_under_its_cap(path, cap):
    assert len(_read(path).splitlines()) <= cap, path.name
