"""review_prep_ab — the review-prep A/B shadow arm (one slot's prep, Opus kept).

design: cheap-tier-review-prep (Task 7.4)

The shadow arm re-runs each non-skipped angle on the Opus alias (the real
`R/angles.json` entry's `agent_ref` / `dispatch_model` — never a field of the
drafter `specs`) with exactly ONE active slot's accepted items, rendered to
`R/prep/shadow/<angle>.md`; the real manifest bytes are never touched.
`findings_of` keeps the CLEAN-vs-UNPARSEABLE distinction fail-closed;
`record_argv` emits the two `dispatch_log` argvs (base, then prep) whose rows
feed `cheap_ab`'s flip rule. Stdlib only; no model is ever called here.
"""
from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import angles  # noqa: E402 — first: it puts skills/_shared on sys.path
import cheap_ab  # noqa: E402
import cheap_tier  # noqa: E402
import review_merge  # noqa: E402
import review_prep  # noqa: E402
import round_scratch  # noqa: E402

PAIR_PREFIX = "rp:"  # == cheap_ab.PAIR_PREFIX: the review-prep pair id prefix
DRAFT_PREFIX = "rp-draft:"  # == cheap_ab.DRAFT_PREFIX (the drafter's rows)
SHADOW = "shadow"


def _active_slots(specs) -> list[str]:
    """The review-prep slots that ran: a dict spec with a truthy `rung`."""
    out = []
    for slot in cheap_tier.REVIEW_PREP_SLOTS:
        if slot == "repro_scaffold":
            continue
        spec = specs.get(slot) if isinstance(specs, dict) else None
        if isinstance(spec, dict) and spec.get("rung"):
            out.append(slot)
    return out


def _candidates_for(name, active, adir) -> list[str]:
    """The active slots with an accepted item for `name` (by slot file names)."""
    out = []
    for slot in active:
        if slot == "review_slice" and (adir / f"review_slice--{name}.json").is_file():
            out.append(slot)
        elif slot == "review_refs" and (adir / "review_refs--_.json").is_file():
            out.append(slot)
        elif slot == "ci_log_triage" and any(adir.glob("ci_log_triage--*.json")):
            out.append(slot)
    return out


def pick_slot(rows, angle, candidates):
    """The candidate slot with the fewest complete `rp:` pairs for `angle` (ties in
    `REVIEW_PREP_SLOTS` order); `repro_scaffold` is never picked; None when none."""
    best = None
    for slot in [s for s in cheap_tier.REVIEW_PREP_SLOTS
                 if s in candidates and s != "repro_scaffold"]:
        n = sum(1 for (_src, pid) in cheap_ab._pair_rows(rows, slot)
                if pid.endswith(":" + angle))
        if best is None or n < best[0]:
            best = (n, slot)
    return best[1] if best else None


def _slot_files(slot, name, adir) -> list[str]:
    """The accepted file names for one slot's items (ci: every check's draft)."""
    if slot == "review_slice":
        return [f"review_slice--{name}.json"]
    if slot == "review_refs":
        return ["review_refs--_.json"]
    return sorted(p.name for p in adir.glob("ci_log_triage--*.json"))


def _shadow_prompt(entry, shadow_dir, reply) -> "str | None":
    """The real prompt re-pointed at the shadow arm: its `put` line, TP_SCRATCH line
    and reply_path all name `shadow_dir`. `round_put` computes the target from
    `--round-dir`/`--slot` alone (never `reply_path`), so the put line is rebuilt
    on `shadow_dir`, whose own `angles.json` lists the slot. None when the prompt
    carries no single put line (fail-closed: no shadow for that angle)."""
    lines = entry["prompt"].split("\n")
    hits = [i for i, line in enumerate(lines) if " put --round-dir " in line]
    if len(hits) != 1:
        return None
    try:
        argv = shlex.split(lines[hits[0]].split(" <<", 1)[0])
        script = argv[argv.index("put") - 1]
    except (ValueError, IndexError):
        return None
    lines[hits[0]] = angles.put_command(script, str(shadow_dir), entry["name"])
    old_scratch = f"TP_SCRATCH: {Path(entry['reply_path']).parent}"
    lines = [f"TP_SCRATCH: {reply.parent}" if line == old_scratch else line
             for line in lines]
    return "\n".join(lines).replace(entry["reply_path"], str(reply))


