"""certify — run certifier records against the guards they claim bind.

design: audit-pass-does-not-bind (Tasks 3.3-3.6; detailed-design.md §Interfaces,
detailed-design-certifier.md §1-§2).

`certify_claim(claim, rec, *, repo, sha, deadline, runner)` returns
`{id, status, reasons, evidence:{red:[{rc, tail}], green:[{rc, tail}]}}`:
no record → `unverified` (`no-record`, B16); a guard path with no entry at `sha` →
`unverified` (`guard-absent`), one that is a symlink, a directory or a gitlink →
`unverified` (`guard-not-file`), a `.py` guard the strict decode rejects →
`unverified` (`guard-undecodable`, fail closed; known issue L92); a declared subject
that is not a regular file at `sha` → `unverified` (`subject-absent:<path>`); else the
record is validated against the guard text at `sha` (`read_guard_at_sha`: `git show
sha:path`, P7, a `.py` guard decoded strictly in the codec Python picks), which
refuses any setup op outside the claim's `subjects` before a pole runs, and each
pole runs in a fresh `certify_scratch.pole_tree`: setup ops applied, the command
run with the pole's scrubbed env, the full stdout+stderr classified (the tail is
evidence only). The command of a pytest guard's pole is the certifier's own
(`certify_argv.pytest_command`: `sys.executable -m pytest ./<path>[::<node>]
--junitxml=<pole dir>/junit.xml --rootdir=<resolved tree> --confcutdir=<resolved tree>
-p no:cacheprovider -o addopts= -o junit_family=xunit1`, the target built from the
guard's parts, never its string, no repo `addopts` added; the xunit1
report outside the checked-out tree) and the pole is classified from that report
[R6]; a report missing after the run is `None`. A non-pytest pole runs the record's
argv. Per pole [R10]: `timeout = min(120, deadline - now)`; a pole with no
budget left is not run and is `unverified` (`budget`). Any exception →
`unverified` (fail-closed). Forged `status` / `observed` keys are never read (B7).
`certify_all` runs one claims file under a shared budget and the caller-repo
fingerprint; the CLI (`validate`, `run`, `fold`) lives in `certify_cli`, the
caller checks (`handoff`, `claimant-check`, `scan`) in `certify_cli_checks`, and
`main` here is its thin script entry.

KNOWN BYPASS [F7][G][R2]: the fingerprint covers HEAD, the content of
tracked/dirty/untracked non-ignored files, the watched refs, the hooks dir and
the listed security config keys. Not covered: unwatched refs, other config
keys, `info/*`, gitignored paths, object-store writes (the `--shared`
alternates and unreferenced objects), other git-dir files, and any path
outside the caller repo and the scratch (a non-pytest argv is filtered, never
read for what it does) — such writes are neither prevented nor detected. Narrowed so
concurrent designs moving their own branches cannot cause spurious exit-3
escalations.

KNOWN BYPASS [R5]: marker-in-subject checks only RED setup-op content and
touched paths; a marker that also occurs in an untouched file the guard reads
can still be echoed by a failing comparison.

KNOWN BYPASS [F9]: parameters completeness and red[*].varies truthfulness are
declared, not derived; B5 (incl. unvaried-independently) is mechanical only
over what is declared.

KNOWN BYPASS [J]: near-miss authorship and the dry-run terminal rule are
contract; an absence-only or pre-probed RED can certify a tautological guard
(pinned by the ARIS absence-RED fixture).

KNOWN BYPASS [J] (in-process hook): a RED `write` to a Python subject the guard imports runs
inside pytest's process and can register a hook that forges the declared node's `<failure>`
with the marker; a vacuous guard then binds. It needs a bad-faith certifier (protocol
§KNOWN BYPASS list, Authorship).

KNOWN BYPASS (N5): free-text `property` reaches the certifier prompt; one line
≤300 chars, fenced as untrusted data, it can still steer RED choice.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import certify_classify
import certify_pynode
import certify_record
import certify_scratch
from argv_runner import run_argv
from certify_argv import is_pytest_guard, norm, pytest_command

POLE_TIMEOUT = 120
JUNIT_NAME = "junit.xml"  # beside the pole's tree, in its throw-away pole dir
FORCED_REASONS = ("records-handoff", "claimant-records")  # `run --unverified` (F6)
clock = time.monotonic  # module-level so tests can drive the budget


def read_at_sha(repo, sha, path) -> str | None:
    """`path`'s text at `sha` (`git show sha:path`), or None when absent."""
    proc = subprocess.run(
        ["git", "show", f"{sha}:{norm(str(path))}"], cwd=str(repo),
        env=certify_scratch.scrubbed_env(), capture_output=True, encoding="utf-8",
        errors="replace", timeout=certify_scratch.GIT_TIMEOUT,
    )
    return proc.stdout if proc.returncode == 0 else None


