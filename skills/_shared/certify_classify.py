"""certify_classify — pole classifier, claim fold and guard-output parsing.

design: audit-pass-does-not-bind (Tasks 2.3-2.5; detailed-design-certifier.md §2).

A pole is pytest when its guard is (`certify_argv.is_pytest_guard`), never by its
argv. A pytest pole is read from its JUnit XML report (`PoleRun.junit`, written by
the runner's own `--junitxml`; `certify_junit` parses and matches it), never from
console lines (amended 2026-09-25, PR #162 remediation) [R6]. `pytest_result(junit,
guard, source)` returns `(type, reason, qualifying)`: only a `<failure>` on a testcase the
declared guard names (its file, node and definition in `source`, the guard file's text
at S: `PoleRun.source`) gives the *pytest type* and the *qualifying output* (its
`message` text, where a RED marker must appear; the source echo and captured output
are not messages). Reasons: `pytest-no-xml` (no readable report), `pytest-ambiguous`
(more than one guard testcase failed), `pytest-no-type` (the failure names no
exception type), and the six non-red reasons of `certify_junit.guard_result`:
`pytest-error` (a setup or teardown `<error>`), `pytest-skipped`,
`pytest-foreign-file` (a test named like the guard's but defined in another file, or
elsewhere in the guard file, failed, or only such a test ran), `pytest-other-node`
(another testcase failed), `pytest-no-guard-case` (no testcase of the report is the guard's) and
`pytest-no-failure` (a guard testcase ran and passed).

For non-pytest output with a traceback, the qualifying output excludes the
traceback's `File "…"` lines and the indented source lines under them [R4].
*Traceback type* [R4] is the exception name on the final line of the last
traceback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import certify_junit
from certify_argv import is_pytest_guard

TRACEBACK_HEAD = "Traceback (most recent call last):"
TYPE_NAME = re.compile(r"^([A-Za-z_][\w.]*)(?::\s|:$|$)")


# --- output parsing (Task 2.3) --------------------------------------------------------

def qualifying_output(output: str) -> str:
    """The part of a non-pytest `output` a RED marker must appear in (module docstring)."""
    kept, in_tb = [], False
    for line in output.splitlines():
        if line.startswith(TRACEBACK_HEAD):
            in_tb = True
        elif in_tb and line[:1].isspace():
            continue
        elif in_tb and line.strip():
            in_tb = False
        kept.append(line)
    return "\n".join(kept)


def _type_name(text: str | None) -> str | None:
    if text is None:
        return None
    match = TYPE_NAME.match(text.strip())
    return match.group(1).rsplit(".", 1)[-1] if match else None


def pytest_result(junit: str | None, guard: str, source: str | None):
    """`(type, reason, qualifying)` for one pytest pole (module docstring)."""
    cases = certify_junit.parse(junit)
    if cases is None:
        return None, "pytest-no-xml", ""
    found, reason = certify_junit.guard_result(cases, guard, source)
    qual = "\n".join(case.message for case in found)
    if not found:
        return None, reason, qual
    if len(found) > 1:
        return None, "pytest-ambiguous", qual
    ptype = certify_junit.failure_type(found[0])
    return (ptype, None, qual) if ptype else (None, "pytest-no-type", qual)


def has_traceback(output: str) -> bool:
    return TRACEBACK_HEAD in output


def traceback_final_line(output: str) -> str | None:
    """The exception line that ends the last traceback, or None."""
    lines = output.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(TRACEBACK_HEAD)]
    if not starts:
        return None
    for line in lines[starts[-1] + 1:]:
        if line.strip() and not line[:1].isspace():
            return line.rstrip()
    return None


def traceback_type(output: str) -> str | None:
    return _type_name(traceback_final_line(output))


# --- pole classifier (Task 2.4) ----------------------------------------------------------
#
# `H` = the GREENs' shared expect.exit (default 0); `V` = the REDs' expect.exit
# (any rc in 1..125 when absent). A pytest pole fixes both: `H` = 0, `V` = 1. `V == H` is an advisory guard:
# the marker alone discriminates. `NOT_RED` are the pytest reasons for a guard that
# was never evaluated to a verdict of its own (a setup / teardown error, all skipped,
# a test defined in another file, another node's failure, no guard testcase in the
# report): unverified on either pole,
# never red, never green. A pytest pole's rc and its report must agree: a `<failure>` on
# the guard's own node at rc 0 (H) is `pytest-rc-mismatch` on either pole (R4c, G2g), e.g.
# committed conftest code forced the session's exit status. It is never green (the report
# says the guard failed) and never a RED's `red-guard-holds` (the rc alone says it held).
# At any other rc the rows below already read it as non-green (G2b/G2c/G3/G4) and a RED
# needs rc 1 besides (R3/R4/R6). An `<error>` is `pytest-error` (R4b/G2f) at every rc.
# Each table is ordered data
# `(row, predicate, result, reasons, repairable)`; the first match wins and the
# last row always matches, so both classifiers are total.

@dataclass(frozen=True)
class PoleRun:
    rc: int | None
    output: str = ""
    setup_error: str | None = None
    junit: str | None = None  # the pole's `--junitxml` report text (pytest poles only)
    source: str | None = None  # the guard file's text at S (pytest poles only)


DEFAULT_TYPES = frozenset({"AssertionError", "Failed"})
NOT_RED = frozenset({"pytest-error", "pytest-skipped", "pytest-foreign-file",
                     "pytest-other-node", "pytest-no-guard-case"})
# `pytest_result` reasons that come with the guard's own `<failure>` (None: exactly one, typed).
GUARD_FAILED = frozenset({None, "pytest-ambiguous", "pytest-no-type"})


class Facts:
    """Everything a row predicate reads about one pole run."""

    def __init__(self, run, pole: dict, rec: dict):
        self.rc = run.rc
        self.output = getattr(run, "output", "") or ""
        self.setup_error = getattr(run, "setup_error", None)
        self.pole = pole
        self.pytest = is_pytest_guard(rec["guard"])
        # A pytest pole's rc is the certifier's to read, never the record's (a record
        # `expect.exit` is `pytest-exit-supplied` before any run): H = 0, V = 1.
        self.h = 0 if self.pytest else rec["green"][0].get("expect", {}).get("exit", 0)
        self.v = 1 if self.pytest else rec["red"][0]["expect"].get("exit")
        v_value = self.v if self.v is not None else (1 if self.pytest else None)
        self.advisory = v_value is not None and v_value == self.h
        if self.pytest:
            self.ptype, self.preason, self.qual = pytest_result(
                getattr(run, "junit", None), rec["guard"], getattr(run, "source", None))
        else:
            self.ptype, self.preason, self.qual = None, None, qualifying_output(self.output)
        self.markers = [p["expect"].get("output_contains") for p in rec["red"]]
        self.marker = pole.get("expect", {}).get("output_contains")

    def matches_v(self) -> bool:
        if self.v is not None:
            return self.rc == self.v
        return self.rc == 1 if self.pytest else 0 < self.rc < 126

    def crash_rc(self) -> bool:
        return self.rc in (126, 127) or self.rc >= 128 or self.rc < 0

    def pytest_usage(self) -> bool:
        return self.pytest and 2 <= self.rc <= 5

    def no_junit(self) -> bool:
        return self.preason == "pytest-no-xml"

    def not_evaluated(self) -> bool:
        return self.preason in NOT_RED

    def rc_contradicts_report(self) -> bool:
        """A pytest pole at rc H (0) whose report has a `<failure>` on the guard's node."""
        return self.pytest and self.rc == self.h and self.preason in GUARD_FAILED

    def preason_list(self) -> list[str]:
        return [self.preason]

    def marker_in_qual(self) -> bool:
        return bool(self.marker) and self.marker in self.qual

    def red_marker_in_qual(self) -> bool:
        return any(m and m in self.qual for m in self.markers)

    def red_type_bad(self) -> bool:
        wanted = self.pole["expect"].get("exception")
        return self.ptype is None or self.ptype not in ({wanted} if wanted else DEFAULT_TYPES)

    def red_traceback_bad(self) -> bool:
        wanted = self.pole["expect"].get("exception")
        final = traceback_final_line(self.output) or ""
        return not wanted or traceback_type(self.output) != wanted or self.marker not in final


