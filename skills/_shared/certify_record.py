"""certify_record — validate claims files, claims and certifier records.

design: audit-pass-does-not-bind (Tasks 2.1, 2.2; detailed-design-certifier.md §1).

Every reason makes the claim `unverified`. The caller validates the record it
runs (the certifier's dry-run uses the same function, so a record that passes
its dry-run passes here). A claim carries `{id, guard, property,
parameters}` plus an optional `subjects`; a record copies those and adds
`parameters_added?`, `varied`, `red[]`, `green[]`, `bypass?`, `rationale`.
`status` / `observed` keys are dropped, never read (B7).
`P = parameters ∪ parameters_added`.

`subjects` [R6, amended 2026-09-25] is the claim's allowlist: the repo-relative
files under guard (the code the guard checks). A setup op may touch only a
declared subject (`setup-outside-subjects:<path>`), so a record can never write a
test, a `conftest.py` or any pytest / tox / setup.cfg / pyproject config unless the
claim declares it; the refusal is the allowlist, not a list of config names. A claim
without `subjects` is valid (its file validates) but certifies nothing: its record is
`no-subjects`, fail-closed. Each subject is a normalised repo-relative path (no `/`
or `~` prefix, no `..`, not under `.git`), listed once (`invalid:subjects`); that it
is a regular file at the certified SHA is `certify.prepare`'s check (`subject-absent`).
The claim's `guard` is `path[::node]` whose path obeys the same shape and never starts
with `-`, and whose `::` names a node (`invalid:guard`). That is the first layer: the
certifier never hands the guard string to pytest, it builds `./<path>[::<node>]` from the
parts (`certify_argv.pytest_target`), so no guard reads as an option or an `@` argument
file. The guard's file is never a subject (`guard-is-subject`): a record could rewrite
it. That it is a regular file at the certified SHA, and a `.py` one Python can decode,
is `certify.prepare`'s check (`guard-absent`, `guard-not-file`, `guard-undecodable`).

`validate` first checks shape (a malformed record stops there), then runs the
ordered `RULES` table: each rule maps a context to the reasons it finds, so a
new rule is one appended row, not a new branch. The pole rules (argv, setup,
exit codes) live in `certify_argv`; the marker rules stay here because they
need the guard text and `read_at_sha`. `candidate_path_violations` /
`candidate_paths_ok` are the Step 2b claimant-record check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable

import certify_argv
from certify_argv import guard_parts, norm, repo_path_ok

CLAIM_KEYS = ("id", "guard", "property", "parameters")
CLAIM_OPTIONAL = ("subjects",)
RECORD_REQUIRED = CLAIM_KEYS + ("varied", "red", "green", "rationale")
RECORD_OPTIONAL = ("parameters_added", "bypass") + CLAIM_OPTIONAL
RECORD_DROPPED = ("status", "observed")
RED_KEYS = {"varies", "setup", "expect"}
GREEN_KEYS = {"setup"}
POLE_OPTIONAL = {"argv", "expect"}  # argv: a non-pytest guard's only (certify_argv)
RED_EXPECT = {"exit": int, "output_contains": str, "exception": str}
GREEN_EXPECT = {"exit": int, "output_contains": str}
OP_KEYS = {
    "replace": {"op", "path", "old", "new"},
    "write": {"op", "path", "content"},
    "delete": {"op", "path"},
}

MAX_CLAIMS = 25
MAX_PARAMETERS = 6
MAX_GREENS = 3
PROPERTY_MAX = 300
DISPOSITIONS = ("verdict", "ledger")
SWEEP_NAME = re.compile(r"sweep-\d\d\.claims\.json")
MARKER_MIN = 8
GENERIC_MARKERS = frozenset({
    "FAILED", "failed", "Error", "error", "assert", "AssertionError",
    "Traceback", "1 failed", "FAIL", "exit",
})


def _dedupe(items) -> list[str]:
    return list(dict.fromkeys(items))


def _str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


# --- claims -----------------------------------------------------------------------

def claim_reasons(claim) -> list[str]:
    """Shape, extra-key, subjects and one-line-property reasons for one claim (N5)."""
    if not isinstance(claim, dict):
        return ["invalid:shape"]
    out = []
    if any(k not in claim for k in CLAIM_KEYS) or not _claim_types_ok(claim):
        out.append("invalid:shape")
    if set(claim) - set(CLAIM_KEYS) - set(CLAIM_OPTIONAL):
        out.append("invalid:claim-extra-key")
    if "subjects" in claim and not _subjects_ok(claim["subjects"]):
        out.append("invalid:subjects")
    if isinstance(claim.get("guard"), str) and claim["guard"] and not _guard_ok(claim["guard"]):
        out.append("invalid:guard")
    if _guard_is_subject(claim):
        out.append("guard-is-subject")
    prop = claim.get("property")
    if isinstance(prop, str) and (prop.splitlines() != [prop] or len(prop) > PROPERTY_MAX):
        out.append("invalid:property")
    return out


def _guard_ok(guard: str) -> bool:
    """`path[::node]` whose path is normalised and repo-relative like a subject, never
    `-`-led, and whose `::` (if any) names a node. The first layer only: the pytest target
    is built from the parts (`certify_argv.pytest_target`), never the claim's string."""
    path, node = guard_parts(guard)
    return repo_path_ok(path) and not path.startswith("-") and node != ""


