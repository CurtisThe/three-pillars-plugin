"""The FLOOR the atom scanner may never go below — and the proof it is independent.

`test_verify_superset.py` asserts `atoms(text)` contains everything a deliberately markdown-BLIND
scan finds. That assertion is only worth anything if the blind scan is written independently of
the module it judges. It was not: `_naive_atoms` documented itself as "reproduced here rather than
imported so that a future 'simplification' of `verify_atoms` cannot quietly move the floor with
it", and then matched against `verify_atoms`'s OWN compiled regexes. Narrowing `ENTRY` in the
module would have narrowed the floor in lockstep and the superset assertion would have stayed
green while real lines left the inventory — exactly the drift it claimed to defend against.

So the floor lives here, with its shapes TYPED OUT, and two drift tests compare those literals
against `verify_atoms.py`'s and `origin/master`'s declarations AS SOURCE TEXT (via `ast`, never
by importing). A future change to a shape then fails loudly in two places at once instead of
travelling silently into the floor.

WHAT THIS MODULE PINS, AND WHAT IT DOES NOT
===========================================
Stated flatly because four prior docstrings in this suite asserted safety properties the code did
not have, and an accurate statement of limits is worth more than an optimistic one.

PINNED. The atom SHAPES, as SOURCE TEXT: the regex literals `_FLOOR_SHAPES` declares must match
`verify_atoms.py`'s module-level `re.compile(...)` declarations character for character, and the
three master-era shapes must match `origin/master`'s. Read via `ast`, never imported, so a runtime
monkeypatch cannot satisfy them. Plus the FLOOR itself: `_naive_atoms` is an independent scan whose
output `atoms()` must contain (asserted in `test_verify_superset.py`).

NOT PINNED. The block scan's CONTROL FLOW — the `_close()` / `open_block` loop. Both drift tests
compare regex literals only; round 7's bug was a control-flow change that touched no regex at all,
and round 8's was a change of WHERE an unchanged regex was applied (its region walk paired brackets
across entry boundaries and matched prose that merely quoted them — round 9, which is why the walk
no longer exists). A further defect of that shape would pass both drift tests. It is caught
only if it manifests on a document already in `ADVERSARIAL` or in the real corpus — i.e. by the
superset and coverage properties over a FIXED population, not by any proof about the space of
control flows. `_naive_atoms` re-derives that control flow by hand as a partial hedge (a divergence
between the two shows up as a superset failure), but two independently typed-out implementations of
the same rule are not a proof that the rule is right; they only catch one of them changing alone.

Widening `ADVERSARIAL` is therefore the only lever that actually moves this boundary. Every round
that found a defect added the document that exposed it.
"""
import ast
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from verify_atoms import _esc, _norm  # noqa: E402

# ---- The floor's shapes, TYPED OUT ------------------------------------------------------------
# Byte-identical to `origin/master`'s `ENTRY`/`ROW`/`LOG` and to this branch's `DECISION_ENTRY`
# today — pinned as source text by the two drift tests at the bottom of this module. They are the
# WHOLE shape set now: literals, not imports, so a narrowing of the module's regexes fails the
# superset assertion instead of silently travelling with it.
#
# `_norm` and `_esc` ARE still imported, deliberately: they are the SIGNATURE CONVENTION (how a
# matched line is spelled as a string), not the floor (which lines count as structure). The floor
# is a claim about line SELECTION, and comparing two atom sets requires both sides to spell
# signatures the same way — a re-typed `_norm` would make every signature differ and the assertion
# would compare nothing. A change to `_norm` moves both sides identically and so cannot hide a
# subtraction; a change to a SHAPE moves only the module, which is what these literals catch.
_F_ENTRY = re.compile(r"^### [A-Z]\d+:\s*(.*)$")
_F_ROW = re.compile(r"^\|\s*[A-Z]\d+\s*\|\s*([^|]+?)\s*\|")
_F_LOG = re.compile(r"^-\s+(\*\*(?:`[a-z0-9][a-z0-9-]*`|\d{4}-\d{2}-\d{2})\*\*\s+—.*)$")
_F_DECISION_ENTRY = re.compile(r"^### \[([^\]\s][^\]]*)\]\s+(.+)$")
# No `_F_CONFLICT_*` here any more, and no re-derived stripper either: round 9 deleted the marker
# strip from `verify_atoms.py` outright (three formulations, three silent drops — see that module's
# header). A floor for a scanner that removes no line needs no marker shapes; the four literals and
# the `_f_decoration_indices` / `_f_strip_decoration` twins that mirrored the strip went with it.

