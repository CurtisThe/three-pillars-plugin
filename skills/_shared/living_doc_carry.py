"""living_doc_carry.py — leaf helpers for the living-doc hand-resolution carry.

A second certification path for `base_sync_cert.py` that preserves a human PR approval
across a base-sync merge whose only files differing from a clean mechanical merge are
inert living-doc prose — without requiring byte-exact reproduction of those files, while
keeping zero-drop and every backstop in force. See
`three-pillars-docs/completed-tp-designs/livingdoc-handres-preserves-approval/detailed-design.md`.

House invariants for this certifier path: **stdlib-only, total, never raises**; every new
branch fails closed. This module holds all new *logic*; `base_sync_cert.py` gains only a
minimal kwarg-thread + a 2-line fallback per entry point (Phase 3).

Phase 1 scope (this file): the three pure helpers —
  - `is_living_doc_carry_path(path)`      — the carry-set predicate (single definition of
                                            the two authority exclusions).
  - `carry_livingdoc_handres_enabled(config)` — the default-ON config interpreter.
  - `regenerate_preamble_date(doc_text)`  — the `## History` → date derivation.
The relaxed link certifier (`certify_link_carry` + private resolve helpers) lands in
Phase 2 via a function-local `import base_sync_cert as bsc`; both cross-module import
directions are function-local, so there is no module-load cycle.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# The zero-drop verifier — the ONE backstop that runs on BOTH relaxed-cond5 branches (inside
# `_mechanical_resolution` before any byte-exact `continue`, M2, and on the hand-res committed
# blob). Reached via the same `Path(__file__)`-relative sys.path shim `base_sync_cert.py` uses.
# `base_sync_cert` itself is imported FUNCTION-LOCALLY (inside `certify_link_carry` /
# `_relaxed_resolve` / `_mechanical_resolution`), so there is no module-load cycle.
_MERGE_SCRIPTS = Path(__file__).resolve().parent.parent / "tp-merge-from-main" / "scripts"
if str(_MERGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MERGE_SCRIPTS))
import verify as _verify  # noqa: E402


# ============================================================
# Task 1.1: is_living_doc_carry_path — the carry-set predicate
# ============================================================
#
# `.md`-suffix + location-scoped — never a directory glob: 18 `.py`, 8 `.sh`, 280 `.json`,
# 4 `.yml`, lock.json envelopes all live under the docs root, so a `tp-designs/**` glob
# would be a smuggling hole. Root prose is exact-match-at-root only; root CLAUDE.md is
# excluded (behavioral agent instructions, not living-doc prose).

_CARRY_ROOT = "three-pillars-docs/"
# The two authority exclusions — the SINGLE definition of each (a single-definition guard
# test pins that neither literal is duplicated, so a future engine-fed `.md` cannot join):
_SPECS_PREFIX = "three-pillars-docs/specs/"          # the specs subtree (pipeline contracts)
_PROJECT_CONTEXT = "three-pillars-docs/project-context.md"  # the machine-fed context doc
_ROOT_PROSE = frozenset({"README.md", "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE"})


def is_living_doc_carry_path(path) -> bool:
    """True iff `path` (a repo-relative POSIX path) is a living-doc carry-set member.

    Total; any non-str / exception fails closed to False. Pure string ops (git plumbing
    never emits `..` or backslashes in tree paths).

        True  iff  path in _ROOT_PROSE                         # exact repo-root prose
                OR (path.endswith(".md")
                    and path.startswith(_CARRY_ROOT)
                    and not path.startswith(_SPECS_PREFIX)
                    and path != _PROJECT_CONTEXT)
    """
    try:
        if path in _ROOT_PROSE:
            return True
        return (
            path.endswith(".md")
            and path.startswith(_CARRY_ROOT)
            and not path.startswith(_SPECS_PREFIX)
            and path != _PROJECT_CONTEXT
        )
    except Exception:
        return False


# ============================================================
# Task 1.2: carry_livingdoc_handres_enabled — default-ON config interpreter
# ============================================================


def carry_livingdoc_handres_enabled(config) -> bool:
    """Read `review.living_doc_handres_preserves_approval` as a **default-ON** flag.

    The deliberate INVERSE of the strict-OFF `base_sync_cert.carry_enabled`: returns
    **False only on a literal `False`**; **True** on absence / non-dict config / non-dict
    `review` / non-bool value / any exception (fail-*toward-default*). Intentional and
    safe — the design's compounding note pins that soundness rests on the carry-set
    predicate + the code-unchanged (cond4 + zero-drop) guards + `ci_local_stamp`, **not**
    on this flag being off. This flag is only ever read *inside* an already-carry-enabled
    repo (nested under the pre-existing default-OFF outer gate).
    """
    try:
        review = (config or {}).get("review") if isinstance(config, dict) else None
        if not isinstance(review, dict):
            return True
        return review.get("living_doc_handres_preserves_approval") is not False
    except Exception:
        return True


# ============================================================
# Task 1.3: regenerate_preamble_date — the `## History` → date derivation
# ============================================================
#
# Only the *date* of a preamble conflict is byte-deterministic; the `Most recent: <summary>`
# clause is a human paraphrase and is NOT byte-reconstructable, so `_mechanical_resolution`
# upgrades a preamble conflict only when the two sides differ *solely* in the date.

_HISTORY_HEADING_RE = re.compile(r"^#{1,6}\s.*History")   # heading TEXT contains "History"
_ATX_HEADING_RE = re.compile(r"^#{1,6}\s")               # any ATX heading — bounds the scan
# Dated atom bullet — the trailing `\s+—` em-dash (U+2014) makes it genuinely match
# `verify.LOG` / `classify.LOG_ENTRY`, not a bare bold date:
_DATED_BULLET_RE = re.compile(r"^-\s+\*\*(\d{4}-\d{2}-\d{2})\*\*\s+—")


def regenerate_preamble_date(doc_text) -> "str | None":
    """Return the ISO date of the topmost dated bullet in the doc's first `## History`
    section, else `None`. Total; any exception → `None` (never fabricates a date).

    - Scan for the first heading matching `^#{1,6}\\s.*History` (so both `## History` and
      roadmap's `## Roadmap History` match).
    - From the line after it **up to (exclusive) the next ATX heading** (F4: bound to the
      History section — a later section's dated bullet must never leak in), return the date
      of the first bullet matching `^-\\s+\\*\\*(\\d{4}-\\d{2}-\\d{2})\\*\\*\\s+—`.
    - History absent / present-but-empty / present with no matching dated bullet → `None`.
    """
    try:
        lines = doc_text.splitlines()
    except Exception:
        return None
    try:
        n = len(lines)
        for i in range(n):
            if not _HISTORY_HEADING_RE.match(lines[i]):
                continue
            # Bound the scan to this History section: up to the next ATX heading.
            j = i + 1
            while j < n and not _ATX_HEADING_RE.match(lines[j]):
                m = _DATED_BULLET_RE.match(lines[j])
                if m:
                    return m.group(1)
                j += 1
            return None   # first History section had no matching dated bullet → defer
        return None       # no History heading at all → defer
    except Exception:
        return None


# ============================================================
# Task 2.1: _has_conflict_markers — the F5 marker guard
# ============================================================

# git writes each flank/base marker as EXACTLY seven sigil chars followed by a space (a label,
# e.g. `<<<<<<< HEAD`) or end-of-line (a bare marker) — never 8 sigils, never a sigil run
# immediately abutting other content. Match that exact shape so a marker LOOKALIKE in inert
# carry-set prose (a fenced `<<<<<<<`-example, an 8-`<` arrow, a mid-line run) does NOT
# false-positive → a needless re-approval on inert prose, the very tax this design removes. This
# is a strict SUBSET of the prior 7-char-prefix check (fires on FEWER lines) and still catches
# every real git conflict marker (git always emits `<<<<<<< label` or a bare `<<<<<<<`).
_FLANK_RES = (
    re.compile(r"^<{7}( |$)"),
    re.compile(r"^>{7}( |$)"),
    re.compile(r"^\|{7}( |$)"),
)
# DELIBERATE fail-closed residual (F5, design.md §Threat model): the orphaned `=======` divider
# (a partial cleanup that stripped the flanks but left the middle) is kept as `^={7}$`. A lone
# 7-char `=======` line is indistinguishable from a markdown setext-H1 underline / horizontal
# divider, so this CAN over-refuse a carry-set doc that literally contains such a line in a
# hand-resolved region. The over-refusal is the SAFE direction (fail closed → re-approve), and
# the design accepts it to keep the partial-cleanup guard. NOT weakened.
_ORPHAN_DIVIDER_RE = re.compile(r"^={7}$")


def _has_conflict_markers(text) -> bool:
    """True iff `text` bears an unresolved conflict marker (F5): a line matching git's exact
    flank/base shape (`^<{7}( |$)` / `^>{7}( |$)` / `^\\|{7}( |$)`), OR a line that is solely
    seven `=` (`^={7}$`, an orphaned divider). A cheap, total guard so a not-actually-resolved
    committed blob can never ride the carry. Total; any exception → False."""
    try:
        for line in text.splitlines():
            if any(rx.match(line) for rx in _FLANK_RES):
                return True
            if _ORPHAN_DIVIDER_RE.match(line):
                return True
        return False
    except Exception:
        return False


# ============================================================
# Task 2.2: _mechanical_resolution — M2 zero-drop + F1 kw-only + DEFER→date upgrade
# ============================================================
#
# Only the preamble *date* is byte-deterministic; the `Most recent: <summary>` clause is a
# human paraphrase and is NOT reconstructable — so a DEFER is upgraded to a clean mechanical
# merge ONLY when the two sides differ *solely* in the `*Last updated:*` date (mirror
# reconcile_docs._LAST_UPDATED_RE). Any richer divergence defers to the hand-res carry path.
_PREAMBLE_DATE_RE = re.compile(r"(\*Last updated:\s*)\d{4}-\d{2}-\d{2}", re.IGNORECASE)
_DATE_MASK = "0000-00-00"


def _mechanical_resolution(base, ours, theirs) -> "str | None":
    """Attempt a byte-deterministic mechanical merge of ONE conflicted path (M2 + F1).

    Calls `resolve_conflict_bytes(base=…, ours=…, theirs=…)` **keyword-only** (F1: a positional
    call raises `TypeError` by design). On RESOLVED, re-runs `verify.verify(ours, theirs, merged,
    mechanical_applied=True)` FIRST — mirroring strict `_cond5_resolve`, which re-verifies even
    after RESOLVED — and returns `None` unless the three-state verdict is `VERIFIED` (M2: the
    byte-exact `continue` is never trusted without zero-drop). Both `DROPS_DETECTED` and
    `UNVERIFIABLE` are failures here: this lane DID apply a mechanical resolution, so parsing zero
    atoms means the shape is unknown to the verifier, not that nothing was lost. On DEFER, attempts
    the preamble-date upgrade (date-only divergence only) — itself a mechanical apply and so
    verified the same way — else `None` (genuine defer). Total; any exception → `None`."""
    try:
        import base_sync_cert as bsc
        status, merged = bsc.resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
        if status == bsc.RESOLVED:
            r = _verify.verify(ours, theirs, merged, mechanical_applied=True)
            return None if not r.ok else merged
        # DEFER — the only mechanical win left is a date-only `*Last updated:*` divergence.
        masked_ours = _PREAMBLE_DATE_RE.sub(lambda m: m.group(1) + _DATE_MASK, ours)
        masked_theirs = _PREAMBLE_DATE_RE.sub(lambda m: m.group(1) + _DATE_MASK, theirs)
        if masked_ours != masked_theirs:
            return None                       # richer-than-date divergence → genuine defer
        new_date = regenerate_preamble_date(ours)
        if new_date is None:
            return None                       # no History date to regenerate from → defer
        candidate = _PREAMBLE_DATE_RE.sub(lambda m: m.group(1) + new_date, ours)
        r = _verify.verify(ours, theirs, candidate, mechanical_applied=True)
        return None if not r.ok else candidate
    except Exception:
        return None


# ============================================================
# Task 2.3: certify_link_carry + _relaxed_resolve — the relaxed single-link certifier
# ============================================================


def _relaxed_resolve(git, conflicts: dict, h1: str):
    """Relaxed cond5 — replaces strict `_cond5_resolve`'s byte-exact hash gate. Returns
    `(reason, carry_paths)`: `reason` is "" on success with `carry_paths` a sorted list of the
    K hand-res carry files (empty if every conflict byte-matched a zero-drop-verified clean
    mechanical merge); on failure `reason` is the first fail-closed cause and `carry_paths` is
    None. First-failure-wins."""
    import base_sync_cert as bsc
    carry_paths = set()
    for path, stages in conflicts.items():
        # M1 — carry-set membership is the FIRST, UNCONDITIONAL per-path gate (before the shape
        # gate, before any cat-blob, before _mechanical_resolution, before the byte-exact
        # `continue`). Because cond3 is skipped and classify/_mechanical_resolution are
        # path-blind, a non-carry path whose committed blob coincidentally equals the mechanical
        # union would otherwise ride the byte-exact `continue`; gate it first, fail-closed.
        if not is_living_doc_carry_path(path):
            return "non-carry path differs from clean mechanical merge", None
        # content-conflict SHAPE gate — identical to strict cond5.
        if not all(s in stages for s in (1, 2, 3)):
            return "non-content conflict", None
        stage_modes = [stages[s][0] for s in (1, 2, 3)]
        rc, out, _err = git(["ls-tree", h1, "--", path])
        if rc != 0:
            return "git error: ls-tree failed", None
        parsed = bsc._parse_ls_tree_line(out)
        if parsed is None or parsed[0] != "100644" or any(m != "100644" for m in stage_modes):
            return "non-content conflict", None
        try:
            base_txt = bsc._cat_blob_strict(git, stages[1][1])
            ours_txt = bsc._cat_blob_strict(git, stages[2][1])
            theirs_txt = bsc._cat_blob_strict(git, stages[3][1])
            committed_txt = bsc._cat_blob_strict(git, parsed[1])   # the human's resolution (h1 blob)
        except UnicodeDecodeError:
            return "undecodable (non-UTF-8) blob content", None
        except bsc._GitOpError:
            return "git error: cat-file blob failed", None
        mech = _mechanical_resolution(base_txt, ours_txt, theirs_txt)   # M2/F1: zero-drop INSIDE
        if mech is not None and committed_txt == mech:
            continue   # byte-exact to a zero-drop-verified mechanical merge → K unchanged
        # --- hand-resolution: the trust relaxation, fully guarded ---
        if _has_conflict_markers(committed_txt):
            return "committed blob retains unresolved conflict markers", None
        # zero-drop on the committed h1 blob. `mechanical_applied=False` PERMANENTLY: no
        # mechanical resolution was applied on this lane — this site verifies whatever text has
        # landed at h1 for the path, and the code has no signal distinguishing a person's
        # hand-resolution from an unattended agent's reaching the same line.
        #
        # ACCEPTED RESIDUAL EXEMPTION (design §Constraints). A zero-atom blob can never raise
        # UNVERIFIABLE here, so future shape drift arriving on this lane still passes silently —
        # by construction, not by omission. That is the deliberate price of Behavior 2: this lane
        # legitimately carries free-form rewritten prose, so "parsed zero atoms" is not evidence
        # of a mistake here the way it is on the mechanical lane. The mitigations live elsewhere
        # — admitting the one KNOWN drifted shape (`tp-designs/*/decisions.md`) to the mechanical
        # lane, where UNVERIFIABLE does fire, and the cross-module coverage test that catches the
        # NEXT drift at commit time rather than at merge time. Closing it needs a different
        # signal than "atoms parsed" and is out of scope for this design.
        r = _verify.verify(ours_txt, theirs_txt, committed_txt, mechanical_applied=False)
        if not r.ok:
            return "zero-drop verifier detected a content drop", None
        carry_paths.add(path)
    return "", sorted(carry_paths)


def certify_link_carry(repo_root, h0: str, h1: str, *, base_ref: str, run_git=None):
    """The relaxed single-link certifier — same shape/contract as
    `base_sync_cert._certify_link_unchecked` (total, first-failure-wins, never raises; **no
    oracle guard here** — the caller already guarded). Orchestrates cond1 → cond2 → [skip cond3]
    → cond4 → relaxed-cond5, reusing `bsc`'s RME helpers BY REFERENCE via a function-local
    `import base_sync_cert as bsc` (breaks the module-load cycle). Returns
    `LinkCheck(ok, reason, conflicted_paths)` where `conflicted_paths` on success = the sorted
    K hand-res carry files (empty when every conflict byte-matched the mechanical merge)."""
    try:
        # The `import base_sync_cert` + git-seam setup are INSIDE the try so this helper is
        # independently total (never-raises) even if the seam construction throws.
        import base_sync_cert as bsc
        git = run_git or bsc._make_default_git(repo_root)
        parents, reason = bsc._cond1_merge_shape(git, h0, h1, base_ref)
        if reason:
            return bsc.LinkCheck(False, reason)
        _p1, p2 = parents
        tree, conflicts, reason = bsc._cond2_recompute(git, h0, p2)
        if reason:
            return bsc.LinkCheck(False, reason)
        # cond3 (AUTO_SAFE allowlist) is deliberately SKIPPED — the carry-set is broader than
        # AUTO_SAFE_PATHS; membership is enforced per-differing-path in _relaxed_resolve (M1).
        reason = bsc._cond4_containment(git, tree, conflicts, h1)
        if reason:
            return bsc.LinkCheck(False, reason, tuple(sorted(conflicts)))
        reason, carry_paths = _relaxed_resolve(git, conflicts, h1)
        if reason:
            return bsc.LinkCheck(False, reason, tuple(sorted(conflicts)))
        return bsc.LinkCheck(True, "", tuple(carry_paths))
    except Exception:
        # `base_sync_cert` is the only caller, so it is always import-cached here (the re-import
        # is a cheap dict hit); the caller-side wrap in `certify_link` guards the other direction.
        import base_sync_cert as bsc
        return bsc.LinkCheck(False, "internal error during link certification")