def read_guard_at_sha(repo, sha, path) -> tuple[str | None, list[str]]:
    """`(text, [])` of the guard file at `sha`, else `(None, [reason])`.

    A Python guard (a `.py` path: the only files pytest imports as test modules) is
    decoded strictly from its blob in the codec Python picks (`certify_pynode.python_source`:
    a BOM or PEP 263 coding cookie), so the `ast` parse, the xunit1 `line` and the RED
    marker all read one text. A guard the strict decode rejects is `guard-undecodable`
    (fail closed: it never certifies); that includes some files CPython accepts (known
    issue L92). Any other guard reads like every other file (`read_at_sha`)."""
    if not path.endswith(".py"):
        text = read_at_sha(repo, sha, path)
        return (text, []) if text is not None else (None, ["guard-absent"])
    proc = subprocess.run(
        ["git", "show", f"{sha}:{norm(str(path))}"], cwd=str(repo),
        env=certify_scratch.scrubbed_env(), capture_output=True,
        timeout=certify_scratch.GIT_TIMEOUT,
    )
    if proc.returncode != 0:
        return None, ["guard-absent"]
    text = certify_pynode.python_source(proc.stdout)
    return (text, []) if text is not None else (None, ["guard-undecodable"])


FILE_MODES = (["100644", "blob"], ["100755", "blob"])


def tree_entry(repo, sha, path) -> list[str] | None:
    """`[mode, type]` of `path`'s own entry at `sha` (`git ls-tree`), None when absent."""
    proc = subprocess.run(
        ["git", "ls-tree", "-z", "--full-tree", sha, "--", path], cwd=str(repo),
        env=certify_scratch.scrubbed_env(), capture_output=True, encoding="utf-8",
        errors="replace", timeout=certify_scratch.GIT_TIMEOUT,
    )
    for item in proc.stdout.split("\0") if proc.returncode == 0 else []:
        meta, _tab, name = item.partition("\t")
        if name == path:
            return meta.split(" ")[:2]
    return None


def is_file_at(repo, sha, path) -> bool:
    """`path` is a regular file (blob mode 100644 / 100755) at `sha`, never a symlink."""
    return tree_entry(repo, sha, path) in FILE_MODES


def guard_file_reasons(repo, sha, guard) -> list[str]:
    """The guard's path is a tracked regular file at `sha`: `guard-absent` when no entry,
    `guard-not-file` for a symlink (120000), a directory or a gitlink."""
    found = tree_entry(repo, sha, guard.partition("::")[0])
    if found is None:
        return ["guard-absent"]
    return [] if found in FILE_MODES else ["guard-not-file"]


def entry(cid, status, reasons, evidence=None) -> dict:
    return {"id": cid, "status": status, "reasons": list(reasons),
            "evidence": evidence or {"red": [], "green": []}}


# --- setup ops ------------------------------------------------------------------------------

def _target(root: Path, rel: str) -> Path | None:
    """`rel` inside the pole tree (symlinks resolved), never into `.git`, else None."""
    target = (root / rel).resolve()
    if target == root or not target.is_relative_to(root):
        return None
    return None if target.relative_to(root).parts[0] == ".git" else target


def _apply(root: Path, op: dict) -> str | None:
    target = _target(root, op["path"])
    if target is None:
        return f"path:{op['path']}"
    if op["op"] == "replace":
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        if text.count(op["old"]) != 1:
            return f"replace-count:{op['path']}"
        target.write_text(text.replace(op["old"], op["new"]), encoding="utf-8")
    elif op["op"] == "write":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(op["content"], encoding="utf-8")
    elif not target.is_file():
        return f"delete-missing:{op['path']}"
    else:
        target.unlink()
    return None


def apply_setup(tree, ops) -> str | None:
    """Apply setup ops in order; the first failure's reason, else None (R1/G1)."""
    root = Path(tree).resolve()
    for op in ops:
        try:
            error = _apply(root, op)
        except (OSError, UnicodeError) as exc:
            error = f"io:{op['path']}:{type(exc).__name__}"
        if error:
            return error
    return None