# `origin/master` had only the first three (no decision-entry atom) when this floor was written; the
# drift test against master requires those three and allows the fourth only as the floor's literal.
_MASTER_SHAPES = ("ENTRY", "ROW", "LOG")
_FLOOR_SHAPES = {
    "ENTRY": _F_ENTRY.pattern, "ROW": _F_ROW.pattern, "LOG": _F_LOG.pattern,
    "DECISION_ENTRY": _F_DECISION_ENTRY.pattern,
}
# `LOG` is the one floor shape the module has WIDENED since (plain-date bullets, `- 2026-10-16 — …`,
# basesync-generator-catalog 4.1). The floor keeps master's original spelling, so the superset
# assertion still proves the widened `atoms()` loses nothing master caught; the module and a
# post-merge master are held to the widened spelling instead.
_WIDENED_SHAPES = {
    "LOG": (r"^-\s+((?:\*\*(?:`[a-z0-9][a-z0-9-]*`|\d{4}-\d{2}-\d{2})\*\*|\d{4}-\d{2}-\d{2})"
            r"\s+—.*)$"),
}
# Branch-local by construction: everything this branch ADDS to master's three atom kinds. Since
# round 9 deleted the marker strip that is exactly one name — the decision-entry atom. The former
# `CONFLICT_*` shape names went with the strip and are NOT listed here any more: naming a shape
# that no longer exists on either side asserts nothing.
_BRANCH_LOCAL_SHAPES = ("DECISION_ENTRY",)


def _naive_atoms(text):
    """A deliberately markdown-BLIND atom scan — the floor `atoms()` may never go below.

    The per-line half is `origin/master`'s `atoms()`, verbatim: three regexes over RAW lines, no
    conflict-marker strip, no fence mask, no zones. Both halves match against the `_F_*` literals
    typed out at the top of this module, NOT against `verify_atoms`'s objects — that is what makes
    this a floor rather than a mirror (see the module docstring).

    The `decision-entry` half removes NO line — not even a conflict marker — and applies the
    simplest block rule there is: a body runs from its heading to the next entry-shaped heading or
    EOF. No fence awareness, no heading-level judgement (the level rule SHORTENED bodies and
    orphaned their tails, round 7), and since round 9 no marker strip either (it removed real
    content from digests three formulations running).
    """
    out = set()
    for line in text.splitlines():                         # master's scan, unchanged
        m = _F_ENTRY.match(line)
        if m and _norm(m.group(1)):
            out.add(("entry", _norm(m.group(1))))
            continue
        m = _F_ROW.match(line)
        if m and _norm(m.group(1)):
            out.add(("row", _norm(m.group(1))))
            continue
        m = _F_LOG.match(line)
        if m and _norm(m.group(1)):
            out.add(("log", _norm(m.group(1))))

    lines = text.splitlines()                              # nothing is removed, markers included
    open_block, body = None, []

    def _close():
        if open_block is not None:
            import hashlib
            nonblank = sum(1 for ln in body if ln.strip())
            digest = hashlib.sha1(
                f"{nonblank}\x00{_norm(' '.join(body))}".encode("utf-8"),
                usedforsecurity=False).hexdigest()[:12]
            out.add(("decision-entry",
                     f"{_esc(open_block[0])}|{_esc(open_block[1])}|{digest}"))

    for line in lines:
        m = _F_DECISION_ENTRY.match(line)
        if m and _norm(m.group(1)) and _norm(m.group(2)):
            _close()
            open_block, body = (_norm(m.group(1)), _norm(m.group(2))), []
            continue
        if open_block is not None:
            body.append(line)
    _close()
    return out



# ---- Drift from the floor is LOUD ------------------------------------------------------------

