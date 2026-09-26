"""junit_verdict.py — judge declared pytest targets by a ``--junitxml`` report, per node.

design: local-implement-and-review (operator rulings on PR #165, amendments A29–A31)

The one verdict source for ``task_verify`` step 6, red-at-base and the Tier 3.5 re-run.
The pytest exit code says nothing about a declared target (a missing node under xdist
exits 5, a conftest can rewrite the status); the report does. We build the input: every
judged run holds exactly **one** declared target (`run_judged`; pytest aborts a whole
session over one target: a node not found, a module skipped at collection) and appends
`report_args` after it, so the report is ours, fresh, and in one shape whatever the
repo's config (xdist or not):

* ``--junitxml=<tmp>/report.xml`` in a fresh temp dir outside the tree (`run_judged`);
* ``-o junit_family=xunit1``: every ``<testcase>`` carries ``file`` (the file that
  *defines* the test, relative to pytest's rootdir) beside ``classname`` and ``name``;
* ``--junit-prefix=`` (no classname prefix) and ``-o junit_logging=no`` (no captured
  output in the report). The rootdir and config are **never** forced: pytest resolves
  them exactly as in the repo's own runs (a package-level ``pytest.ini`` included).

**The rootdir** (`resolve`) is the one directory, among the run's cwd and every
directory from it down to a declared target, under which every recorded ``.py``
``file`` exists. No such directory → ``rootdir-unknown``; several that place any case
differently → ``rootdir-ambiguous``: both ``unverified``, never a pass.

**Matching is by file.** A case's path is its ``file`` resolved against that rootdir,
made relative to the cwd. Its class path is read from ``classname`` only *within* that
file: ``classname``'s module path must be exactly the file's (``a/b/test_x.py`` →
``a.b.test_x``), then ``.Class`` segments whose leading ones name no path beside it,
joined by ``/`` or ``.`` (``a/b/test_x/Seg``, ``a/b/test_x.Seg``, file or directory,
absent), then its ``name`` (with any ``[param]``). A file whose module path is
ambiguous (a segment holding ``.``: ``a/b.v2/test_x.py`` reads as ``a.b.v2.test_x``,
like ``a/b/v2/test_x.py``) has no exact module path: its cases are foreign. A
collection error is its collector's case (``classname=""``, ``name`` the module → the
file itself). A case with no ``file``, outside the tree, or collected from another
module (an inherited method, an imported function, a re-collected ``from test_a import
*``, a dotted-directory ``tests/test_a.v2/test_b.py`` re-collecting ``tests/test_a.py``)
is **foreign**: it matches no target and never counts toward a pass, and a failure of
it blocks a pass.

**Per target** (`judge`): a declared file absent from the tree → ``missing``
(``file-missing``). Else the cases *of* a target are those at it or inside it (a class
holds its methods; ``test_x`` holds every ``test_x[...]``; ``test_x[a]`` only itself; a
file target holds every case of the file) plus its collectors (the file's or an
enclosing class's case). Any failed/errored → ``red`` (``collection-error`` when only
collectors failed); none → ``unverified`` (``node-absent``, or ``file-no-tests`` for a
file target: the repo's config may deselect it, so it is never case f); a node target
passes only if every case passed; a file target with at least one pass and no failure;
otherwise (skips) → ``unverified``. Each target's verdict comes from its own run's
report; a task's (or a report's) targets combine with the most severe winning
(`verdict`), so no skip, abort or absent node in one target masks another.

**The report** (`parse`) is read with stdlib ``xml.etree``, strictly: missing, empty,
carrying a DTD, not XML, not rooted at ``testsuites``/``testsuite``, or a ``testcase``
without ``classname``/``name`` → None, which every consumer reads as ``unverified``.
Stdlib only.
"""
from __future__ import annotations

import itertools
import os
import re
import tempfile
import xml.etree.ElementTree as ET

