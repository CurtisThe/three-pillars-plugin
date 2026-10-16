"""The Tier-7 stdin bullet's DOCUMENTED field set, pinned by the SHAPE of each
declaration.

Scope, stated precisely (corrected in round 14): this pins every field the **bullet
documents**, which is a strict subset of every field `run_round.py` reads. See the
comment on :data:`_STDIN_FIELDS` for the five deliberate omissions.

The Tier-7 bullet in `tp-run-full-design/SKILL.md` is not prose about the stdin
contract — for a caller building its payload, it IS the contract. There is no schema
and no argparse to fall back on: `run_round.py` reads a JSON object off stdin with
`payload.get(...)`, so a field that silently leaves the documentation is a field
callers silently stop sending, and `.get()` returns None without complaint.

Restored in round 13. Round 12 deleted this guard along with ~900 lines of prose
byte-equality pins it happened to share a module with, but it was never a prose pin.
Measured after the deletion: removing NINE of the eleven declarations left the suite
green (799 passed). Only `review_proof_root` and `review_base` survived, pinned
incidentally elsewhere. `config` is the sharpest loss — the bullet itself documents
that omitting it defaults `review.expects_copilot` and `ci.expects_github_checks` to
true, which blocks code-review-only convergence on repos without Copilot.

Deliberately NOT an equality pin over the region: adding a field is a routine additive
API change that must not fail, while dropping one is breaking. So this asserts presence
of each DECLARATION and nothing about the surrounding sentence.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"

# The bullet's field half: from its opening words up to the resume-claim sentence.
_BULLET_OPENING = "Shell out the round decision"
_CLAIM_OPENING = "The wrapper reads + writes"

# Every field the Tier-7 bullet DOCUMENTS — NOT every field `run_round.py` reads.
#
# Do not read this tuple as an inventory of the stdin API. `run_round.py` reads five
# more that the bullet deliberately says nothing about, and none of them has a single
# backticked occurrence in either SKILL.md (verified):
#
#   * `dispose_only` (:211) — the switch into a whole ALTERNATE mode, documented as
#     `--dispose-only` in `tp-pr-iterate/SKILL.md` rather than as a Tier-7 stdin field;
#   * `state`       (:131, :216) — the inline-state seam, an alternative to `state_path`;
#   * `author`      (:133) — defaults to "automation";
#   * `posted_comments`, `self_login` (:358, :359) — the hermetic test boundary seam.
#
# They are omitted on purpose: the bullet is the contract for the Tier-7 CALLER, and
# these five are not part of what that caller sends. The omission is the gap worth
# knowing about — if one of them ever becomes a documented Tier-7 field, add it here in
# the same commit. Widening this tuple to "everything `run_round.py` reads" WITHOUT
# documenting them would fail immediately, since the bullet declares none of them.
_STDIN_FIELDS = (
    "state_path", "head_sha", "codereview_findings", "reviewed",
    "unresolved_actionable", "ci_rollup", "config", "review_proof_root",
    "review_base", "pr_url", "decisions_path",
)


def _field_half() -> str:
    """The bullet from its first words up to the resume claim — backticks intact.

    Backticks are kept because a declaration's SHAPE is made of them: this is what
    tells `` `config` `` (a declaration) from `` `.three-pillars/config.json` `` (a
    path that merely contains the characters). A naive free-substring scan over this
    region caught only 7 of the 11 — four names survive their own deletion because the
    same characters occur elsewhere in reach.
    """
    flat = " ".join(re.sub(r"\*", "", skill_text.read_skill_text("tp-run-full-design")).split())
    begin = flat.index(_BULLET_OPENING)
    return flat[begin:flat.index(_CLAIM_OPENING, begin)]


def test_the_stdin_bullet_still_declares_every_field_it_documents() -> None:
    """All 11 DOCUMENTED fields, each a backticked bare identifier in the field half."""
    half = _field_half()
    missing = [f for f in _STDIN_FIELDS if f"`{f}`" not in half]
    assert not missing, (
        f"the Tier-7 stdin-contract bullet no longer declares {missing} — the bullet IS "
        "the contract a Tier-7 caller builds its payload from, and there is no schema "
        "behind it. (It documents a strict SUBSET of what `run_round.py` reads; see the "
        "comment on `_STDIN_FIELDS`. Do not read this list as the stdin API, and do not "
        "widen it to one.)\n\n"
        "This is the FIELD-LIST class of change, not the resume-contract class:\n"
        "  * ADDING a field is additive and fine — document it here, no pin to touch;\n"
        "  * REMOVING or RENAMING one is a breaking API change. Do it deliberately, "
        "and update `run_round.py`'s stdin parsing and this list in the SAME commit.\n\n"
        "If the field IS still documented, check its SHAPE: this looks for a backticked "
        "bare identifier (`` `state_path` ``), deliberately not a free substring — "
        "mentioning the name inside a path or a function call does not declare it.\n\n"
        "Do not delete the name from this tuple to make the failure go away."
    )


def test_every_pinned_field_is_actually_read_by_run_round() -> None:
    """The pin must track the code, or it decays into a list of names nobody reads.

    Without this, a field deleted from `run_round.py` keeps its declaration in the
    bullet and this module goes on asserting a contract the wrapper no longer honours —
    the same drift, arriving from the code side instead of the prose side.
    """
    # The payload reads live in run_round.py and, since iterate-convergence-budget, in
    # run_round_boundary.round_inputs (the wrapper's stdin half).
    scripts = Path(__file__).resolve().parent.parent.parent / "tp-pr-iterate" / "scripts"
    src = "".join((scripts / name).read_text(encoding="utf-8")
                  for name in ("run_round.py", "run_round_boundary.py"))
    unread = [f for f in _STDIN_FIELDS
              if f'payload.get("{f}"' not in src and f'payload["{f}"]' not in src]
    assert not unread, (
        f"{unread} are documented in the Tier-7 stdin bullet but `run_round.py` no "
        "longer reads them off the payload. Either the wrapper dropped a field (update "
        "the bullet AND this tuple in the same commit) or the read moved behind a "
        "helper (update this scan)."
    )