def _subjects_ok(subjects) -> bool:
    """A non-empty list of distinct, normalised, repo-relative file paths."""
    return (isinstance(subjects, list) and bool(subjects)
            and all(map(repo_path_ok, subjects)) and len(set(subjects)) == len(subjects))


def _guard_is_subject(claim) -> bool:
    """The guard's own file is declared a subject: a record could then rewrite the guard."""
    subjects = claim.get("subjects")
    guard = claim.get("guard")
    return (isinstance(guard, str) and isinstance(subjects, list)
            and guard_parts(guard)[0] in subjects)


def _claim_types_ok(claim) -> bool:
    texts = all(isinstance(claim[k], str) and claim[k] for k in ("id", "guard", "property"))
    return texts and _str_list(claim["parameters"])


def _doc_reasons(doc, name) -> list[str]:
    """File-level reasons: each makes every claim of the file unverified."""
    if (not isinstance(doc, dict) or set(doc) != {"disposition", "claims"}
            or doc["disposition"] not in DISPOSITIONS or not isinstance(doc["claims"], list)):
        return ["invalid:shape"]
    out = []
    ids = [c.get("id") if isinstance(c, dict) else None for c in doc["claims"]]
    if len(ids) != len(set(map(repr, ids))):
        out.append("invalid:shape")
    wanted = "ledger" if is_sweep_name(name) else "verdict"
    if doc["disposition"] != wanted:
        out.append("disposition-name")
    return out


def validate_claims_doc(doc, name) -> list[str]:
    """Reasons for one claims file `{disposition, claims[]}` named `name` [R9]."""
    out = _doc_reasons(doc, name)
    claims = doc.get("claims") if isinstance(doc, dict) else None
    if not isinstance(claims, list):
        return out
    if len(claims) > MAX_CLAIMS:
        out.append("cap")
    for claim in claims:
        out.extend(claim_reasons(claim))
    return _dedupe(out)


def file_reasons(doc, name) -> list[str]:
    """The file-level reasons of claims file `doc` named `name` (each voids every claim)."""
    return _doc_reasons(doc, name)


def is_sweep_name(name) -> bool:
    return bool(SWEEP_NAME.fullmatch(PurePosixPath(str(name)).name))


def derived_disposition(doc, name) -> str:
    """[R9] `ledger` only for a valid `sweep-NN.claims.json`; the declared value is never copied."""
    return "ledger" if is_sweep_name(name) and not _doc_reasons(doc, name) else "verdict"


def is_ledger_result(res) -> bool:
    """A certify result left out of the verdict fold: `ledger`, sweep-named, no file reasons.

    Anything else folds, so a forged or mis-named `ledger` fails closed (F1).
    """
    return (isinstance(res, dict) and res.get("disposition") == "ledger"
            and is_sweep_name(res.get("name", "")) and res.get("file_reasons") == [])


def file_level_entries(doc, name) -> list[dict]:
    """One `unverified` entry per claim when the file itself is invalid, else []."""
    reasons = _doc_reasons(doc, name)
    if not reasons:
        return []
    claims = doc.get("claims") if isinstance(doc, dict) else None
    claims = claims if isinstance(claims, list) else []
    return [
        {"id": c.get("id") if isinstance(c, dict) else None,
         "status": "unverified", "reasons": list(reasons)}
        for c in claims
    ]


# --- record shape ---------------------------------------------------------------------

def _op_ok(op) -> bool:
    if not isinstance(op, dict) or op.get("op") not in OP_KEYS:
        return False
    keys = OP_KEYS[op["op"]]
    return set(op) == keys and all(isinstance(op[k], str) for k in keys)