_DTD = re.compile(r"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_BAD = ("failure", "error")


def report_args(report: str) -> list[str]:
    """The flags every judged run appends after its targets (module docstring)."""
    return [f"--junitxml={report}", "-o", "junit_family=xunit1", "--junit-prefix=",
            "-o", "junit_logging=no"]


def _outcome(testcase) -> str:
    tags = {child.tag for child in testcase}
    if tags & set(_BAD):
        return "failed"
    return "skipped" if "skipped" in tags else "passed"


def parse(report) -> list[tuple] | None:
    """``[(file or None, classname, name, passed|failed|skipped)]`` per ``<testcase>``,
    or None when the report is missing or malformed (module docstring)."""
    try:
        with open(report, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return None
    if not text.strip() or _DTD.search(text):
        return None
    try:
        root = ET.fromstring(text)  # nosec B314 — DTD-free input only (checked above)
    except ET.ParseError:
        return None
    if root.tag not in ("testsuites", "testsuite"):
        return None
    cases = []
    for testcase in root.iter("testcase"):
        classname, name = testcase.get("classname"), testcase.get("name")
        if classname is None or name is None:
            return None
        path = (testcase.get("file") or "").replace(os.sep, "/") or None
        cases.append((path, classname, name, _outcome(testcase)))
    return cases


def _path(target: str) -> str:
    """A declared target's file, normalised (``./a//b.py`` → ``a/b.py``)."""
    return os.path.normpath(target.partition("::")[0]).replace(os.sep, "/")


def _roots(cwd: str, targets) -> list[str]:
    """The rootdir candidates: ``cwd`` and every directory from it to a target's file."""
    roots = [cwd]
    for target in targets:
        parts = _path(target).split("/")[:-1]
        for i in range(1, len(parts) + 1):
            if parts[i - 1] in ("", ".", ".."):
                break
            roots.append(os.path.join(cwd, *parts[:i]))
    return list(dict.fromkeys(roots))


def _module(path: str) -> str | None:
    """A recorded ``.py`` file's module path (``a/b/test_x.py`` → ``a.b.test_x``), or
    None when it is ambiguous: a segment holding ``.`` (``a/b.v2/test_x.py``) reads the
    same dotted as a slashed path, so no classname can be matched to it exactly."""
    parts = path[:-3].split("/")
    if any(not part or "." in part for part in parts):
        return None
    return ".".join(parts)


_DEPTH = 6  # class segments probed; a deeper classname is foreign (fail closed)


def _beside(stem: str, classes: list[str]) -> bool:
    """Some leading ``classes`` segments name a path beside the file ``<stem>.py``,
    joined by ``/`` or ``.`` at each step (``stem/v2/test_b``, ``stem.v2/test_b``, a
    file or a directory): the classname's module is then not the file's."""
    if len(classes) > _DEPTH:
        return True
    for k in range(1, len(classes) + 1):
        for joins in itertools.product("/.", repeat=k):
            probe = stem + "".join(j + seg for j, seg in zip(joins, classes[:k]))
            if os.path.exists(probe) or os.path.exists(probe + ".py"):
                return True
    return False


def _node(case, root: str, cwd: str) -> str | None:
    """The case's node id ``path::A::name[param]`` relative to ``cwd`` (a collector:
    ``path``) under rootdir ``root``, or None when it is foreign (module docstring)."""
    path, classname, name, _outcome = case
    if not path or not path.endswith(".py"):
        return None
    full = os.path.normpath(os.path.join(root, path))
    rel = os.path.relpath(full, cwd).replace(os.sep, "/")
    if rel == ".." or rel.startswith("../"):
        return None
    module = _module(path)
    if module is None:
        return None
    if classname == "" and name == module:
        return rel
    if classname == module:
        classes = []
    elif classname.startswith(module + "."):
        classes = classname[len(module) + 1:].split(".")
        if _beside(full[:-3], classes):
            return None
    else:
        return None
    return "::".join([rel, *classes, name])


def resolve(cases: list, targets, cwd) -> tuple[list | None, str]:
    """``cases`` → ``([(node id or None, outcome)], "")`` under the one rootdir the
    report fits, or ``(None, rootdir-unknown|rootdir-ambiguous)`` (module docstring)."""
    cwd = os.path.realpath(str(cwd))
    files = {c[0] for c in cases if c[0] and c[0].endswith(".py")}
    roots = [r for r in _roots(cwd, targets)
             if all(os.path.isfile(os.path.normpath(os.path.join(r, f))) for f in files)]
    if not files:
        roots = [cwd]  # nothing to place: every case is foreign under any rootdir
    if not roots:
        return None, "rootdir-unknown"
    placed = [[(_node(c, r, cwd), c[3]) for c in cases] for r in roots]
    if any(p != placed[0] for p in placed[1:]):
        return None, "rootdir-ambiguous"
    return placed[0], ""


def _split(node: str) -> tuple[str, list[str], str]:
    """``path::A::b[p]`` → ``(path, [A, b], "[p]")``."""
    path, _, rest = node.partition("::")
    base, bracket, param = rest.partition("[")
    return path, [s for s in base.split("::") if s], bracket + param


def _relation(node: str, target: str) -> str | None:
    """``"in"`` (at or inside ``target``), ``"collector"`` (an enclosing collector), or None."""
    path, segs, param = _split(node)
    t_path, t_segs, t_param = _split(target)
    if path != _path(t_path):
        return None
    if segs[:len(t_segs)] == t_segs and (not t_param or (segs, param) == (t_segs, t_param)):
        return "collector" if not segs else "in"
    if not param and len(segs) < len(t_segs) and t_segs[:len(segs)] == segs:
        return "collector"
    return None


def judge(nodes: list, target: str, *, exists: bool = True) -> tuple[str, str]:
    """One declared target → ``(pass|red|missing|unverified, reason)`` from resolved
    ``nodes``; ``exists``: its file is in the tree (module docstring)."""
    if not exists:
        return "missing", "file-missing"
    mine = [(rel, outcome) for node, outcome in nodes if node
            for rel in [_relation(node, target)] if rel]
    failed = [rel for rel, outcome in mine if outcome == "failed"]
    if failed:
        return "red", "collection-error" if set(failed) == {"collector"} else "red"
    if not mine:
        return "unverified", "node-absent" if "::" in target else "file-no-tests"
    outcomes = [outcome for _rel, outcome in mine]
    if "::" not in target:
        ok = "passed" in outcomes
    else:
        ok = all(outcome == "passed" for outcome in outcomes)
    return ("pass", "") if ok else ("unverified", "skipped")


def verdict(cases: list | None, targets, cwd) -> tuple[str, str]:
    """Declared ``targets`` judged from one report in ``cwd`` → ``(pass|red|missing|
    unverified, reason)``, each target judged on its own, the most severe winning: a
    declared file absent from the tree (``missing``, case f), else the first red, else a
    failed case matching no target (``foreign-failure``), else the first unverified
    target, else pass. No report, or no rootdir it fits → unverified. Every judged run
    holds one target (`run_judged`); a task's targets combine the same way over their
    own runs."""
    if not targets:
        return "unverified", "no-targets"
    if any(not os.path.isfile(os.path.join(str(cwd), _path(t))) for t in targets):
        return "missing", "file-missing"
    if cases is None:
        return "unverified", "no-report"
    nodes, why = resolve(cases, targets, cwd)
    if nodes is None:
        return "unverified", why
    judged = [judge(nodes, t) for t in targets]
    hit = next((j for j in judged if j[0] == "red"), None)
    if hit:
        return hit
    if any(outcome == "failed" and not any(node and _relation(node, t) for t in targets)
           for node, outcome in nodes):
        return "unverified", "foreign-failure"
    return next((j for j in judged if j[0] != "pass"), ("pass", ""))


def run_judged(run, target: str, cwd):
    """``run(extra_args, [target])`` in ``cwd`` with `report_args` for a fresh report in
    a temp dir (removed after) → ``(run's result, verdict(parse(report), [target],
    cwd))``. Exactly one declared target per run, everywhere: pytest aborts a whole
    session over one target (a node not found, a module skipped at collection), so a
    shared run would let one target mask another. The caller combines its targets'
    verdicts, the most severe winning."""
    if not isinstance(target, str):
        raise TypeError("run_judged judges exactly one declared target per run")
    with tempfile.TemporaryDirectory(prefix="tp-junit-") as tmp:
        report = os.path.join(tmp, "report.xml")
        result = run(report_args(report), [target])
        return result, verdict(parse(report), [target], cwd)