def shadow(round_dir, work, specs, rows) -> Path:
    """Build `R/prep/shadow/` (one slot's prep per angle) and return its manifest.

    Moves `work` to `R/prep/work` when it is a distinct, existing dir; reads the
    real manifest only (its bytes are never changed); renders each entry from a
    throwaway stage dir holding just the picked slot's items.
    """
    r = Path(round_dir)
    if work is not None:
        dest = r / "prep" / "work"
        w = Path(work)
        if w.resolve() != dest.resolve() and w.exists():
            review_prep.move_work(work, r)
    manifest = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    active = _active_slots(specs)
    adir = r / "prep" / "work" / "accepted"
    shadow_dir = r / "prep" / SHADOW
    shadow_dir.mkdir(parents=True, exist_ok=True)
    pr = review_prep._pr_number(manifest["pr_url"])
    ordinal = manifest["ordinal"]
    entries = []
    for e in manifest.get("angles") or ():
        if e.get("skipped"):
            continue
        name = e["name"]
        slot = pick_slot(rows, name, _candidates_for(name, active, adir))
        if slot is None:
            continue
        reply = shadow_dir / name / "reply.md"
        prompt = _shadow_prompt(e, shadow_dir, reply)
        if prompt is None:
            continue
        stage = shadow_dir / "_stage" / name
        accepted = stage / "prep" / "work" / "accepted"
        accepted.mkdir(parents=True, exist_ok=True)
        for fname in _slot_files(slot, name, adir):
            shutil.copy2(str(adir / fname), str(accepted / fname))
        rendered = review_prep.render(stage, [{"name": name}])
        if name not in rendered:
            shutil.rmtree(str(stage), ignore_errors=True)
            continue
        text = rendered[name].read_text(encoding="utf-8")
        shutil.rmtree(str(stage), ignore_errors=True)
        md = shadow_dir / f"{name}.md"
        md.write_text(text, encoding="utf-8")
        reply.parent.mkdir(parents=True, exist_ok=True)
        entries.append({
            "name": name, "slot": slot,
            "pair_id": f"{PAIR_PREFIX}{pr}:{ordinal}:{name}",
            "agent": e["agent"], "agent_ref": e["agent_ref"],
            "dispatch_model": e["dispatch_model"],
            "reply_path": str(reply),
            "prompt": prompt + review_prep.prompt_suffix(md),
        })
    shutil.rmtree(str(shadow_dir / "_stage"), ignore_errors=True)  # no stage dir remains
    out = shadow_dir / "angles.json"
    out.write_text(json.dumps({"pr_url": manifest["pr_url"], "round": manifest["round"],
                               "ordinal": ordinal, "head": manifest["head"],
                               "angles": entries}, indent=2) + "\n",
                   encoding="utf-8")
    return out


def findings_of(reply_text):
    """`{"n", "classes"}` from a review reply; None when it does not parse (fail-closed)."""
    findings, ok = review_merge.parse_codereview_result(reply_text)
    if not ok:
        return None
    return {"n": len(findings),
            "classes": sorted([str(f.get("file")), str(f.get("class"))]
                              for f in findings)}


def _reply_text(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def record_argv(round_dir, ids, design_dir) -> list[list[str]]:
    """Two `dispatch_log` argvs (base, then prep) per recorded shadow angle.

    `ids` is `{angle: {"real": agent_id, "shadow": agent_id}}` (the content of
    `R/prep/shadow/ids.json`). An angle is skipped when it lacks both ids or
    either reply is unparseable; both rows carry `--rung opus` and the pair's
    shape, and the argvs are accepted as-is by `dispatch_log.main`.
    """
    r = Path(round_dir)
    shadow_man = json.loads((r / "prep" / SHADOW / "angles.json").read_text(encoding="utf-8"))
    real_man = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    real = {e["name"]: e for e in real_man.get("angles") or ()}
    diff = r / "prep" / "work" / "diff.patch"
    diff_text = diff.read_text(encoding="utf-8") if diff.is_file() else ""
    shp = review_prep.shape(real_man, diff_text)
    argvs = []
    for e in shadow_man.get("angles") or ():
        name = e["name"]
        pair = ids.get(name) if isinstance(ids, dict) else None
        if not isinstance(pair, dict) or not pair.get("real") or not pair.get("shadow"):
            continue
        base_f = findings_of(_reply_text(real[name]["reply_path"]))
        prep_f = findings_of(_reply_text(e["reply_path"]))
        if base_f is None or prep_f is None:
            continue
        for arm, agent_id, findings in (
                ("base", pair["real"], base_f), ("prep", pair["shadow"], prep_f)):
            argvs.append([
                "record", "--design-dir", str(design_dir),
                "--role", "review_prep_ab",
                "--agent", e["agent"],
                "--reason", f"review-prep ab {arm}: {name}",
                "--outcome", "done",
                "--slot", e["slot"],
                "--oracle", "pass",
                "--rung", "opus",
                "--ab-pair", e["pair_id"],
                "--ab-arm", arm,
                "--agent-id", agent_id,
                "--findings", json.dumps(findings, sort_keys=True),
                "--shape", shp,
            ])
    return argvs