# --- poles ---------------------------------------------------------------------------------

BUDGET = (("unverified", ["budget"], False), {"rc": None, "tail": "budget"})


def run_pole(pole, rec, classify, *, repo, sha, deadline, runner, guard_text=None):
    """`(classified, evidence)` for one pole run in its own pole tree. `guard_text` is the
    guard file's text at S: a pytest report's testcases are matched against it."""
    if deadline - clock() <= 0:
        return BUDGET
    with certify_scratch.pole_tree(repo, sha) as (tree, env):
        error = apply_setup(tree, pole["setup"])
        if error:
            run = certify_classify.PoleRun(None, "", error)
            return classify(run, pole, rec), {"rc": None, "tail": f"setup:{error}"}
        remaining = deadline - clock()
        if remaining <= 0:
            return BUDGET
        junit_path = None
        if is_pytest_guard(rec["guard"]):
            junit_path = Path(tree).parent / JUNIT_NAME
            # resolved: pytest's invocation dir is the physical cwd, so an unresolved
            # tree behind a symlinked temp dir (macOS /var) would not contain the tests
            argv = pytest_command(rec["guard"], junit_path, rootdir=Path(tree).resolve())
        else:
            argv = list(pole["argv"])
        result = run_argv(argv, cwd=tree, timeout=min(POLE_TIMEOUT, remaining),
                          env=env, runner=runner)
        junit = _read_report(junit_path)
    run = certify_classify.PoleRun(result.rc, result.output, None, junit, guard_text)
    return classify(run, pole, rec), {"rc": result.rc, "tail": result.tail}


def _read_report(path) -> str | None:
    """The pole's JUnit XML text, or None when it was not written (could not evaluate)."""
    if path is None or not Path(path).is_file():
        return None
    return Path(path).read_text(encoding="utf-8", errors="replace")


def prepare(claim, rec, *, repo, sha):
    """`(valid_record, guard_text, [])`, or `(None, None, reasons)` before any run.

    Claim shape (incl. `invalid:guard`, `guard-is-subject`), `no-record`, `guard-absent` /
    `guard-not-file` / `guard-undecodable`, `subject-absent:<path>`, then
    `certify_record.validate` against the guard text at `sha` — the CLI
    `validate --records` gate uses the same function, so a record that passes it
    reaches the poles here.
    """
    bad_claim = certify_record.claim_reasons(claim)
    if bad_claim:
        return None, None, bad_claim
    if rec is None:
        return None, None, ["no-record"]
    guard = claim["guard"]
    bad_guard = guard_file_reasons(repo, sha, guard)
    if bad_guard:
        return None, None, bad_guard
    guard_text, bad_text = read_guard_at_sha(repo, sha, guard.partition("::")[0])
    if bad_text:
        return None, None, bad_text
    absent = [f"subject-absent:{path}" for path in claim.get("subjects") or []
              if not is_file_at(repo, sha, path)]
    if absent:
        return None, None, absent
    valid, reasons = certify_record.validate(
        claim, rec, guard_text=guard_text, node_id=guard if "::" in guard else None,
        read_at_sha=lambda path: read_at_sha(repo, sha, path),
    )
    return (None, None, reasons) if reasons else (valid, guard_text, [])


def _certify_claim(claim, rec, *, repo, sha, deadline, runner) -> dict:
    cid = claim.get("id") if isinstance(claim, dict) else None
    valid, guard_text, reasons = prepare(claim, rec, repo=repo, sha=sha)
    if reasons:
        return entry(cid, "unverified", reasons)
    poles, evidence = [], {"red": [], "green": []}
    for kind, classify in (("red", certify_classify.classify_red),
                           ("green", certify_classify.classify_green)):
        for pole in valid[kind]:
            classified, ev = run_pole(pole, valid, classify, repo=repo, sha=sha,
                                      deadline=deadline, runner=runner, guard_text=guard_text)
            poles.append(classified)
            evidence[kind].append(ev)
    status, why = certify_classify.claim_status(poles, valid, guard_text)
    return entry(cid, status, why, evidence)


def certify_claim(claim, rec, *, repo, sha, deadline, runner=subprocess.run) -> dict:
    """One claim's status entry (module docstring); never raises."""
    try:
        return _certify_claim(claim, rec, repo=repo, sha=sha, deadline=deadline, runner=runner)
    except Exception as exc:  # fail-closed: any crash is unverified, never binds
        cid = claim.get("id") if isinstance(claim, dict) else None
        return entry(cid, "unverified", [f"exception:{type(exc).__name__}"])


