"""`shaped_merge.is_shaped_line_merge`: which diff3 hunks the shaped-line merge may touch.

Spec: basesync-three-way-verifier detailed-design.md (Interfaces: `is_shaped_line_merge`, the
import graph) and plan Task 4.1. The predicate admits a hunk only when it is 3-way with a
non-empty base, no line of it is blank, and it is either a TABLE arm (ID rows and slug rows, at
least one slug row, no delimiter or header row) or a LOG arm (single-line log bullets, with the
hunk ending at an entry boundary). Inputs are small hand-built hunks parsed from diff3 text; every
case is a concrete example with its expected verdict. Rule: skills/_shared/test-fragility.md
(behaviour only: the import rule is shown by re-execution, not by reading the module's source).
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
import shaped_merge  # noqa: E402
from conflict_fixtures import diff3, diff3_empty_base  # noqa: E402
from shaped_merge import is_shaped_line_merge  # noqa: E402

SCRIPTS = os.path.dirname(os.path.abspath(__file__))

R = "| `ci-settle` | wait for the status context | Seed |"
R2 = "| `ci-settle` | wait for the status context | Done |"
X = "| `new-ours` | the ours row | Seed |"
Y = "| `new-theirs` | the theirs row | Seed |"
D1 = "| D1 | design-a | Seed |"
D2 = "| D2 | design-b | Seed |"
D2_DONE = "| D2 | design-b | Done |"
DELIM = "|--------|------|--------|"
SPACED_DELIM = "| --- | --- | --- |"
HEADER = "| Design | Note | Status |"
ID_HEADER = "| ID | Design | Status |"

SEED = "- **2026-07-01** — the seed entry."
SEED2 = "- **2026-07-02** — the second seed entry."
OURS = "- **2026-07-03** — the ours entry."
THEIRS = "- **2026-07-04** — the theirs entry."
NAMED = "- **`design-a`** — Implemented (2026-07-04)."


def text(ours, base, theirs, post=None):
    block = diff3("\n".join(ours), "\n".join(base), "\n".join(theirs))
    return block if post is None else block + "\n" + post


def hunk(ours, base, theirs, post=None):
    """The first conflict region of the diff3 text built from the three sides, parsed the way the
    resolver parses it. `post` is a clean line that follows the region (None: it ends the text)."""
    parsed = classify.parse_conflict(text(ours, base, theirs, post))
    return next(seg for seg in parsed.segments if isinstance(seg, classify.Hunk))


# --- admitted: the table arm and the log arm ---------------------------------------------------

ADMITTED = {
    "the #219 shape: one row edited by theirs, one row appended by each side":
        hunk([R, X], [R], [R2, Y]),
    "slug rows mixed with ID rows": hunk([D1, R, X], [D1, R], [D1, R2, Y]),
    "slug rows beside a changed ID row": hunk([D1, D2, R], [D1, D2, R], [D1, D2_DONE, R, Y]),
    "a slug row in only one section": hunk([D1, D2], [D1, R], [D1, D2_DONE]),
    "a slug row with a CRLF line ending":
        hunk([R + "\r", X + "\r"], [R + "\r"], [R2 + "\r", Y + "\r"]),
    "the #188 History two-line rewrite": hunk([OURS, SEED2], [SEED, SEED2], [SEED, THEIRS]),
    "a log arm of name-keyed bullets": hunk([NAMED, OURS], [NAMED], [NAMED, THEIRS]),
}


@pytest.mark.parametrize("name", ADMITTED)
def test_an_admitted_shape_is_a_shaped_line_merge(name):
    assert is_shaped_line_merge(ADMITTED[name]) is True


# --- refused: not a 3-way region with a base ----------------------------------------------------

def test_a_two_way_region_is_refused():
    two_way = ("<<<<<<< ours\n" + "\n".join([R, X]) + "\n=======\n" + "\n".join([R2, Y])
               + "\n>>>>>>> theirs")
    parsed = classify.parse_conflict(two_way)
    region = next(seg for seg in parsed.segments if isinstance(seg, classify.Hunk))
    assert region.base_marker is None
    assert is_shaped_line_merge(region) is False


def test_an_empty_base_is_refused():
    region = classify.parse_conflict(diff3_empty_base(X, Y)).segments[0]
    assert region.base == []
    assert is_shaped_line_merge(region) is False


# --- refused: a blank line in any section -------------------------------------------------------

@pytest.mark.parametrize("ours,base,theirs", [
    ([R, "", X], [R], [R2, Y]),
    ([R, X], [R, ""], [R2, Y]),
    ([R, X], [R], [R2, "", Y]),
    ([OURS, "", SEED2], [SEED, SEED2], [SEED, THEIRS]),
    ([OURS, SEED2], [SEED, "", SEED2], [SEED, THEIRS]),
    ([OURS, SEED2], [SEED, SEED2], [SEED, "", THEIRS]),
], ids=["table-ours", "table-base", "table-theirs", "log-ours", "log-base", "log-theirs"])
def test_a_blank_line_in_any_section_is_refused(ours, base, theirs):
    assert is_shaped_line_merge(hunk(ours, base, theirs)) is False


# --- refused: lines that are not shaped rows or single-line bullets -----------------------------

REFUSED = {
    "a separator row in a section of slug rows": hunk([R, DELIM, X], [R], [R2, Y]),
    "a spaced separator row": hunk([R, X], [R], [R2, SPACED_DELIM, Y]),
    "a separator row in the base": hunk([R, X], [DELIM, R], [R2, Y]),
    "a table header row (Design | Note | Status)": hunk([HEADER, R, X], [HEADER, R], [R2, Y]),
    "an ID-table header row (ID | Design)": hunk([R, X], [R], [ID_HEADER, R2, Y]),
    "a header and separator before the rows":
        hunk([HEADER, DELIM, R, X], [HEADER, DELIM, R], [HEADER, DELIM, R2, Y]),
    "an ID-only table hunk": hunk([D1, D2], [D1], [D1, D2_DONE]),
    "ID rows with a header and separator": hunk([ID_HEADER, DELIM, D1, D2],
                                                [ID_HEADER, DELIM, D1],
                                                [ID_HEADER, DELIM, D1, D2_DONE]),
    "slug rows mixed with log bullets": hunk([R, X], [R], [R2, SEED]),
    "log bullets with a row in the base": hunk([SEED, OURS], [SEED, R], [SEED, THEIRS]),
    "a prose line among slug rows": hunk([R, "Some prose, not a row."], [R], [R2, Y]),
    "a prose line among log bullets":
        hunk([SEED, "Workaround: rerun the job."], [SEED], [SEED, THEIRS]),
    "a wrapped (two-line) bullet": hunk([SEED, OURS, "  and it continues here"], [SEED],
                                        [SEED, THEIRS]),
    "a bullet that is not a log entry": hunk([SEED, "- plain list item"], [SEED], [SEED, THEIRS]),
    "a carriage return inside a row": hunk([R, "| `new-ours` | a\rb | Seed |"], [R], [R2, Y]),
}


@pytest.mark.parametrize("name", REFUSED)
def test_a_line_that_is_not_a_shaped_row_or_bullet_is_refused(name):
    assert is_shaped_line_merge(REFUSED[name]) is False


# --- the log arm must end at an entry boundary --------------------------------------------------

def built(post_context):
    """The same log-arm hunk with only `post_context` varied (a hand-built `Hunk`)."""
    return classify.Hunk(ours=[SEED, OURS], base=[SEED], theirs=[SEED, THEIRS],
                         post_context=post_context)


@pytest.mark.parametrize("post", [None, "Workaround: rerun.", "  indented continuation",
                                  "#### a level four heading", "#no-space"],
                         ids=["unknown", "prose", "indented", "h4", "no-space"])
def test_a_log_hunk_not_at_an_entry_boundary_is_refused(post):
    assert is_shaped_line_merge(built(post)) is False


@pytest.mark.parametrize("post", ["", NAMED, SEED2, "## Next section", "# Top", "### Three"],
                         ids=["eof", "named-bullet", "dated-bullet", "h2", "h1", "h3"])
def test_a_log_hunk_at_an_entry_boundary_is_admitted(post):
    assert is_shaped_line_merge(built(post)) is True


def test_the_boundary_is_read_from_the_parsed_text_after_the_region():
    args = ([SEED, OURS], [SEED], [SEED, THEIRS])
    assert is_shaped_line_merge(hunk(*args)) is True    # the region ends the text
    assert is_shaped_line_merge(hunk(*args, post="## Next section")) is True
    assert is_shaped_line_merge(hunk(*args, post=SEED2)) is True
    assert is_shaped_line_merge(hunk(*args, post="Workaround: rerun.")) is False


def test_a_log_hunk_directly_followed_by_another_region_is_refused():
    two = classify.parse_conflict(text([SEED, OURS], [SEED], [SEED, THEIRS]) + "\n"
                                  + text([SEED2, OURS], [SEED2], [SEED2, THEIRS]))
    first = next(seg for seg in two.segments if isinstance(seg, classify.Hunk))
    assert first.post_context is None
    assert is_shaped_line_merge(first) is False


def test_the_table_arm_does_not_look_at_what_follows_the_region():
    region = hunk([R, X], [R], [R2, Y], post="Workaround: rerun.")
    assert is_shaped_line_merge(region) is True


# --- the refusal type task 4.2 raises ------------------------------------------------------------

def test_shaped_merge_refused_is_a_value_error():
    assert issubclass(shaped_merge.ShapedMergeRefused, ValueError)
    with pytest.raises(ValueError):
        raise shaped_merge.ShapedMergeRefused("a shape fault")


# --- the import rule, shown by re-execution ------------------------------------------------------

BANNED = ("resolve_totality", "keyed_classes", "classify", "resolvers")

DENY = f"""
import sys
BANNED = {BANNED!r}


class Deny:
    def find_spec(self, name, path=None, target=None):
        if name in BANNED:
            raise ImportError("denied by the test: " + name)
        return None


sys.meta_path.insert(0, Deny())
"""


def run_isolated(body):
    return subprocess.run([sys.executable, "-c", DENY + body], cwd=SCRIPTS, capture_output=True,
                          text=True, timeout=60)


def test_the_finder_really_blocks_a_banned_module():
    run = run_isolated("import classify")
    assert run.returncode != 0
    assert "denied by the test: classify" in run.stderr


def test_shaped_merge_imports_with_every_banned_module_blocked():
    body = ("import shaped_merge\n"
            "loaded = sorted(set(BANNED) & set(sys.modules))\n"
            "assert not loaded, loaded\n"
            "print('ok')\n")
    run = run_isolated(body)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "ok"
