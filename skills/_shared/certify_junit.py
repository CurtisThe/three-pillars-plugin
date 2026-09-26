"""certify_junit — read a pytest pole's result from its `--junitxml` report [R6].

design: audit-pass-does-not-bind (detailed-design-certifier.md §2 [R6], amended
2026-09-25 by the PR #162 remediation, the report replaces console `FAILED` lines, by the
allowlist ruling: only a `<failure>` on the declared node is red, by the config
ruling: a testcase is the guard's by its exact file, never by a dotted name, and by the
alias ruling: the guard file's own definition at its line, sub-note (h)).

The runner builds every pytest pole's command itself (`certify_argv.pytest_command`):
the claim's declared guard, anchored as `./<path>[::<node>]`, is the only target, with
`--junitxml=<pole dir>/junit.xml`, `--rootdir` and `--confcutdir` pinned to the resolved
pole tree, `-o addopts=` (no repo config adds a target, an option or a plugin) and
`-o junit_family=xunit1`, so every `<testcase>` carries `file` and `line` attributes:
the tree-relative path of the file that defines the test and the 0-based first line of
its definition (pytest's `item.location`). The
report is read structurally, stdlib only (`xml.etree.ElementTree`). `parse(xml)` returns
one case per outcome of every `<testcase>`: `failure`, `error`, `skipped`, or `passed`
when it carries none of those; None when the report is missing, unparseable or carries a
DTD (pytest writes none).

**Which testcases are the guard's.** The dotted classname does not encode the node chain
(a module `tests/t/test_x.py` that committed conftest code adds as a target spells
`tests.t.test_x`, like a class `test_x` of `tests/t.py`, and a function it imports from
`tests/t.py` reports `file=tests/t.py`), so a case is the guard's only when ALL of:
  * its `file` is exactly the guard's path (string equality, no normalising beyond the
    platform separator): `tests/t/test_x.py` is never `tests/t.py`, `test_g/Test_test.py`
    never `test_g.py`, `test_a/test_b.py` never `test_a.test_b.py`;
  * its classname is the guard path's module (the path with `/` → `.` and `.py` dropped,
    pytest's own `mangle_test_address`) or starts with it plus `.`; the rest, split on
    `.`, is the claimed class chain, and the name without its `[param]` the test name;
  * the guard file's own text at S (`source`, the certifier passes it; the guard file is
    never a subject, so no pole rewrites it) defines that chain and test at the case's
    xunit1 `line` (`certify_pynode.defines`: each class nested in the one before, the
    test a `def` of the innermost class or its in-file bases, or of the module, whose
    first line is the reported one). An alias, a helper imported under a test's name, a
    module whose dotted path fakes a class chain: each reports another line or names a
    non-class, and is never the guard's;
  * its segments `[*classes, name]` are the declared node or inside it: a guard with a
    `[param]` names the case with the same segments and param; a guard without one names
    every parametrization of its segments and, for a class, every case collected under
    it (`f.py::TestK` holds `TestK::test_m` and `TestK::TestIn::t`, never the sibling
    `TestKX::test_m`); a function has no case under it but its own `[param]` ids; a path
    guard names every case its file defines.
A case with no `file` or `line`, or checked without `source` (a report or a call the
certifier did not shape), is never the guard's; named like it, it reads as foreign.
`file` is where the test is *defined*, not where it is collected: a test collected from
the guard file but defined in another one (a method inherited from a base class in
another module, a function imported into the guard file, a decorator without
`functools.wraps` defined elsewhere) reports that other file, and one defined elsewhere
in the guard file (a helper aliased under a test's name) another line. Neither is ever
the guard's case: it fails closed, its failure is never red (reason
`pytest-foreign-file`), and a guard whose only cases are such tests is never evaluated.
A test decorated with `functools.wraps` reports the file and line of the function it
wraps (the guard's own, when that function is the declared `def`).

`guard_result(cases, guard, source)` → `(failures, reason)`. Only a `<failure>` on a guard case
counts (one per testcase id; a call failure beside its teardown error is one failure).
With none, the reason says why, in this order:
  * `pytest-error`: a guard case has an `<error>` (a setup or teardown error, e.g. a
    module fixture's teardown reported on the last item), never red;
  * `pytest-skipped`: every guard case was skipped (could not evaluate);
  * `pytest-foreign-file`: a case named like the guard's node (classname and name) that
    is not the guard's (another `file`, or no definition of it at its `line`) failed or
    errored, or no guard case ran but such a case did;
  * `pytest-other-node`: some other testcase failed or errored, never the guard's;
  * `pytest-no-guard-case`: no testcase of the report is the guard's (it never ran:
    could not evaluate, never green even at rc 0);
  * `pytest-no-failure`: a guard case ran and passed.

`failure_type(case)`: an explicit `type` attribute when the pytest version writes
one; else the exception name heading the `message` (`KeyError: 'k'` → `KeyError`,
`Failed: …` → `Failed`, a dotted name keeps its last part); a message that is an
assertion-rewrite explanation (`assert …`) is `AssertionError`. Anything else → None.
`message` (the attribute) is the failure text a RED marker must appear in.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import certify_pynode
from certify_argv import guard_parts

OUTCOME_TAGS = ("failure", "error", "skipped")
TYPE_NAME = re.compile(r"^([A-Za-z_][\w.]*)(?::\s|:$|$)")
_DTD = re.compile(r"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)


@dataclass(frozen=True)
class Case:
    classname: str
    name: str
    kind: str  # "failure" | "error" | "skipped" | "passed"
    message: str = ""
    type: str | None = None
    file: str | None = None  # xunit1 `file`: the tree-relative file defining the test
    line: int | None = None  # xunit1 `line`: the definition's 0-based first line

    @property
    def node(self) -> str:
        """`classname.name`: the case's dotted id, for evidence and ambiguity reports."""
        return ".".join(p for p in (self.classname, self.name) if p)