def _expect_ok(expect, allowed) -> bool:
    if not isinstance(expect, dict) or set(expect) - set(allowed):
        return False
    return all(isinstance(v, allowed[k]) and not isinstance(v, bool) for k, v in expect.items())


def _pole_ok(pole, keys, expect_types, expect_required) -> bool:
    if not isinstance(pole, dict):
        return False
    if not keys <= set(pole) or set(pole) - keys - POLE_OPTIONAL:
        return False
    if expect_required and "expect" not in pole:
        return False
    if "expect" in pole and not _expect_ok(pole["expect"], expect_types):
        return False
    if "argv" in pole and not (_str_list(pole["argv"]) and pole["argv"]):
        return False
    setup = pole["setup"]
    if not (isinstance(setup, list) and all(map(_op_ok, setup))):
        return False
    return "varies" not in keys or _str_list(pole["varies"])


def record_shape(rec) -> list[str]:
    """`invalid:shape` when the record is not the documented shape, else []."""
    if not isinstance(rec, dict) or any(k not in rec for k in RECORD_REQUIRED):
        return ["invalid:shape"]
    if set(rec) - set(RECORD_REQUIRED) - set(RECORD_OPTIONAL) - set(RECORD_DROPPED):
        return ["invalid:shape"]
    texts = all(isinstance(rec[k], str) for k in ("id", "guard", "property", "rationale"))
    lists = _str_list(rec["parameters"]) and _str_list(rec["varied"])
    lists = lists and _str_list(rec.get("parameters_added", []))
    bypass = isinstance(rec.get("bypass", ""), str)
    poles = (isinstance(rec["red"], list) and rec["red"]
             and isinstance(rec["green"], list) and rec["green"])
    poles = poles and all(_pole_ok(p, RED_KEYS, RED_EXPECT, True) for p in rec["red"])
    poles = poles and all(_pole_ok(p, GREEN_KEYS, GREEN_EXPECT, False) for p in rec["green"])
    return [] if (texts and lists and bypass and poles) else ["invalid:shape"]


# --- rule context + table -------------------------------------------------------------

@dataclass
class Ctx:
    claim: dict
    rec: dict
    guard_text: str | None
    node_id: str | None
    read_at_sha: Callable[[str], "str | None"]

    @property
    def params(self) -> list[str]:
        return _dedupe(self.rec["parameters"] + self.rec.get("parameters_added", []))


def _claim_drift(c: Ctx):
    same = all(c.rec[k] == c.claim[k] for k in ("id", "guard", "property"))
    subjects = "subjects" not in c.rec or c.rec["subjects"] == c.claim.get("subjects")
    if not (same and subjects) or not set(c.rec["parameters"]) >= set(c.claim["parameters"]):
        yield "claim-drift"


def _too_many_parameters(c: Ctx):
    if len(c.params) > MAX_PARAMETERS:
        yield "too-many-parameters"


def _red_count(c: Ctx):
    if len(c.rec["red"]) > len(c.params) + 1:
        yield "red-count"


def _green_count(c: Ctx):
    if len(c.rec["green"]) > MAX_GREENS:
        yield "green-count"


def _varied_mismatch(c: Ctx):
    varied = set(c.rec["varied"])
    union = {v for pole in c.rec["red"] for v in pole["varies"]}
    if varied != union or not varied <= set(c.params):
        yield "varied-mismatch"


def _unvaried(c: Ctx):
    for p in c.params:
        if p not in c.rec["varied"]:
            yield f"unvaried:{p}"


def _unvaried_independently(c: Ctx):
    sole = {pole["varies"][0] for pole in c.rec["red"] if len(pole["varies"]) == 1}
    for p in c.params:
        if p not in sole:
            yield f"unvaried-independently:{p}"


def _markers(c: Ctx) -> list[str]:
    return [pole["expect"].get("output_contains") or "" for pole in c.rec["red"]]


def _red_no_marker(c: Ctx):
    if not all(_markers(c)):
        yield "red-no-marker"


def _red_generic_marker(c: Ctx):
    if any(m and (len(m.strip()) < MARKER_MIN or m.strip() in GENERIC_MARKERS) for m in _markers(c)):
        yield "red-generic-marker"


def _marker_not_in_guard(c: Ctx):
    if any(m and m not in (c.guard_text or "") for m in _markers(c)):
        yield "marker-not-in-guard"


def _marker_in_node_id(c: Ctx):
    node = c.node_id or c.rec["guard"]
    if any(m and m in node for m in _markers(c)):
        yield "marker-in-node-id"


