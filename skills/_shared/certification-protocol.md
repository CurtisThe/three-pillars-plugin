# Guard certification protocol

An audit that says a guard (test, check, lint, gate, script) *enforces* a property must prove it. The auditor names only the **claim**. An independent
certifier (`agents/tp-certifier.md`) authors RED inputs that violate the property and GREEN inputs that keep it true. `certify.py` then re-runs every
pole itself, in a throw-away clone, and decides the claim's status mechanically. This file is the single prose source for that loop. The code-level
tables are linked, not restated:

- record validation reasons: `skills/_shared/certify_record.py` (`RULES`) and `certify_argv.py` (command/setup rules);
- the RED/GREEN decision table and the claim fold: `skills/_shared/certify_classify.py` (+ `certify_junit.py`, `certify_pynode.py`);
- the scan: `skills/_shared/cert_phrase_scan.py`; the fold: `skills/_shared/cert_fold.py`;
- the verdict join: `auto_verdict.combine_verdict`; the caller checks (`handoff`, `claimant-check`, `scan`):
  `certify_cli_checks.py`.

Scripts are resolved, never called by a bare repo path:

```bash
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
CERT="$(python3 "$RS" certify.py)" || exit 1
CL="$(python3 "$RS" certify_ledger.py)" || exit 1
```

## Shapes

**Claims file** (auditor-authored, `{design}/certifications/<name>.claims.json`, at most 25 claims; claims past the
25th are `unverified` with reason `cap`):

```json
{"disposition": "verdict", "claims": [
  {"id": "c1", "guard": "skills/_shared/test_x.py::test_y", "property": "one line, at most 300 chars",
   "parameters": ["route", "span"], "subjects": ["skills/_shared/x.py"]}
]}
```

A claim carries `{id, guard, property, parameters}` plus `subjects`. `guard` is `path[::node]`: its path normalised like a subject and never `-`-led, and a `::` names a node (`invalid:guard`).
The guard's path is a tracked regular file at `S` (no entry: `guard-absent`; a symlink, directory or gitlink: `guard-not-file`), never a subject (`guard-is-subject`). A `.py` guard is decoded strictly in the codec Python picks (its UTF-8 BOM or PEP 263 coding cookie); one the strict decode rejects is `guard-undecodable` (fail closed; this includes some files CPython accepts, e.g. a non-UTF-8 byte in a comment, so save a guard as UTF-8 with `\n` line endings). `subjects` lists the repo-relative files under guard
(the code the guard checks): the **only** files a certifier may perturb. Each is a normalised path (no `/`, `~`, `..` or `.git`; `invalid:subjects`)
to a regular file at `S` (`subject-absent:<path>`). Name the code, not a test, `conftest.py` or pytest config. A claim without `subjects` validates
but certifies nothing: `unverified` (`no-subjects`). `disposition` is `verdict` (folds into the audit verdict) or `ledger` (recorded only). `ledger`
is accepted only in a file named `sweep-NN.claims.json`, and such a file must be `ledger`. Any other name (including `self.claims.json`) must be
`verdict`. A violation makes every claim of the file `unverified` (`disposition-name`).

**Record** (certifier-authored): the claim's four fields copied verbatim, plus:

| Key | Shape |
|---|---|
| `parameters_added` | optional `[str]`: parameters the certifier found the guard also depends on |
| `varied` | `[str]`: must equal the union of every RED's `varies` |
| `red` | `[{varies, setup, argv?, expect: {exit?, output_contains, exception?}}]`, at most `len(P) + 1` (`argv`, `exit`: non-pytest guards only) |
| `green` | `[{setup, argv?, expect?: {exit?, output_contains?}}]`, at most 3 (`argv`, `exit`: non-pytest guards only) |
| `bypass` | optional `str`: accepted only when the guard file states `KNOWN BYPASS: <bypass>` |
| `rationale` | `str`: why each RED violates the property and each GREEN keeps it |

`P = parameters ∪ parameters_added` (at most 6). Every `p` in `P` must be the **sole** `varies` entry of at least one RED ("varied independently"). A
`status` or `observed` key is dropped, never read: a record's self-report never counts.