_MODULE_SRC = os.path.join(os.path.dirname(__file__), "verify_atoms.py")
# The atom shapes live in `verify.py` on master before this branch lands and in `verify_atoms.py`
# after (this branch moved them). The provenance check reads BOTH, so it is correct on either side
# of the merge (F6: reading `verify.py` alone found no shapes at all once the move reached master).
_SCANNER_SRCS = ("skills/tp-merge-from-main/scripts/verify_atoms.py",
                 "skills/tp-merge-from-main/scripts/verify.py")
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _declared_patterns(source):
    """{NAME: pattern string} for every module-level `NAME = re.compile(r"...")` in `source`.

    Reads SOURCE TEXT via `ast` and never imports, so it works on a blob from another commit and
    cannot be satisfied by a runtime monkeypatch.
    """
    out = {}
    for node in ast.parse(source).body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        call = node.value
        if (isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "compile"
                and call.args and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)):
            out[node.targets[0].id] = call.args[0].value
    return out


def test_the_floor_shapes_have_not_drifted_from_the_module_under_test():
    """The floor is typed out, so it CAN diverge from `verify_atoms` — this makes divergence loud.

    If a future change narrows one of the module's shapes, the superset assertion above fails
    (real lines leave the inventory while the floor still sees them) AND this test fails naming
    the shape. Widening is equally reported. Either way the change is a decision someone has to
    make deliberately, which is precisely what importing the regexes made impossible.
    """
    with open(_MODULE_SRC, encoding="utf-8") as fh:
        declared = _declared_patterns(fh.read())
    expected = {**_FLOOR_SHAPES, **_WIDENED_SHAPES}
    drift = {name: (pat, declared.get(name)) for name, pat in expected.items()
             if declared.get(name) != pat}
    assert not drift, (
        "verify_atoms.py's shapes no longer match this module's inlined floor. If the change is "
        f"intended, retype the literal here and say why in the commit: {drift}")
    # The DELETION, pinned as source text. Round 9 removed the marker strip and its regexes; a
    # future round that re-declares one has to delete this assertion first, in the open, rather
    # than reintroduce a line-removing step under a new name and stay green.
    reintroduced = [n for n in declared if "CONFLICT" in n]
    assert not reintroduced, (
        "verify_atoms.py declares a conflict-marker shape again. The scanner strips NOTHING — "
        "three formulations of that strip each hid real content from a digest (module header). "
        f"If a strip is genuinely wanted, argue it in the commit: {reintroduced}")


def _git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True,
                       cwd=os.path.dirname(_MODULE_SRC))
    return r.stdout if r.returncode == 0 else None


def _git_show(ref_path):
    return _git("show", ref_path)


def _master_ref_is_expected():
    """Is this a checkout where `origin/master` SHOULD resolve?

    A `pytest.skip` is visible to a human reading the summary but INDISTINGUISHABLE from a pass by
    exit code, which is all an automated gate sees — and this suite now runs in the gate
    (`scripts/ci-local.sh`). So the skip is confined to checkouts that genuinely cannot have the
    ref: no git, no `origin`, or a shallow clone. Anywhere else the ref is expected and its
    absence is a FAILURE, not a skip.

    `TP_REQUIRE_MASTER_REF=1` forces the strict answer for a gate that wants to assert the check
    really ran (CI sets it alongside a full-depth checkout); `=0` forces the lenient one for a
    deliberately degraded environment.
    """
    forced = os.environ.get("TP_REQUIRE_MASTER_REF")
    if forced in ("0", "1"):
        return forced == "1"
    remotes = _git("remote")
    if remotes is None or "origin" not in remotes.split():
        return False
    shallow = _git("rev-parse", "--is-shallow-repository")
    return shallow is not None and shallow.strip() == "false"


def _declared_at(read):
    """`{NAME: {pattern, ...}}` over every scanner module `read(path)` returns source for, or None
    when it returns none of them. A name declared in two modules keeps every spelling it has."""
    sources = [src for src in map(read, _SCANNER_SRCS) if src is not None]
    if not sources:
        return None
    out = {}
    for src in sources:
        for name, pat in _declared_patterns(src).items():
            out.setdefault(name, set()).add(pat)
    return out


