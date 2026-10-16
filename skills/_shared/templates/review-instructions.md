# Review instructions

This file is the project-specific standard a reviewer applies on top of the
generic blocking bar. Fill it in for your repo: a reviewer reading a diff
against `base...head` applies exactly this, so keep it short, concrete, and
unambiguous. Everything here is guidance for both human and automated
reviewers; the blocking bar at the bottom is the decision rule.

## Scope

State what a review covers for this repo. Name the surfaces a reviewer should
read a change against: the product's own stated behaviour, its documented
contracts, and the mechanical checks that already run in CI. Keep this to the
fewest sentences that pin down what "correct" means here, so two reviewers
mean the same thing.

## Known-intentional patterns

List the recurring patterns in this repo's diffs that are **deliberate**, so a
reviewer does not re-flag them as defects. For each, give a short name and one
line on why it is intentional and why it is not a defect. Leave this section
empty until you have real entries — a reviewer should never have to guess.

<!-- Example entry format:
- **`Name of pattern`.** One line on why it is deliberate and why it is not a defect.
-->

## What counts as a real defect

Name the concrete failures that are real defects for this project, not generic
code smells. Prefer things that break a user's shipped behaviour or a
documented contract and can be shown failing. Consult the canonical sources
your project keeps for its own rules rather than restating them here.

## Blocking bar

Only a demonstrated shipped-behaviour defect with a reproducer blocks; mutation survivors, test-tightening, exotic env, lint-guard bypasses, style and perf are non-blocking notes.

## Promises vs enforcement

Flag shipped text that promises enforcement by a mechanism that does not ship
or run where it is read. A sentence saying a guard, check, or lint "enforces"
a property is trustworthy only if that mechanism actually ships and runs in the
context where the claim is read — a promise backed by a mechanism absent from
the read environment is a real finding, not a style note.

- Key: `promises-vs-enforcement` — shipped text promising enforcement by a
  mechanism that does not ship or run where it is read.
- Key: `forge-parity` — a forge-facing change with no stated Gitea behaviour, a
  silent Gitea no-op, or a direct `gh` call that bypasses `forge.py` (per
  `skills/_shared/forge-parity-rule.md`).