**Setup ops** run inside the pole's clone before `argv`:

```json
{"op": "replace", "path": "rel/path", "old": "text occurring exactly once", "new": "replacement"}
{"op": "write", "path": "rel/path", "content": "full file text"}
{"op": "delete", "path": "rel/path"}
```

Every op's `path` must be one of the claim's `subjects` (`setup-outside-subjects:<path>`): the allowlist, not a list of config names, keeps a record
from writing a test, `conftest.py` or any pytest/tox config. No RED may `delete`; no op may touch the guard file itself. A refused op runs no pole.

**Commands.** A guard is **pytest** when it names a node (`path::node`) or a `test_*.py` / `*_test.py` file; any other guard (a script, a lint, a
`.sh` gate) is not. A pytest guard's record carries **no `argv`** and **no `expect.exit`** (`pytest-argv-supplied`, `pytest-exit-supplied`, refused before any run): `certify.py` runs
`sys.executable -m pytest ./<path>[::<node>] --junitxml=<pole dir>/junit.xml --rootdir=<tree> --confcutdir=<tree> -p no:cacheprovider -o addopts= -o junit_family=xunit1` (`<tree>`: the resolved pole tree), so a node guard never runs as its file,
and no repo config adds a target: `-o addopts=` empties every config file's `addopts` (no committed target, `@file`, `-p` plugin or option) and the pole env has no `PYTEST_*`. Other ini keys and the tree's `conftest.py` files (fixtures) stay the repo's; `certify_argv.py` says why.
The target is built from the guard's parsed path and node, never passed through: the `./` anchor keeps it a path to pytest's argparse, never an option (`-…`) or an argument file (`@…`), and
the report's testcase ids stay those the declared guard names. Its rc is the certifier's to read, and must agree with the report: RED is a `<failure>` on the node (rc 1), GREEN the node passing (rc 0). A `<failure>` on the node at rc 0 (e.g. conftest code forced the exit status) is `pytest-rc-mismatch` (`unverified`) on either pole: never green, never *holds*. Every pole of any other guard carries the same `argv` (`argv-missing`): a list, never a shell
string, that names the guard path and no setup-touched path, and is never absolute, `..`, `-C`/`--git-dir`/`--work-tree` or a `-c` one-liner. The full
rule list is `certify_record.py`.