# --- every claim of one claims file (Task 3.5) ---------------------------------------------

def _id_of(item, kind: str):
    """`item["id"]` (None for a non-dict); a list / dict id is bad input (exit 2), not a
    TypeError traceback out of the `in` / `.get` lookups below."""
    iid = item.get("id") if isinstance(item, dict) else None
    if isinstance(iid, (list, dict)):
        raise ValueError(f"{kind} id must be a string, got {type(iid).__name__}")
    return iid


def _records_by_id(records):
    """`({id: record}, duplicate ids)`; a non-list is bad input."""
    if not isinstance(records, list):
        raise ValueError("records must be a JSON array")
    found, dupes = {}, set()
    for rec in records:
        rid = _id_of(rec, "record")
        if rid in found:
            dupes.add(rid)
        found.setdefault(rid, rec)
    return found, dupes


def _entries(doc, recs, dupes, *, name, max_claims, run):
    file_level = certify_record.file_level_entries(doc, name)
    if file_level:  # e.g. disposition-name [R9]: the whole file is unverified
        return [entry(e["id"], e["status"], e["reasons"]) for e in file_level]
    out = []
    for i, claim in enumerate(doc["claims"]):
        cid = _id_of(claim, "claim")
        if i >= max_claims:
            out.append(entry(cid, "unverified", ["cap"]))
        elif cid in dupes:
            out.append(entry(cid, "unverified", ["duplicate-record"]))
        else:
            out.append(run(claim, recs.get(cid)))
    return out


def certify_all(claims_doc, records, *, repo, sha, name, max_claims=25, budget_s=480,
                watch_refs=None, runner=subprocess.run, unverified=None) -> dict:
    """Certify every claim of one claims file against its records [E][H][F7][G].

    Every claim gets an entry, with or without a record; claims past
    `max_claims` → `unverified` (`cap`); one `deadline = start + budget_s` is
    shared by every pole; records naming no claim are `orphans`. The caller
    repo is fingerprinted before and after: a change → every status
    `unverified` (`tree-mutated`) and `tree_mutated: true`. Each entry carries
    its claim's `guard` (when a string) so the phrase scan can match a
    `[cert:<id>]` tag to the guard path from the result alone (Task 5.3).
    `disposition` is derived from `name` (`certify_record.derived_disposition`),
    never copied from the file, and `file_reasons` lists its file-level reasons.
    `unverified` (one of `FORCED_REASONS`) runs no pole: every claim is
    `unverified` with that reason (a failed records handoff or claimant check).
    """
    if unverified is not None and unverified not in FORCED_REASONS:
        raise ValueError(f"unverified must be one of {FORCED_REASONS}")
    if not isinstance(claims_doc, dict) or not isinstance(claims_doc.get("claims"), list):
        raise ValueError("claims doc must be {disposition, claims: [...]}")
    recs, dupes = _records_by_id(records)
    before = certify_scratch.fingerprint(repo, watch_refs)
    deadline = clock() + budget_s

    def run(claim, rec):
        if unverified is not None:
            return entry(claim.get("id") if isinstance(claim, dict) else None, "unverified",
                         [unverified])
        return certify_claim(claim, rec, repo=repo, sha=sha, deadline=deadline, runner=runner)

    claims = _entries(claims_doc, recs, dupes, name=name, max_claims=max_claims, run=run)
    mutated = certify_scratch.fingerprint(repo, watch_refs) != before
    if mutated:
        for item in claims:
            item["status"] = "unverified"
            item["reasons"] = list(dict.fromkeys(item["reasons"] + ["tree-mutated"]))
    guards = {c.get("id"): c.get("guard") for c in claims_doc["claims"] if isinstance(c, dict)}
    for item in claims:
        if isinstance(guards.get(item["id"]), str):
            item["guard"] = guards[item["id"]]
    ids = set(guards)
    return {
        "complete": True, "name": name, "sha": sha,
        "disposition": certify_record.derived_disposition(claims_doc, name),
        "file_reasons": certify_record.file_reasons(claims_doc, name), "claims": claims,
        "statuses": [c["status"] for c in claims],
        "orphans": [rid for rid in recs if rid not in ids],
        "tree_mutated": mutated,
    }


def main(argv=None) -> int:
    """Thin script entry; the CLI lives in `certify_cli`."""
    import certify_cli  # deferred: certify_cli imports this module

    return certify_cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