def parse(xml_text: str | None) -> list[Case] | None:
    """Every testcase outcome of the report, or None when it is unreadable.

    pytest never writes a DTD, so a report carrying one (the vector of the entity-
    expansion and external-entity XML attacks) is unreadable, never parsed."""
    if not xml_text or _DTD.search(xml_text):
        return None
    try:
        root = ET.fromstring(xml_text)  # nosec B314 — DTD-free input only (checked above)
    except ET.ParseError:
        return None
    cases = []
    for testcase in root.iter("testcase"):
        ids = (testcase.get("classname") or "", testcase.get("name") or "")
        where = (testcase.get("file"), _line(testcase.get("line")))
        found = [Case(*ids, child.tag, child.get("message") or "", child.get("type"), *where)
                 for child in testcase if child.tag in OUTCOME_TAGS]
        cases.extend(found or [Case(*ids, "passed", "", None, *where)])
    return cases


def _line(text: str | None) -> int | None:
    return int(text) if text is not None and text.isascii() and text.isdigit() else None


def _split_param(name: str) -> tuple[str, str]:
    base, bracket, rest = name.partition("[")
    return base, bracket + rest


def module_name(path: str) -> str:
    """pytest's classname spelling of a test file path (`mangle_test_address`)."""
    return re.sub(r"\.py$", "", path.replace("/", "."))


def _file(case: Case) -> str | None:
    return case.file.replace(os.sep, "/") if case.file and os.sep != "/" else case.file


def _segments(case: Case, path: str) -> tuple[list[str], str] | None:
    """`([*classes, name], param)` of the case's node id under `path`'s module, or None
    when its classname is not that module (module docstring)."""
    module = module_name(path)
    if case.classname == module:
        classes = []
    elif case.classname.startswith(module + "."):
        classes = case.classname[len(module) + 1:].split(".")
    else:
        return None
    base, param = _split_param(case.name)
    return [*classes, base], param


def _names(case: Case, guard: str) -> bool:
    """The case's dotted id reads as the guard's node or inside it (its claimed chain
    only: neither its file nor its definition is checked here)."""
    path, node = guard_parts(guard)
    found = _segments(case, path)
    if found is None:
        return False
    segments, case_param = found
    base, param = _split_param(node or "")
    wanted = [n for n in base.split("::") if n] if node else []
    if param:
        return segments == wanted and case_param == param
    return segments[:len(wanted)] == wanted


def _defined(case: Case, guard: str, source: str | None) -> bool:
    """The guard file's text defines the case's claimed chain and test at its `line`."""
    segments, _param = _segments(case, guard_parts(guard)[0])
    return certify_pynode.defines(source, segments[:-1], segments[-1], case.line)


def matches(case: Case, guard: str, source: str | None) -> bool:
    """True when `guard` names `case`: its exact file, its node, and the guard file's own
    definition of it at its line (module docstring). `source` is the guard file's text."""
    return (_file(case) == guard_parts(guard)[0] and _names(case, guard)
            and _defined(case, guard, source))


def _foreign(case: Case, guard: str, source: str | None) -> bool:
    """A case named like the guard's node that is not the guard's (module docstring)."""
    return _names(case, guard) and not matches(case, guard, source)


def guard_result(cases: list[Case], guard: str,
                 source: str | None) -> tuple[list[Case], str | None]:
    """`(failures, reason)`: the guard's `<failure>` cases, one per testcase id, or `([],
    reason)` naming why none counts as red (module docstring). `source` is the guard
    file's text at S; without it no case is the guard's."""
    mine = [case for case in cases if matches(case, guard, source)]
    foreign = [case for case in cases if _foreign(case, guard, source)]
    failures: dict[tuple[str, str], Case] = {}
    for case in mine:
        if case.kind == "failure":
            failures.setdefault((case.classname, case.name), case)
    if failures:
        return list(failures.values()), None
    if any(case.kind == "error" for case in mine):
        return [], "pytest-error"
    if mine and all(case.kind == "skipped" for case in mine):
        return [], "pytest-skipped"
    if any(case.kind in ("failure", "error") for case in foreign) or (foreign and not mine):
        return [], "pytest-foreign-file"
    if any(case.kind in ("failure", "error") for case in cases):
        return [], "pytest-other-node"
    if not mine:
        return [], "pytest-no-guard-case"
    return [], "pytest-no-failure"


def _type_name(text: str) -> str | None:
    match = TYPE_NAME.match(text.strip())
    return match.group(1).rsplit(".", 1)[-1] if match else None


def failure_type(case: Case) -> str | None:
    """The exception type of one failure (module docstring), or None."""
    if case.type:
        return case.type.rsplit(".", 1)[-1]
    message = case.message.strip()
    if message == "assert" or message.startswith("assert "):
        return "AssertionError"
    return _type_name(message.splitlines()[0]) if message else None