def _setup(f: Facts) -> list[str]:
    return [f"setup:{f.setup_error}"]


def _red_crash(f: Facts) -> list[str]:
    return ["red-crash"] + ([f.preason] if f.preason else [])


def _no_marker(f: Facts) -> list[str]:
    """R8; a pytest pole also names why (`pytest-no-failure`: the guard did not fail)."""
    return ["red-without-marker"] + ([f.preason] if f.preason else [])


RED_ROWS = [
    ("R1", lambda f: f.setup_error is not None, "unverified", _setup, True),
    ("R2", lambda f: f.rc is None, "unverified", ["red-timeout"], True),
    ("R3", Facts.crash_rc, "unverified", ["red-crash-rc"], False),
    ("R4", Facts.pytest_usage, "unverified", ["red-pytest-usage"], True),
    ("R4a", Facts.no_junit, "unverified", ["pytest-no-xml"], False),
    ("R4b", Facts.not_evaluated, "unverified", Facts.preason_list, False),
    ("R4c", Facts.rc_contradicts_report, "unverified", ["pytest-rc-mismatch"], False),
    ("R5", lambda f: not f.matches_v() and f.rc == f.h, "not-binding", ["red-guard-holds"], False),
    ("R6", lambda f: not f.matches_v(), "unverified", ["red-rc-unexpected"], False),
    ("R7", lambda f: not f.marker_in_qual() and f.advisory, "not-binding",
     ["red-advisory-silent"], False),
    ("R8", lambda f: not f.marker_in_qual(), "unverified", _no_marker, False),
    ("R9", lambda f: f.pytest and f.red_type_bad(), "unverified", _red_crash, False),
    ("R10", lambda f: not f.pytest and has_traceback(f.output) and f.red_traceback_bad(),
     "unverified", ["red-crash"], False),
    ("R11", lambda f: True, "red", [], False),
]