def _provenance_drift(declared):
    """Every way a ref's declared shapes contradict the floor — `[]` when they agree.

    Master's three shapes must each be declared with exactly one spelling: the floor's literal. The
    branch-local shape may be ABSENT (master before this branch lands) or present as the floor's
    literal (master after); present with any other spelling means the floor needs re-deriving."""
    drift = [f"{name}: {sorted(declared.get(name, ()))!r} != {[_FLOOR_SHAPES[name]]!r}"
             for name in _MASTER_SHAPES
             if declared.get(name) not in ({_FLOOR_SHAPES[name]}, {_WIDENED_SHAPES.get(name)})]
    drift += [f"{name}: {sorted(declared[name])!r} != {[_FLOOR_SHAPES[name]]!r}"
              for name in _BRANCH_LOCAL_SHAPES
              if name in declared and declared[name] != {_FLOOR_SHAPES[name]}]
    return drift


def test_the_floor_shapes_have_not_drifted_from_origin_master():
    """The floor's provenance, asserted rather than asserted-in-a-comment: `ENTRY`/`ROW`/`LOG` are
    `origin/master`'s, character for character. Master is the last scanner known to catch every
    repro in `ADVERSARIAL`, so "at least as good as master" needs master's shapes to be pinned,
    not merely claimed. A deliberate future change to a shape on master fails here loudly.

    A missing ref is a FAILURE wherever the ref is expected — a full clone with an `origin`
    remote, or `TP_REQUIRE_MASTER_REF=1`. It skips only where the ref genuinely cannot exist
    (no git, no remote, shallow clone), because an exit-code-only gate cannot tell a skip from a
    pass and this suite is now inside the gate. The module-source test above always runs.
    """
    declared = (_declared_at(lambda p: _git_show(f"origin/master:{p}"))
                or _declared_at(lambda p: _git_show(f"master:{p}")))
    if declared is None:
        if _master_ref_is_expected():
            pytest.fail(
                f"origin/master is expected in this checkout but none of {_SCANNER_SRCS} read "
                "from origin/master or master — the floor's provenance check did NOT run. Fetch "
                "master, or set TP_REQUIRE_MASTER_REF=0 if this environment is deliberately "
                "degraded.")
        pytest.skip("SKIPPED-NOT-RUN: origin/master unavailable (no remote / shallow clone) — "
                    "the floor's provenance against master was NOT checked")
    assert not _provenance_drift(declared), _provenance_drift(declared)


def test_the_provenance_check_still_passes_once_this_branch_is_master():
    """F6, proven rather than argued: run the same check against a "master" that IS this branch —
    the state `origin/master` is in the moment this PR lands. Read from the working tree, so it
    tests the code under review rather than a stale commit."""
    def _worktree(path):
        full = os.path.join(_REPO_ROOT, path)
        return open(full, encoding="utf-8").read() if os.path.exists(full) else None
    declared = _declared_at(_worktree)
    assert declared is not None and "DECISION_ENTRY" in declared, "precondition: post-merge shape"
    assert _provenance_drift(declared) == []


def test_the_provenance_check_reads_the_pre_split_layout_and_reports_drift():
    """The other side of the merge, and non-vacuity: master's pre-move layout (shapes in `verify.py`,
    no decision-entry atom) passes; a drifted shape or a mis-spelled branch-local shape fails."""
    pre = "\n".join(f'{n} = re.compile(r"{_FLOOR_SHAPES[n]}")' for n in _MASTER_SHAPES)
    layout = {"skills/tp-merge-from-main/scripts/verify.py": pre}
    assert _provenance_drift(_declared_at(layout.get)) == []
    drifted = {"skills/tp-merge-from-main/scripts/verify.py": pre.replace(r"\s+—", r"\s*—")}
    assert _provenance_drift(_declared_at(drifted.get)), "a narrowed LOG must be reported"
    odd = {**layout, "skills/tp-merge-from-main/scripts/verify_atoms.py":
           'DECISION_ENTRY = re.compile(r"^### x$")'}
    drift = _provenance_drift(_declared_at(odd.get))
    assert len(drift) == 1 and drift[0].startswith("DECISION_ENTRY:"), drift
