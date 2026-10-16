"""review_prep_cli.py — begin, batch, open, batch-end, settle, ci-logs, scaffold-targets, A/B.

Each prints one JSON line, exits 0 on every verdict path (usage error: 2). Stdlib only, C1-clean.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import angles  # noqa: E402 — puts skills/_shared on sys.path
import argv_runner  # noqa: E402
import cheap_oracle  # noqa: E402
import cheap_oracle_run  # noqa: E402
import live_tree_guard  # noqa: E402
import review_prep  # noqa: E402
import review_prep_budget  # noqa: E402
import review_prep_cli_ab  # noqa: E402 — the A/B subcommands: shadow, ab-record
import review_prep_io  # noqa: E402 — the drafter's in-tree I/O dir
import review_prep_scaffold  # noqa: E402


def _git(repo, *args) -> str:
    out = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                         text=True, timeout=60, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} rc={out.returncode}: {out.stderr.strip()}")
    return out.stdout


def _log(path, line) -> None:
    """Append one line to the log file; an unreadable/writable path is silent."""
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _load_config(path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # missing or unparseable: no config
        return None


def cmd_begin(args, now=None) -> dict:
    """Wipe and rebuild W at head (D10: no snapshot here); print {work, bucket}."""
    repo = str(Path(args.repo).resolve())
    if _git(repo, "rev-parse", "HEAD").strip() != args.head:
        _log(args.log, "[cheap-tier] prep skipped: HEAD != head")
        return {"skip": "head-mismatch"}
    W = review_prep.work_dir(args.root, args.pr_url)
    shutil.rmtree(W, ignore_errors=True)  # a stale next/ never survives begin
    W.mkdir(parents=True)
    review_prep_io.wipe(repo, args.pr_url)  # nor a stale staged drafter dir
    base = _git(repo, "rev-parse", "--verify", f"{args.base}^{{commit}}").strip()  # a SHA key
    diff_text = _git(repo, "diff", f"{base}...{args.head}")
    (W / "diff.patch").write_text(diff_text, encoding="utf-8")
    declared = angles.load_angles(_load_config(args.config))
    meta = {"pr_url": args.pr_url, "base": base, "head": args.head,
            "repo": repo, "log": str(Path(args.log).resolve()),
            "angles": [{"name": a.get("name"), "skipped": bool(a.get("skipped")),
                        "prompt": a.get("prompt")} for a in declared]}
    (W / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    review_prep_budget.begin(W, now=now)
    review_prep.cache_prune(W.parent.parent / review_prep.CACHE, args.head)
    return {"work": str(W), "bucket": review_prep.diff_bucket(diff_text)}


def cmd_batch(args, now=None) -> dict:
    """The only live-tree snapshot (D10): replace W/live, then snapshot into it."""
    W = Path(args.work)
    try:
        meta = json.loads((W / "meta.json").read_text(encoding="utf-8"))
        if not isinstance(meta, dict) or not meta.get("repo"):
            raise ValueError("meta.json has no repo")
    except (OSError, ValueError):
        return {"state": "skip"}
    live = W / "live"
    if live.exists():
        shutil.rmtree(live)
    return {"live": str(live_tree_guard.snapshot(meta["repo"], live))}


_UNIT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SLOTS = ("review_slice", "review_refs", "ci_log_triage", "repro_scaffold")
RUNNER = subprocess.run  # test seam for `gh`
_FAILED = ("FAILURE", "TIMED_OUT", "STARTUP_FAILURE")


def _load_work(work, head):
    """`(W, meta)` for a readable prep work dir at `head`; else one stderr line and None."""
    W = Path(work)
    try:
        meta = json.loads((W / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = None
    ok = isinstance(meta, dict) and bool(meta.get("repo"))
    if ok and str(meta.get("head")) != str(head):
        _log(meta.get("log") or str(W / "prep.log"),
             f"[cheap-tier] prep work dir is for another head: {meta.get('head')}")
        ok = False
    if not ok:
        print(f"[cheap-tier] prep work dir missing: {W}", file=sys.stderr)
    return (W, meta) if ok else None


def _cache_dir(W):
    """The per-PR `prep-cache` dir: `rounds/<pr>/prep-work/next` or `r<N>/prep/work`."""
    up = W.parent.parent if W.name == "next" else W.parent.parent.parent
    return up / review_prep.CACHE


def _scaffold_target(round_dir, unit):
    """The `repro_scaffold` target entry for `unit`, or None when it is not one."""
    try:
        targets = review_prep_scaffold.targets(Path(round_dir), log=False)  # no cap lines
    except (OSError, ValueError, KeyError):
        return None
    return next((t for t in targets if t.get("key") == unit), None)


def _cache_hit(W, meta, slot, unit):
    """The re-verified cached artifact for this unit, or None (no entry / fails)."""
    key = review_prep.cache_key(meta["base"], meta["head"], slot, unit)
    cache_dir = _cache_dir(W)
    if not (cache_dir / key).exists():
        return None
    if slot == "repro_scaffold":
        sc = review_prep_scaffold.scratch(meta["repo"], meta["head"])
        try:
            ctx = review_prep.ctx_for(slot, W, unit=unit, root=str(sc),
                                      scratch=W / slot / unit / "check")
            return review_prep.cache_get(cache_dir, key,
                                         lambda art: cheap_oracle.check(slot, art, ctx))
        finally:
            review_prep_scaffold.discard(sc)  # after the recheck, never before it
    ctx = review_prep.ctx_for(slot, W, unit=unit, root=meta["repo"])
    return review_prep.cache_get(cache_dir, key, lambda art: cheap_oracle.check(slot, art, ctx))


def cmd_open(args, now=None) -> dict:
    """Decide one unit: a re-verified hit, a spent-budget skip, or a spawn."""
    loaded = _load_work(args.work, args.head)
    if loaded is None:
        return {"state": "skip"}
    W, meta = loaded
    slot, unit = args.slot, str(args.unit)
    if not _UNIT_RE.match(unit) or unit in (".", ".."):
        return {"state": "refused", "reason": f"bad unit {unit!r}"}
    round_dir = Path(args.round_dir) if args.round_dir else None
    if slot == "repro_scaffold":
        if round_dir is None:
            return {"state": "refused", "reason": "repro_scaffold requires --round-dir"}
        target = _scaffold_target(round_dir, unit)
        if target is None:
            return {"state": "refused", "reason": f"{unit!r} not a target"}
    try:
        if slot == "repro_scaffold":
            finding = {k: target["finding"].get(k)
                       for k in ("file", "line_range", "summary", "class")}
            facts_payload = review_prep.facts(slot, W, unit, finding=finding)
        else:
            facts_payload = review_prep.facts(slot, W, unit)
    except ValueError as exc:
        return {"state": "refused", "reason": str(exc)}
    # Order: validate -> cache hit -> budget start -> spawn (a hit never starts a clock).
    artifact = _cache_hit(W, meta, slot, unit)
    if artifact is not None:
        adir = W / "accepted"
        adir.mkdir(parents=True, exist_ok=True)
        accepted = adir / f"{slot}--{unit}.json"
        accepted.write_text(json.dumps(artifact), encoding="utf-8")
        if slot == "repro_scaffold":
            review_prep_scaffold.write_note(round_dir, unit, artifact, meta["head"])
        return {"state": "hit"}
    if not review_prep_io.ignored(meta["repo"]):  # the drafter's I/O must stay in-tree
        _log(meta.get("log") or str(W / "prep.log"),
             f"[cheap-tier] prep skipped {slot}/{unit}: "
             f"{review_prep_io.SCRATCH_DIR}/ is not gitignored")
        return {"state": "skip"}
    if not review_prep_budget.start(W, f"{slot}--{unit}", now=now):
        n = int(review_prep_budget.spent(W, now))
        _log(meta.get("log") or str(W / "prep.log"),
             f"[cheap-tier] prep budget spent ({n}s of "
             f"{review_prep.PREP_BUDGET_SEC}s): skipped {slot}/{unit}")
        return {"state": "skip"}
    draft = review_prep.draft_path(W, slot, unit)
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.unlink(missing_ok=True)  # a stale draft never survives a spawn
    # The drafter is project-scoped: its paths live in-tree, never under W (settle copies back).
    facts_path, out_path = review_prep_io.stage(meta["repo"], meta["pr_url"], slot, unit,
                                                facts_payload)
    return {"state": "spawn", "facts_path": str(facts_path),
            "out_path": str(out_path), "loop_id": f"{slot}--{unit}"}


def cmd_batch_end(args, now=None) -> dict:
    """Stop the batch's budget clocks at one instant; no oracle runs here."""
    loaded = _load_work(args.work, args.head)
    if loaded is None:
        return {"state": "skip"}
    W, _meta = loaded
    loop_ids = [x for x in str(args.loop_ids).split(",") if x]
    return {"late": review_prep_budget.stop_batch(W, loop_ids, now=now)}