def _red_ops(c: Ctx) -> list[dict]:
    return [op for pole in c.rec["red"] for op in pole["setup"]]


def _marker_in_subject(c: Ctx):
    """[R5] the marker is in a RED op's text, or in a RED-touched path's text at S."""
    markers = [m for m in _markers(c) if m]
    texts = [op.get(k, "") for op in _red_ops(c) for k in ("old", "new", "content")]
    for path in dict.fromkeys(op["path"] for op in _red_ops(c)):
        texts.append(c.read_at_sha(path) or "")
    if any(m in t for m in markers for t in texts):
        yield "marker-in-subject"


def _setup_outside_subjects(c: Ctx):
    """[R6] the allowlist: a setup op touches only a path the claim declares.

    Read from the claim (the caller's bytes), never from the record's copy."""
    subjects = c.claim.get("subjects")
    if not subjects:
        yield "no-subjects"
        return
    declared = set(subjects)
    for path in dict.fromkeys(norm(op["path"]) for pole in c.rec["red"] + c.rec["green"]
                              for op in pole["setup"]):
        if path not in declared:
            yield f"setup-outside-subjects:{path}"


def _on_rec(fn):
    return lambda c: fn(c.rec)


RULES: list[tuple[str, Callable[[Ctx], object]]] = [
    ("claim-drift", _claim_drift),
    ("too-many-parameters", _too_many_parameters),
    ("red-count", _red_count),
    ("green-count", _green_count),
    ("varied-mismatch", _varied_mismatch),
    ("unvaried", _unvaried),
    ("unvaried-independently", _unvaried_independently),
    ("invalid:shape", _on_rec(certify_argv.exit_shape)),
    ("red-no-marker", _red_no_marker),
    ("red-generic-marker", _red_generic_marker),
    ("marker-not-in-guard", _marker_not_in_guard),
    ("marker-in-node-id", _marker_in_node_id),
    ("marker-in-subject", _marker_in_subject),
    ("pytest-argv-supplied", _on_rec(certify_argv.pytest_argv_supplied)),
    ("pytest-exit-supplied", _on_rec(certify_argv.pytest_exit_supplied)),
    ("argv-missing", _on_rec(certify_argv.argv_missing)),
    ("setup-outside-subjects", _setup_outside_subjects),
    ("red-delete", _on_rec(certify_argv.red_delete)),
    ("red-edits-guard", _on_rec(certify_argv.red_edits_guard)),
    ("green-edits-guard", _on_rec(certify_argv.green_edits_guard)),
    ("no-real-green", _on_rec(certify_argv.no_real_green)),
    ("no-perturbed-green", _on_rec(certify_argv.no_perturbed_green)),
    ("argv-escape", _on_rec(certify_argv.argv_escape)),
    ("argv-not-guard", _on_rec(certify_argv.argv_not_guard)),
]


def validate(claim, rec, *, guard_text, node_id=None, read_at_sha=None):
    """`(record, [])` when valid (forged `status`/`observed` dropped), else `(None, reasons)`.

    `guard_text` is the guard file's text at the certified SHA; `node_id` the
    guard's pytest node id (if any); `read_at_sha(path) -> str | None` returns a
    path's text at that SHA (used by `marker-in-subject`).
    """
    reasons = claim_reasons(claim) + record_shape(rec)
    if reasons:
        return None, _dedupe(reasons)
    ctx = Ctx(claim, rec, guard_text, node_id, read_at_sha or (lambda _path: None))
    for _family, rule in RULES:
        reasons.extend(rule(ctx))
    if reasons:
        return None, _dedupe(reasons)
    return {k: v for k, v in rec.items() if k not in RECORD_DROPPED}, []


def candidate_path_violations(paths, design) -> list[str]:
    """[A][R11] the diff paths a candidate may not carry: anything under
    `{design}/certifications/` but a top-level `*.claims.json`, and
    `{design}/sweep-ledger.md` (`certify.py claimant-check` prints them)."""
    root = norm(str(design))
    certs = f"{root}/certifications/"
    out = []
    for raw in paths:
        path = norm(str(raw))
        rest = path[len(certs):] if path.startswith(certs) else None
        if path == f"{root}/sweep-ledger.md" or (
                rest is not None and ("/" in rest or not rest.endswith(".claims.json"))):
            out.append(path)
    return out


def candidate_paths_ok(paths, design) -> bool:
    return not candidate_path_violations(paths, design)