GREEN_ROWS = [
    ("G1", lambda f: f.setup_error is not None, "unverified", _setup, True),
    ("G2a", lambda f: f.rc is None, "unverified", ["green-crash"], True),
    ("G2b", Facts.crash_rc, "unverified", ["green-crash"], False),
    ("G2c", Facts.pytest_usage, "unverified", ["green-crash"], True),
    ("G2e", Facts.no_junit, "unverified", ["pytest-no-xml"], False),
    ("G2f", Facts.not_evaluated, "unverified", Facts.preason_list, False),
    ("G2g", Facts.rc_contradicts_report, "unverified", ["pytest-rc-mismatch"], False),
    ("G2d", lambda f: not f.pytest and has_traceback(f.output), "unverified",
     ["green-crash"], False),
    ("G3", lambda f: f.rc != f.h and f.matches_v() and (
        f.ptype in DEFAULT_TYPES if f.pytest else f.red_marker_in_qual()),
     "false-red", ["green-guard-violated"], False),
    ("G4", lambda f: f.rc != f.h, "unverified", ["green-crash"], False),
    ("G5", lambda f: f.red_marker_in_qual() and f.advisory, "false-red",
     ["green-advisory-flagged"], False),
    ("G6", Facts.red_marker_in_qual, "unverified", ["marker-not-discriminating"], False),
    ("G7", lambda f: bool(f.marker) and f.marker not in f.output, "unverified",
     ["green-assertion-miss"], True),
    ("G8", lambda f: True, "green", [], False),
]


def _classify(rows, run, pole, rec):
    facts = Facts(run, pole, rec)
    for _row, predicate, result, reasons, repairable in rows:
        if predicate(facts):
            found = reasons(facts) if callable(reasons) else list(reasons)
            return result, found, repairable
    raise AssertionError("unreachable: the last row always matches")


def classify_red(run, pole, rec):
    """`(result, reasons, repairable)` for one RED pole run (dd-certifier §2)."""
    return _classify(RED_ROWS, run, pole, rec)


def classify_green(run, pole, rec):
    """`(result, reasons, repairable)` for one GREEN pole run (dd-certifier §2)."""
    return _classify(GREEN_ROWS, run, pole, rec)


# --- claim status fold (Task 2.5) ------------------------------------------------------------

def _normalise(text: str) -> str:
    return " ".join(text.split())


def claim_status(poles, rec, guard_text):
    """Fold classified poles `(result, reasons, …)` into `(status, reasons)`.

    `not-binding` if any RED is; else `false-red` if any GREEN is; else
    `unverified` if any pole is (reasons unioned); else every pole binds →
    `known-bypass` iff `rec.bypass` is set and the guard text carries
    `KNOWN BYPASS: <bypass>` (whitespace-normalised) [F13] — set but absent →
    `unverified` (`bypass-undocumented`) — else `binds`. No poles → `unverified`.
    """
    poles = list(poles)
    if not poles:
        return "unverified", ["no-poles"]
    for terminal in ("not-binding", "false-red", "unverified"):
        hits = [p for p in poles if p[0] == terminal]
        if hits:
            return terminal, list(dict.fromkeys(r for p in hits for r in p[1]))
    bypass = rec.get("bypass")
    if not bypass:
        return "binds", []
    documented = _normalise(f"KNOWN BYPASS: {bypass}") in _normalise(guard_text or "")
    return ("known-bypass", []) if documented else ("unverified", ["bypass-undocumented"])