def _drop(why, late=False) -> dict:
    return {"action": "drop", "late": late, "verdict": {"ok": False, "oracle": "", "reason": why}}


def _check(W, meta, slot, unit, artifact) -> dict:
    """Write A.json / C.json beside the draft and run the slot's oracle."""
    d = review_prep.draft_path(W, slot, unit).parent
    try:
        sc = (review_prep_scaffold.scratch(meta["repo"], meta["head"])
              if slot == "repro_scaffold" else None)
    except (RuntimeError, OSError) as exc:
        return _drop(f"scratch-failed: {exc}")
    try:
        ctx = review_prep.ctx_for(slot, W, unit=unit, root=str(sc or meta["repo"]),
                                  scratch=d / "check")
        for name, obj in (("A.json", artifact), ("C.json", ctx)):
            (d / name).write_text(json.dumps(obj), encoding="utf-8")
        return cheap_oracle_run.run_check(slot, str(d / "A.json"), str(d / "C.json"))
    finally:
        if sc is not None:
            review_prep_scaffold.discard(sc)


def cmd_settle(args, now=None) -> dict:
    """Settle one unit: guard -> late -> readable draft -> oracle; never stops a clock."""
    loaded = _load_work(args.work, args.head)
    if loaded is None:
        return {"state": "skip"}
    W, meta = loaded
    slot, unit = args.slot, str(args.unit)
    if not _UNIT_RE.match(unit) or unit in (".", ".."):
        return {"state": "refused", "reason": f"bad unit {unit!r}"}
    review_prep_io.harvest(meta["repo"], meta["pr_url"], slot, unit,
                           review_prep.draft_path(W, slot, unit))  # staged draft -> W
    late = review_prep_budget.late(W, args.loop_id)  # read-only: one flag per batch
    guard = live_tree_guard.guard(meta["repo"], W / "live", exclude=(str(W),))
    if not guard["ok"] or late:  # the guard's reason first, then over-budget
        return _drop(guard["reason"] or "over-budget", late)
    try:
        artifact = json.loads(review_prep.draft_path(W, slot, unit).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        artifact = None
    if not isinstance(artifact, dict):
        return _drop("unreadable-draft")
    res = _check(W, meta, slot, unit, artifact)
    res.setdefault("late", False)
    if res["action"] != "accept":
        return res
    if slot == "repro_scaffold":  # first: a refused note leaves nothing accepted
        review_prep_scaffold.write_note(W.parent.parent, unit, artifact, meta["head"])
    (W / "accepted").mkdir(parents=True, exist_ok=True)
    (W / "accepted" / f"{slot}--{unit}.json").write_text(json.dumps(artifact), encoding="utf-8")
    key = review_prep.cache_key(meta["base"], meta["head"], slot, unit)
    review_prep.cache_put(_cache_dir(W), key, artifact)
    return res


def cmd_scaffold_targets(args, now=None) -> dict:
    ts = review_prep_scaffold.targets(Path(args.round_dir))
    return {"targets": [{"key": t["key"], "file": t["finding"].get("file"),
                         "summary": t["finding"].get("summary")} for t in ts]}


def _gh(cwd, *argv):
    return argv_runner.run_argv(["gh", *argv], cwd=cwd, timeout=60, runner=RUNNER)


def cmd_ci_logs(args, now=None) -> dict:
    """Last 200 kB of up to 3 failed Actions run logs into W/ci; fail-open."""
    cfg, W, logs, seen = _load_config(args.config), Path(args.work), [], set()
    try:
        if ((cfg or {}).get("ci") or {}).get("expects_github_checks") is False:
            return {"logs": logs}
        repo = json.loads((W / "meta.json").read_text(encoding="utf-8"))["repo"]
        view = _gh(repo, "pr", "view", args.pr_url, "--json", "statusCheckRollup")
        for c in json.loads(view.stdout)["statusCheckRollup"] if view.rc == 0 else []:
            m = re.search(r"/actions/runs/(\d+)", c.get("detailsUrl") or "")
            if c.get("conclusion") not in _FAILED or not m or m[1] in seen:
                continue
            seen.add(m[1])
            run = _gh(repo, "run", "view", m[1], "--log-failed")
            if run.rc != 0:
                continue
            base = re.sub(r"[^A-Za-z0-9_.-]+", "-", c.get("name") or "").strip("-.") or "check"
            slug, n = base, 1
            while any(x["check"] == slug for x in logs):
                n += 1
                slug = f"{base}-{n}"
            path = W / "ci" / f"{slug}.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            tail = run.stdout.encode("utf-8")[-200_000:]  # a cut char is dropped, not kept
            path.write_text(tail.decode("utf-8", "ignore"), encoding="utf-8")
            logs.append({"check": slug, "path": str(path)})
            if len(logs) == 3:
                break
    except Exception as exc:  # noqa: BLE001 — fail-open: any gh/parse failure keeps what we have
        print(f"[cheap-tier] ci-logs skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
    return {"logs": logs}


def _sub(sub, name, func, *required, **optional):
    """A subparser: `required` options are required; `optional` maps option -> default."""
    s = sub.add_parser(name)
    for opt in required:
        s.add_argument("--" + opt, required=True)
    for opt, default in optional.items():
        s.add_argument("--" + opt.replace("_", "-"), default=default)
    s.set_defaults(func=func)
    return s


def _parse_args(argv):
    p = argparse.ArgumentParser(prog="review_prep_cli.py", description="Cheap-tier review prep.")
    sub = p.add_subparsers(dest="command", required=True)
    _sub(sub, "begin", cmd_begin, "root", "pr-url", "base", "head", "log",
         repo=".", config=".three-pillars/config.json")
    _sub(sub, "batch", cmd_batch, "work")
    o = _sub(sub, "open", cmd_open, "work", "head", "unit", round_dir=None)
    t = _sub(sub, "settle", cmd_settle, "work", "head", "unit", "loop-id")
    for unit_parser in (o, t):
        unit_parser.add_argument("--slot", required=True, choices=_SLOTS)
    _sub(sub, "batch-end", cmd_batch_end, "work", "head", "loop-ids")
    _sub(sub, "ci-logs", cmd_ci_logs, "work", "pr-url", config=".three-pillars/config.json")
    _sub(sub, "scaffold-targets", cmd_scaffold_targets, "round-dir")
    review_prep_cli_ab.register(sub, _sub)
    return p.parse_args(argv)


def main(argv=None, now=None) -> int:
    args = _parse_args(argv)
    try:
        result = args.func(args, now=now)
    except Exception as exc:  # noqa: BLE001 — one JSON line and exit 0 on every verdict path
        result = {"skip": f"cli-error: {type(exc).__name__}: {exc}"}
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
