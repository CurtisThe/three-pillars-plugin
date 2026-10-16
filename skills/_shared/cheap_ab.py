#!/usr/bin/env python3
"""cheap_ab.py — the cheap-tier A/B harness over dispatch telemetry (Behavior 6).

design: cheap-tier-offload (Phase 3)

Reads the `dispatch-telemetry.ndjson` rows that carry a `slot` (the cheap-dispatch
record step writes them) from every design under `three-pillars-docs/`, archived
designs included, and turns them into flip evidence:

- `arm(row)`: `opus` when the rung family is `opus`, else `cheap` (`code` included);
- `summarize(rows)`: per slot and arm, `{n, pass, rate, tokens}` plus `unpaired_on`.
  A pure slot is rated on **complete pairs only**: an `ab_pair` id with exactly one
  row per arm, keyed by (source ndjson file, slot, id), so two designs that reuse an
  id keep their own pairs (`load_rows` tags each row's file as `SOURCE_KEY`). Plain
  `on` rows (no `ab_pair`) count in `unpaired_on` and never enter a rate, and so do
  `rp-draft:` rows; a half
  pair is dropped. A pair with a `tokens: null` arm counts for the pass rate but not
  for the token sums. An effectful `code` slot (`runbook`) cannot run
  twice on one input, so its arms alternate across runs (D10): its rows carry
  `ab_pair: "alt:<slot>"` and are rated per arm, one row at a time. A slot with a complete
  pair also gets `served` and `local_slot` (`cheap_ab_served.served_summary`);
- `flip_verdict(summary, slot, rows)`: `exempt` for `task` (its evidence is #184 plus
  `task_opus_audit`; task rows carry no `slot`, so no pair can exist), `insufficient`
  when either arm has n < 2, `hold` when the opus arm never passed (0.00 vs 0.00 is
  no baseline) or the cheap rate is lower, else `flip`. A `local_slot` runs the same
  checks on its served `local` cell vs the served `opus` cell. The `review_prep` slots
  (`cheap_tier.REVIEW_PREP_SLOTS`) delegate to `review_prep_verdict(rows, slot)`:
  same-head pairs only, exact findings equality, fewer prep tokens (D12).

A row passes when its `oracle` field is `"pass"` (`cheap-dispatch.md` step 4 records
`--oracle pass|fail`, and `dispatch_log` refuses any other value with `--slot`); a row
with any other `oracle` is never rated. A flip is never automatic: it is a reviewed PR that sets
`cheap_tier.SLOTS[slot].default` (D6).

`budget(rows)` caps `ab` mode at 8M tokens over every `ab_pair` row, both arms,
except an `ab_arm: base` row (the real Opus angle runs anyway). Its
CLI reads `load_all_rows`: every worktree of the repo (`git worktree list`), so parallel
design runs see each other's in-flight rows (a line shared by several checkouts counts
once; an unreadable worktree is skipped). A `tokens: null` row is charged `UNKNOWN_ROW_TOKENS` (pessimistic, so
undercounting can only stop `ab` early), except a `code` row, which ran no model and is
charged 0, and an inline row (`agent: null`, the dispatcher ran it), which is charged
the mean measured tokens of its slot and arm, else of its arm, before the placeholder.
`alt_arm(rows, slot, taken)` picks the next arm of an effectful slot: `cheap` after an
even prior count, `opus` after an odd one. The count is the larger of the `alt:<slot>`
rows and `taken`, the picks the `alt-arm` CLI keeps in the git common dir
(`cheap_ab_state.ALT_STATE`):
tp-post-merge step 6 reverts a row it cannot commit, so the rows alone lose a pick.
CLI (every subcommand exits 0): `report --root R` (markdown table), `budget --root R`
(JSON), `alt-arm --slot S --root R` (the arm; advances the pick count, so run it once
per teardown). Stdlib-only; no model is ever called here.

"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import cheap_ab_served  # noqa: E402 — in-repo, stdlib-only sibling (the served-arm dimension)
import cheap_ab_state as state_file  # noqa: E402 — in-repo, stdlib-only sibling
import cheap_tier  # noqa: E402 — in-repo, stdlib-only sibling (REVIEW_PREP_SLOTS)
import dispatch_log  # noqa: E402 — in-repo, stdlib-only sibling
import prose_oracle  # noqa: E402 — in-repo, stdlib-only sibling (the edit metric)

ARMS = ("cheap", "opus")
ALT_PREFIX = "alt:"
DRAFT_PREFIX = "rp-draft:"  # the review-prep drafter's `ab_pair` prefix: charged, never paired
PAIR_PREFIX = "rp:"  # the review-prep pair id prefix (`rp-draft:...` does not start with it)
BUDGET_CAP = 8_000_000
UNKNOWN_ROW_TOKENS = 200_000
_DESIGN_TREES = ("tp-designs", "completed-tp-designs")
RATED = ("pass", "fail")  # the `oracle` values a row may carry (dispatch_log.SLOT_ORACLES)
SOURCE_KEY = "_source"  # the ndjson file a loaded row came from (pair ids are per file)


def _ndjson_paths(root) -> list[Path]:
    docs = Path(root) / "three-pillars-docs"
    seen: dict[Path, None] = {}
    for tree in _DESIGN_TREES:
        base = docs / tree
        if not base.is_dir():
            continue
        for design in sorted(p for p in base.iterdir() if p.is_dir()):
            path = dispatch_log.resolve_dir(design) / dispatch_log.NDJSON_NAME
            if path.is_file():
                seen.setdefault(path.resolve(), None)
    return list(seen)


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()]


def _row(line: str, source: str) -> dict | None:
    try:
        row = json.loads(line)
    except ValueError:
        return None
    return {**row, SOURCE_KEY: source} if isinstance(row, dict) else None


def _parsed(root):
    """Each non-blank ndjson line as a dict, or None when it is not a JSON object."""
    for path in _ndjson_paths(root):
        for line in _lines(path):
            yield _row(line, str(path))


def load_all_rows(root) -> tuple[list[dict], int]:
    """`load_rows` over every worktree of the repo. One ndjson (same repo-relative path)
    in several checkouts is merged line by line with each line's largest count, so a
    committed row every checkout carries counts once and an in-flight row counts too.
    A row under a different path in two checkouts (a design archived on one branch
    only) counts twice, which stops `ab` early. A worktree git lists but this process
    cannot read is skipped, so its rows are not counted (the CLI still exits 0)."""
    merged: dict[str, collections.Counter] = {}
    for tree in state_file.worktree_roots(root):
        try:  # a worktree removed or unreadable since the listing is skipped (exit 0)
            files = {p: collections.Counter(_lines(p)) for p in _ndjson_paths(tree)}
        except OSError:
            continue
        for path, counts in files.items():
            rel = path.relative_to(tree).as_posix() if path.is_relative_to(tree) else str(path)
            merged[rel] = merged.get(rel, collections.Counter()) | counts
    parsed = [_row(line, rel) for rel, counts in merged.items()
              for line in counts.elements()]
    return [r for r in parsed if r and r.get("slot")], sum(r is None for r in parsed)


def load_rows(root) -> tuple[list[dict], int]:
    """(rows carrying a `slot`, malformed line count) over every design's ndjson.
    A blank line is skipped silently; a line that is not a JSON object is counted."""
    parsed = list(_parsed(root))
    return [r for r in parsed if r and r.get("slot")], sum(r is None for r in parsed)


def arm(row: dict) -> str:
    """`opus` when the rung family is opus, else `cheap` (`code` and a missing rung too)."""
    return "opus" if str(row.get("rung") or "").split("-", 1)[0] == "opus" else "cheap"


def _passed(row: dict) -> bool:
    return row.get("oracle") == "pass"


def _tokens(row: dict) -> int | None:
    tokens = row.get("tokens")
    return tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None


def _blank() -> dict:
    return ({a: {"n": 0, "pass": 0, "rate": None, "tokens": 0} for a in ARMS}
            | {"unpaired_on": 0, "local_slot": False})


def _count(cell: dict, row: dict, tokens: bool) -> None:
    cell["n"] += 1
    cell["pass"] += int(_passed(row))
    if tokens:
        cell["tokens"] += _tokens(row) or 0


def summarize(rows: list[dict]) -> dict:
    """`{slot: {"cheap": {n, pass, rate, tokens}, "opus": {...}, "unpaired_on": n}}`."""
    out: dict[str, dict] = {}
    pairs: dict[tuple, list[dict]] = {}
    for row in rows:
        slot, pair = row.get("slot"), row.get("ab_pair")
        if not slot or row.get("oracle") not in RATED:
            continue  # an oracle other than pass/fail is never rated (not a silent fail)
        summary = out.setdefault(slot, _blank())
        if pair is None or str(pair).startswith(DRAFT_PREFIX):
            summary["unpaired_on"] += 1  # a `rp-draft:` row is charged by `budget` but never paired
        elif str(pair).startswith(ALT_PREFIX):
            _count(summary[arm(row)], row, tokens=True)
        else:
            pairs.setdefault((row.get(SOURCE_KEY), slot, str(pair)), []).append(row)
    for (_src, slot, _pid), members in pairs.items():
        if sorted(arm(r) for r in members) != sorted(ARMS):
            continue  # a half pair, or not one row per arm: never rated
        with_tokens = all(_tokens(r) is not None for r in members)
        for row in members:
            _count(out[slot][arm(row)], row, tokens=with_tokens)
    for slot, served in cheap_ab_served.served_summary(pairs).items():
        out[slot] |= {"served": served, "local_slot": served["local_slot"]}
    for summary in out.values():
        for a in ARMS:
            cell = summary[a]
            cell["rate"] = cell["pass"] / cell["n"] if cell["n"] else None
    return out


def _pair_rows(rows: list[dict], slot: str) -> dict[tuple[str, str], dict[str, dict]]:
    """Complete review-prep pairs for `slot`: {(source, pair id): {arm: row}}. A
    complete pair is exactly two rows — one `base`, one `prep` — each carrying a dict
    `findings`, a str `shape` and integer `tokens`; anything else is ignored."""
    out: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        if row.get("slot") != slot or not str(row.get("ab_pair") or "").startswith(PAIR_PREFIX):
            continue
        if row.get("oracle") not in RATED or not isinstance(row.get("findings"), dict):
            continue
        if not isinstance(row.get("shape"), str) or _tokens(row) is None:
            continue
        ab_arm = row.get("ab_arm")
        if ab_arm not in ("base", "prep"):
            continue
        members = out.setdefault((row.get(SOURCE_KEY), str(row["ab_pair"])), {})
        members[ab_arm] = row
    return {pid: members for pid, members in out.items() if set(members) == {"base", "prep"}}


def review_prep_verdict(rows: list[dict], slot: str) -> tuple[str, str]:
    """(`insufficient` | `hold` | `flip`, reason) for a review-prep slot (D12).
    `repro_scaffold` has no same-head pair: its evidence is the oracle accept rate.
    Otherwise the slot flips only with >= 2 complete `rp:` pairs, over >= 2 PRs and
    >= 2 shapes, whose findings are exactly equal (no noise floor) and whose prep
    token sum is strictly below the base sum."""
    if slot == "repro_scaffold":
        rated = [r for r in rows if r.get("slot") == slot and r.get("oracle") in RATED]
        passed = sum(1 for r in rated if r.get("oracle") == "pass")
        return "insufficient", f"repro_scaffold: no same-head pair; oracle accept rate {passed}/{len(rated)}"
    pairs = _pair_rows(rows, slot)
    k = len(pairs)
    prs = {pid.split(":")[1] for _src, pid in pairs if pid.count(":") >= 3}
    shapes = {members["base"]["shape"] for members in pairs.values()}
    if k < 2 or len(prs) < 2 or len(shapes) < 2:
        return "insufficient", f"pairs={k} prs={len(prs)} shapes={len(shapes)} (each needs >= 2)"
    parts = []
    for key in sorted(pairs, key=lambda kv: kv[1]):
        base, prep = pairs[key]["base"], pairs[key]["prep"]
        pid = key[1]
        b_n, p_n = base["findings"]["n"], prep["findings"]["n"]
        b_cls = {tuple(c) for c in base["findings"]["classes"]}
        p_cls = {tuple(c) for c in prep["findings"]["classes"]}
        if b_n != p_n or b_cls != p_cls:
            parts.append(f"{pid}: n {b_n}→{p_n}, +{sorted(p_cls - b_cls)} -{sorted(b_cls - p_cls)}")
    if parts:
        return "hold", "; ".join(parts)
    base_tokens = sum(_tokens(pairs[kv]["base"]) for kv in pairs)
    prep_tokens = sum(_tokens(pairs[kv]["prep"]) for kv in pairs)
    if prep_tokens >= base_tokens:
        return "hold", f"prep tokens {prep_tokens} >= base tokens {base_tokens}"
    return "flip", f"{k} pairs over {len(prs)} PRs and {len(shapes)} shapes: equal findings, prep tokens {prep_tokens} < base {base_tokens}"


def flip_verdict(summary: dict, slot: str, rows: list[dict] | None = None) -> tuple[str, str]:
    """(`exempt` | `insufficient` | `hold` | `flip`, reason) for one slot. The
    review-prep slots delegate to `review_prep_verdict`; `rows` carries their pairs."""
    if slot in cheap_tier.REVIEW_PREP_SLOTS:
        return review_prep_verdict(rows or [], slot)
    if slot == "task":
        return "exempt", "task: evidence is #184 plus task_opus_audit (no per-task pair exists)"
    cells = summary.get(slot) or _blank()
    name, src = ("local", cells["served"]) if cells.get("local_slot") else ("cheap", cells)
    cheap, opus = src[name], src["opus"]  # a local slot: its served cells, fallbacks dropped
    if cheap["n"] < 2 or opus["n"] < 2:
        return "insufficient", f"n {name}={cheap['n']} opus={opus['n']} (each needs >= 2)"
    rates = f"{name} {cheap['rate']:.2f} vs opus {opus['rate']:.2f}"
    if not opus["pass"]:
        return "hold", f"{rates}: the opus arm never passed, so there is no baseline"
    if cheap["rate"] < opus["rate"]:
        return "hold", f"{rates}: the {name} arm passes less often"
    return "flip", f"{rates}: the {name} arm passes at least as often"


def _measured_means(rows: list[dict]) -> dict:
    """Mean measured tokens per `(slot, arm)` and per `(None, arm)` over the ab rows."""
    sums: dict[tuple, list[int]] = {}
    for row in rows:
        tokens = _tokens(row)
        if row.get("ab_pair") is None or tokens is None:
            continue
        for key in ((row.get("slot"), arm(row)), (None, arm(row))):
            sums.setdefault(key, []).append(tokens)
    return {key: sum(v) // len(v) for key, v in sums.items()}


def _charge(row: dict, means: dict) -> int:
    tokens = _tokens(row)
    if tokens is not None:
        return tokens
    if row.get("rung") == "code":
        return 0
    if row.get("agent") is None:  # inline: no transcript, so the measured rows stand in
        for key in ((row.get("slot"), arm(row)), (None, arm(row))):
            if key in means:
                return means[key]
    return UNKNOWN_ROW_TOKENS


def budget(rows: list[dict], cap: int = BUDGET_CAP) -> dict:
    """`{spent, left, exhausted}` over the `ab_pair` rows; exactly `cap` is exhausted.
    An `ab_arm: base` row (the real Opus angle) is never charged — only the
    incremental spend draws on the cap."""
    means = _measured_means(rows)
    spent = sum(_charge(r, means) for r in rows
                if r.get("ab_pair") is not None and r.get("ab_arm") != "base")
    return {"spent": spent, "left": max(cap - spent, 0), "exhausted": spent >= cap}


def _prior(rows: list[dict], slot: str, taken: int | None) -> int:
    """The larger of the `alt:<slot>` rows and `taken` (the stored pick count)."""
    return max(sum(1 for r in rows if r.get("ab_pair") == f"{ALT_PREFIX}{slot}"), taken or 0)


def alt_arm(rows: list[dict], slot: str, taken: int | None = None) -> str:
    """The next alternation arm for `slot`: `cheap` on an even prior count, else `opus`."""
    return "cheap" if _prior(rows, slot, taken) % 2 == 0 else "opus"


def take_alt_arm(root, slot: str) -> str:
    """`alt_arm` over the rows and the stored pick count, then store the count plus one
    (under a lock, atomic replace; fail-open: an unwritable state leaves the rows to decide)."""
    rows = load_rows(root)[0]
    path = state_file.state_path(root)
    with state_file.locked(path):
        state = state_file.read_state(path)
        taken = state.get(slot) if type(state.get(slot)) is int else None  # not a bool
        if path is not None:
            state_file.write_state(path, {**state, slot: _prior(rows, slot, taken) + 1})
    return alt_arm(rows, slot, taken)


def _task_outcomes(root) -> dict[str, int]:
    """`role: "task"` rows by outcome (information only: the task slot is exempt)."""
    counts: dict[str, int] = {}
    for row in _parsed(root):
        if row and row.get("role") == "task" and not row.get("slot"):
            counts[str(row.get("outcome"))] = counts.get(str(row.get("outcome")), 0) + 1
    return counts


def _rate(cell: dict) -> str:
    return "-" if cell["rate"] is None else f"{cell['rate']:.2f}"


def _edit_cell(root, slot: str) -> str:
    m = prose_oracle.edit_metric(root, slot)
    return ("-" if m["mean"] is None else f"{m['mean']:.2f}") + f" (n={m['n']})"


def report(root) -> str:
    """The markdown evidence table: one row per slot, the info lines, then the served-arm,
    fallback and reach tables over the local requests. The edit ratio column is
    prose_oracle.edit_metric: reviewed drafts only."""
    rows, malformed = load_rows(root)
    summary = summarize(rows)
    all_rows = load_all_rows(root)[0]  # the budget line is the gate's own number
    lines = ["| slot | cheap n | cheap rate | cheap tokens | opus n | opus rate | opus tokens "
             "| unpaired on | edit ratio | verdict |", "|---|---|---|---|---|---|---|---|---|---|"]
    for slot in sorted(summary):
        s = summary[slot]
        verdict, reason = flip_verdict(summary, slot, rows)
        cells = [slot]
        for a in ARMS:
            cells += [str(s[a]["n"]), _rate(s[a]), str(s[a]["tokens"])]
        cells += [str(s["unpaired_on"]), _edit_cell(root, slot), f"{verdict} ({reason})"]
        lines.append("| " + " | ".join(cells) + " |")
    tasks = _task_outcomes(root)
    lines += ["", "task rows (information only): "
              + (", ".join(f"{k}={v}" for k, v in sorted(tasks.items())) or "none"),
              f"budget: {json.dumps(budget(all_rows), sort_keys=True)}",
              f"malformed lines: {malformed}"]
    served = {slot: s["served"] for slot, s in summary.items() if "served" in s}
    local = [r for r in rows if cheap_ab_served._eligible(r)]  # its one eligibility rule
    return "\n".join(lines + ["", cheap_ab_served.render_tables(served, local)])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="The cheap-tier A/B harness.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("report", "budget", "alt-arm"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", default=".", help="repository root (default: .)")
        if name == "alt-arm":
            sp.add_argument("--slot", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "report":
        print(report(args.root))
    elif args.cmd == "budget":
        print(json.dumps(budget(load_all_rows(args.root)[0]), sort_keys=True))
    else:
        print(take_alt_arm(args.root, args.slot))
    return 0


if __name__ == "__main__":
    sys.exit(main())