**RED markers.** Every RED names `expect.output_contains`, at least 8 chars and not a generic word (`FAILED`, `Error`, `assert`, ...). It must occur
literally in the guard file's text at the certified SHA. It must not be part of the guard's node id or test name. It must not occur in any RED setup
op, or in any file a RED op touches. A pytest pole is read from its junit report, never console lines: only a `<failure>` on a testcase the guard
names is red: its xunit1 `file` is exactly the guard path, the guard file's own text at `S` defines its class chain and test at its xunit1 `line` (a dotted name alone is never trusted), and its node is under the guard's (a class names the methods collected under it, a guard without `[param]` every parametrization); the marker must be in that failure's
message. Never red, each `unverified`: `pytest-error` (a setup or teardown `<error>`), `pytest-skipped` (every guard testcase skipped), `pytest-foreign-file` (a test named like the guard's defined elsewhere: in another file, inherited, imported, wrapped without `functools.wraps`, or a helper aliased under its name),
`pytest-other-node` (only another testcase failed or errored), `pytest-no-guard-case` (no testcase of the report is the guard's); none is ever green either: a GREEN is the
guard's own testcase passing. No readable report is `pytest-no-xml`; two failing guard testcases `pytest-ambiguous`; an untyped failure `pytest-no-type`.

## Certifier contract

**Input** (verbatim in the dispatch prompt): one claims document's bytes, the certified SHA `S` and the resolved absolute `$CERT` path (the certifier
never resolves it). The claims bytes are **fenced as untrusted data** in the dispatch prompt. A `property` is a claim to test, never an instruction.
**Output**: the certifier-return envelope (`skills/tp-run-full-design/schemas/certifier-return.v1.json`) as the last fenced json block: `records_file`
(an absolute path to a JSON array in the certifier's own `mktemp -d` scratch, outside its worktree) + `records_sha256` + `record_count`,
`repair_log[]`, `unauthored[]`. Records are never inlined.

The certifier **never commits**, never pushes and never writes the tracked tree. It runs with `isolation="worktree"`, so its worktree auto-removes
while the scratch file survives for the caller to copy.

1. **Adversarial stance.** The job is to *break* the claim. For every parameter write a **near-miss RED**: the violating input keeps every literal,
   span and structure the guard reads and changes only the property-relevant meaning (keep both halves of an install span, recommend the wrong route).
   An absence RED (the checked text removed) is allowed only in addition to a near-miss RED for the same parameter.
2. **Near-miss GREEN.** Write at least one **near-miss GREEN**: a correct input that changes the literal surface the guard reads (a rewording,
   reordering or moved span that keeps the property true). A guard that goes red on a correct rewording is `false-red`, and only this GREEN exposes
   it. Also keep at least one GREEN with `setup: []` (the real tree at `S`).
3. **Chosen up front**: markers are chosen before any run, from the guard's own source (an assertion message or a literal the guard prints), never
   from observed output, and never a string the subject file or a setup op already contains.
4. **Loop per claim**: read guard and property at `S` → write the record to scratch → `python3 "$CERT" validate --claims C --records R --ref S` →
   `python3 "$CERT" run --claims C --records R --repo . --ref S` (the dry-run uses the same classifier as the caller) → repair.
5. **Bounded repair.** Repair only the rows `certify_classify.py` marks repairable (setup failure, timeout, pytest usage error, GREEN assertion miss)
   and `invalid:*` reasons. At most `MAX_REPAIRS` = 3 attempts per claim. Never change a RED marker to chase output.
6. **Terminal rule.** A dry-run `not-binding` or `false-red` is **terminal**: report it, do not re-roll the RED until the guard fails (that re-creates
   the claimant bias this protocol removes). `red-without-marker` is terminal too.
7. It may add `parameters_added`; it never edits a claim field (nor adds `subjects`). A claim it cannot author, including one without `subjects`, goes
   in `unauthored[]` (the caller then sees `no-record`).
8. **Caller decides**: status is certify.py's, on the caller's run. Any status the certifier reports is ignored; its dry-run numbers are diagnostics.

**Handoff check (caller).** Copy `records_file` to scratch, then `python3 "$CERT" handoff --certifier-return <envelope> --records <copy>`: a missing
copy, a sha256 or `record_count` mismatch, or a certifier `status` other than `pass` exits 1 (`records-handoff`). The caller then runs that claims
file with `--unverified records-handoff` in place of `--records` (every claim `unverified`, no pole runs) and folds it.

## Statuses

`binds` (every RED red, every GREEN green) · `not-binding` (a RED stayed green: the guard said *holds* on a violating input) · `false-red` (a GREEN
went red: the guard lies about a correct input) · `unverified` (no record, a validation reason such as a refused argv or setup path, a crash, a
timeout, the budget, or a mutated caller tree) · `known-bypass` (binds, and the guard documents the bypass). No record is `unverified` (`no-record`).
Any exception is `unverified`: certification fails closed.

## Verdicts

The audit verdict is a join over the total order **NEEDS WORK > UNVERIFIED > KNOWN BYPASS > PASS WITH NOTES > PASS** (`combine_verdict`).
`not-binding`/`false-red` → NEEDS WORK (normal retry-with-advice); `unverified` → UNVERIFIED (blocks PASS; in `--auto` it escalates as
`certification-unverified`, never retry-with-advice); `known-bypass` → KNOWN BYPASS (non-blocking; recorded verbatim); `binds` → PASS. With no claims
the verdict is unchanged. The fold strips any model-supplied `certifications`/`uncertified_phrases`/`certification_base`. A model-asserted
`unverified` or `known-bypass` verdict becomes UNVERIFIED with a `model-asserted` finding. Only `verdict`-disposition results fold.

## Tags and the Guards certified section

Every audit artifact carries a `## Guards certified` section listing each claim and its status, or only the line `No guard claims.` A certifying
sentence elsewhere (in the artifact, an envelope `summary` or a finding `description`) is **matched** only if the same field carries `[cert:<id>]` for
a returned claim: the tag alone binds, the sentence need not repeat the `guard` path. A council member's summary field (no tags) needs only name the
`guard` path of some returned claim. Every other hit of the phrase scan is **unmatched** and adds one `unverified`. A missing section is one unmatched
hit. A body of exactly `No guard claims.` (not text quoting it) leaves every hit unmatched. `suggested_fix` is never scanned. A negator suppresses
nothing: "no test catches it" is a hit like "the test catches it", so a guard that does not bind is described without the certifying wording.

## Three-outcome checker rule

A check reports one of three outcomes: **holds**, **violated**, or **could not evaluate**. It must never report PASS when it could not observe the
thing it checks. A missing input, a crashed subprocess, an unreadable file or a swallowed exception is *could not evaluate*, never *holds*. So: no
`|| true` on a check's own command, no bare `except:` or `except Exception: pass` around the observation, and no `subprocess.run` whose result is
never read. Where a fail-open line is intended, it carries `tp-allow-fail-open: <reason>` inline.

## Step 2b

The orchestrator runs this in Tier 5 after Step 2's synth, on every Slot 8 attempt. All reads come from one captured SHA
`S = git rev-parse origin/candidate/{slug}/single`. No certifier write reaches any branch.

1. **Claimant-record check.** `python3 "$CERT" claimant-check --base tp/{slug} --ref S --design {design}` over
   `git diff --no-renames --name-only tp/{slug}...S` (a rename lists its old path too). A path under
   `{design}/certifications/` that is not a top-level `*.claims.json`, or `{design}/sweep-ledger.md`, exits 1 and
   escalates `certification-unverified` (reason `claimant-records`). A candidate carries claims only.
2. **Inputs.** The synth's `guard_claims[]` (disposition `verdict`) are written by the orchestrator to
   `{design}/certifications/records/impl-audit.claims.json` on `tp/{slug}`. Every top-level
   `{design}/certifications/*.claims.json` in `S` is read with `git show S:<path>` into scratch; those bytes are what
   the certifier receives and what `certify.py` reads. `disposition-name` is checked per file. A `ledger` claim whose
   guard path is in the step 1 diff (a guard this candidate changed) folds as verdict (step 5 `--verdict-guards`).
3. **Dispatch** `Agent(subagent_type="tp-certifier", isolation="worktree", model="opus")` once per claims file,
   **every attempt** (earlier records are never reused), verdict files first. Copy each `records_file` to
   `<scratch>/r<N>.records.json` (step 4's `<N>`), `python3 "$CERT" handoff --certifier-return <envelope> --records
   <copy>` (exit ≠ 0 → step 4 runs that file with `--unverified records-handoff`), then copy the bytes to
   `{design}/certifications/records/<x>.json` for an `<x>.claims.json` (`records/impl-audit.json`) on `tp/{slug}`
   (committed at step 7).
4. **Run** per file (Bash timeout 600 s; `--budget-s` defaults to 480 s, enforced per pole):
   `python3 "$CERT" run --claims <scratch> --records <scratch> --repo . --ref S --name <name>
   --watch-ref refs/heads/tp/{slug} --watch-ref 'refs/remotes/origin/candidate/{slug}/*' --out <scratch>/r<N>.result.json`.
   `<name>` is the file's path under `{design}/certifications/` (`records/impl-audit.claims.json`,
   `impl-audit.claims.json`), so no two results share a name: `fold` rejects a repeated (file, id) as bad input.
   `<N>` is the file's 1-based index in dispatch order: a token derived from `<name>` could collide
   (`records/x` against a candidate's `records-x`) and one result would overwrite the other.
   `--out` is written atomically with `complete: true`. A missing or incomplete `--out`, or any exit ≠ 0 (3 = caller
   tree mutated), makes every claim of that file `unverified` → `certification-unverified`.
5. **Fold once**: `python3 "$CERT" fold --envelope <synth envelope> --result <each result> --slot 8
   --member-summaries <clipped R1 argument_summary + R2 counter_argument> --out <scratch>
   --verdict-guards <scratch>/diff.txt` (`git -c core.quotePath=false diff --no-renames --name-only tp/{slug}...S >
   <scratch>/diff.txt`: the step 1 diff, one path per line, a non-ASCII path left unquoted). A sweep result folds
   only its claims on a listed guard path. An envelope `guard_claims[]` id with no entry from a `records/` result
   folds `unverified` (`no-result`), so a lost result never drops a claim. Its output replaces the Step 2 envelope.
6. **Ledger files** (`certify_ledger.py`, resolved as `$CL` above), only when a `sweep-NN.claims.json` or
   `self.claims.json` exists in `S` (otherwise no ledger or self rows exist and this step is skipped):
   `python3 "$CL" ledger render --inventory {design}/sweep/inventory.json --triage {design}/sweep/triage.json --result
   <each sweep result> [--self-result <self result>] --out {design}/sweep-ledger.md`; `python3 "$CL" ledger verify
   --ledger {design}/sweep-ledger.md --result …` (mismatch → `unverified`); `python3 "$CL" issues render --result …
   --out {design}/certifications/records/known-issues.pending.md`. Step 2b only renders: `python3 "$CL" issues apply
   --pending … --known-issues three-pillars-docs/known_issues.md` runs after the Tier 5.6 fold, on the folded tree
   (clean folds only), so each next-free id is re-derived past any entry the candidate added. The candidate never files
   these entries itself.
7. **Commit once**: assert `git symbolic-ref --short HEAD` is `tp/{slug}`, then make one commit of the step 2
   claims, the step 3 records and the step 6 files. No earlier step commits.

Then, in order on every audit return: map-check → `certification-unverified` (folded `verdict == unverified`, `records-handoff`, `tree_mutated`,
`claimant-records`, or a certify.py failure) → `status`. `certification-unverified` escalates to the operator; it is never re-spawned with advice.

**Slot 4** uses steps 2–5 and 7 with `S` = the `tp/{slug}` HEAD SHA, claims at `certifications/records/design-audit.claims.json`, records at
`certifications/records/design-audit.json`, `--watch-ref refs/heads/tp/{slug}` and `fold --slot 4` (no member summaries; an unmatched hit escalates
exactly as in Slot 8, even when the guard it names does not exist yet).

**Interactive surfaces** (`/tp-implementation-audit`, `/tp-design-audit`, `/tp-phase-review`, in a main conversation): write
`certifications/<surface>.claims.json` and the `## Guards certified` section, dispatch the certifier the same way with `S = HEAD`, copy `records_file`
under `certifications/records/` after `python3 "$CERT" handoff --certifier-return <envelope> --records <copy>` (exit ≠ 0 →
`--unverified records-handoff`), then `python3 "$CERT" run --artifact <artifact> …` prints the combined verdict. With no claims the artifact is still
scanned: `python3 "$CERT" scan --artifact <artifact>` prints the verdict the artifact's own verdict joins. A skill running as a subagent (no Agent
tool), or `--auto` without a certifier result, marks its claims `unverified` (`certifier-unavailable`) → BLOCKED, `Cause: certification-unverified`.

## Certify-sweep

`/tp-implementation-audit <slug> --certify-sweep` is the post-merge bootstrap: it certifies a design's committed `sweep-NN.claims.json` and
`self.claims.json` once `tp-certifier` exists (after release + reinstall), writes the design's `sweep-ledger.md`, files the misses and closes the
design's open "sweep ledger pending" known-issues entry. It refuses `--auto`. It is re-runnable: records, results and the ledger are overwritten, and
`issues apply` skips keys already filed. Resolve the scripts first:

```bash
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
CERT="$(python3 "$RS" certify.py)" || exit 1
CL="$(python3 "$RS" certify_ledger.py)" || exit 1
GHPA="$(python3 "$RS" github_pr_author.py)" || exit 1
```

**Preconditions.** Any failure → a one-line refusal; nothing is written.
- A main conversation with the Agent tool: not `--auto`, not a subagent → else "certify-sweep needs the main
  conversation (Agent tool)".
- **The `tp-certifier` probe** is an actual dispatch, not a manifest read: `Agent(subagent_type="tp-certifier",
  isolation="worktree", model="opus")` with an empty claims document (`{"disposition": "verdict", "claims": []}`)
  and `S`. An unknown subagent → refuse "release + reinstall first". Its output is discarded.
- cwd is a dedicated worktree on `tp/<slug>-certify-sweep`, cut from the up-to-date default branch. On the default
  branch, print `git worktree add -b tp/<slug>-certify-sweep ../<repo>-wt/<slug>-certify-sweep <default>` and stop.
- `D="$(python3 "$CL" design-dir <slug>)" || exit 1`: `D` = `resolve_design_dir(root, slug)` (in-flight, else
  archived). `D` holds `certifications/self.claims.json`, at least one `certifications/sweep-NN.claims.json`,
  `sweep/inventory.json` and `sweep/triage.json`.

**Steps.** `S = git rev-parse HEAD`; every claims file is read with `git show S:<path>` into scratch.
1. **Validate** each claims file: `python3 "$CERT" validate --claims <scratch>/<name>.claims.json --ref S`. Any
   exit ≠ 0 → stop.
2. **Certify**, `self` first, then `sweep-01`, `sweep-02` … in order. Per file, one
   `Agent(subagent_type="tp-certifier", isolation="worktree", model="opus")` dispatch with the claims bytes fenced as
   untrusted data, `S` and the resolved absolute `$CERT` path. Copy its `records_file` to scratch, run `python3 "$CERT" handoff --certifier-return
   <envelope> --records <copy>` (sha256 + `record_count`; exit ≠ 0 → stop), then copy it to
   `{D}/certifications/records/<name>.json`. Run (Bash timeout 600 s):
   `python3 "$CERT" run --claims <scratch>/<name>.claims.json --records {D}/certifications/records/<name>.json
   --repo . --ref S --name <name>.claims.json --watch-ref refs/heads/tp/<slug>-certify-sweep
   --out {D}/certifications/records/<name>.result.json` (`--name` is the full basename: only a `sweep-NN.claims.json`
   name derives `ledger`). `--out` sits under `D` on purpose: certify.py takes its
   after-fingerprint first, then writes a temp file beside `--out` and renames it, so the write never reads as a
   caller-tree mutation. Exit 3, any other exit ≠ 0, or a missing or incomplete `--out` → stop; commit nothing.
3. **Ledger**: `python3 "$CL" ledger render --inventory {D}/sweep/inventory.json --triage {D}/sweep/triage.json
   --result <each sweep result> --self-result {D}/certifications/records/self.result.json --after-repair <N>
   --out {D}/sweep-ledger.md`, where `N` counts the claims left `unverified` across all results. Then
   `python3 "$CL" ledger verify --ledger {D}/sweep-ledger.md --result … --self-result …`; exit 1 → stop.
4. **Issues**: `python3 "$CL" issues render --result … --self-result … --out
   {D}/certifications/records/known-issues.pending.md`, then `python3 "$CL" issues apply --pending
   {D}/certifications/records/known-issues.pending.md --known-issues three-pillars-docs/known_issues.md`. Every
   `not-binding`/`false-red` sweep row and every self row that is not `binds`/`known-bypass` is filed; a
   self-certification miss is never silent. A claim without `subjects` is `unverified` (`no-subjects`), counted in `N`.
   A phrase hit that a fresh `certify_sweep.py inventory` over `S` finds beyond the committed snapshot (one a later scan
   change newly counts, such as a negated hit) is no ledger row and is never re-triaged: it fails closed as
   `unverified` and escalates once, one line per hit in the step 7 PR body, for the operator.
5. **Close the pending entry**: move the `known_issues.md` entry whose heading holds "sweep ledger pending" and the
   slug, verbatim, to `known_issues_resolved.md`, adding `(RESOLVED <date>)` to its heading and a `**Status**` line
   naming `{D}/sweep-ledger.md`.
6. **Coherence**: where the repo carries a sweep-coherence test for the design (the framework's own repo does:
   `python3 -m pytest skills/_shared/test_sweep_coherence.py -q`), it must pass. Otherwise → stop.
7. **Commit + PR**: assert `git symbolic-ref --short HEAD` is `tp/<slug>-certify-sweep`. Scoped `git add` of exactly
   `{D}/certifications/records/`, `{D}/sweep-ledger.md`, `three-pillars-docs/known_issues.md` and
   `three-pillars-docs/known_issues_resolved.md`; commit `certify: <slug> sweep ledger + self-certification`; push
   fail-open. Open the PR through the PR-author chokepoint: `python3 "$GHPA" create --context manual -- --base
   <default> --head tp/<slug>-certify-sweep --title "certify: <slug> sweep ledger + self-certification"`. Exit 3
   (bot account unavailable): surface its stderr, never retry with ambient auth. The PR merges through `/tp-merge`.

Its only writes are the design's own new files and the two known-issues docs; no swept design's artifact is touched.

## KNOWN BYPASS list

These are contract, not mechanism. Each is stated here and, where it lives in code, in that module's docstring.

- **Authorship.** The near-miss rule and the dry-run terminal rule are contract. A certifier that writes only absence REDs, or probes REDs
  with exploratory Bash before its first dry-run, can still certify a tautological guard (the absence-only fixture
  pins that case as `binds`). The claimant's free-text `property` is also a steering channel into the certifier
  prompt: one line, at most 300 chars, fenced as untrusted data, it can still steer which RED is chosen. Mitigation:
  independent authorship, the adversarial contract, and operator-visible records.
  - **In-process hook (bad-faith certifier).** The allowlist bounds which files a setup op writes, not what a Python subject does once the guard imports it
    into pytest's process: a RED `write` to a declared `.py` subject can register a pytest hook (e.g. a `pytest_runtest_call` hookwrapper on the live `Config`)
    that forges the declared node's `<failure>` with the marker built at runtime from the guard's text, so a vacuous guard certifies `binds`. Only a
    bad-faith certifier writes such a RED; the mitigation is the Authorship one. Committed code at `S` runs in pytest's process: conftest code (fixtures guards need, so it still loads), and any committed module shadowing an import (the tree is first on `sys.path`: a `pytest.py`, a package named like an installed plugin such as `xdist/`, a lazily imported stdlib name). It can add a target, whose testcases are the guard's only where the guard file defines them at their reported `line` (an alias of a guard-file helper is not), or deselect the guard (`pytest-no-guard-case`); forging the guard's own `<failure>` is this hook, in code review reads.
- **Rewording contract.** That the perturbed GREEN is a *correct rewording* is contract. The mechanism only requires
  one GREEN with a non-empty setup.
- **The interactive relay.** In the interactive skills (and the post-merge certify-sweep) the auditor copies the
  certifier's `records_file`; a substitution of file *and* sha256 is not detected. In Slots 4 and 8 the copier is the
  orchestrator, not the claimant. Mitigation: the sha256 check, and records shown in `## Guards certified`.
- **Phrase scan.** A certification phrased outside the scan's literal list and its guard-noun proximity form escapes
  the scan (`cert_phrase_scan.py`).
- **Records copy.** A candidate's top-level `impl-audit.claims.json` (Slot 4: `design-audit.claims.json`) gets the
  same step 3 copy path as the synth's claims (`records/impl-audit.json`): the later copy overwrites the earlier.
  Only the committed traceability copy is lost; `run` reads each file's own scratch copy, so no status changes.
- **Caller-tree fingerprint, marker provenance, declared parameters.** See the `certify.py` docstring.
