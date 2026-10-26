"""finder_round — the local-finder round's angles and the Opus check.

design: local-role-routing (Task 6.2)

With `review_finder` on Opus, `round_angles` is `angles.load_angles` unchanged.
With `local`, every angle becomes an advisory local finder and the Opus check
angle is appended; it re-emits the kept findings and re-covers unparseable ones.

Stdlib only. `round_scratch` is never imported here at module level (it imports
this module lazily), so the manifest name is spelled out.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parents[1] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import angles  # noqa: E402
import role_engine  # noqa: E402
import strata_spawn  # noqa: E402

CHECK_NAME = "opus-check"
CHEAP_ENGINES = ("local", "sonnet")
MANIFEST = "angles.json"  # round_scratch.MANIFEST, the round manifest
_SELF = str(_HERE / "finder_round.py")


def check_angle(rulings_path) -> dict:
    """The Opus check: a Claude confirmer that audits every cheap finder's reply."""
    prompt = (
        "You are the Opus check for a round whose finders ran on a cheap model. "
        f"Read the context rulings at {rulings_path}. Read the round manifest "
        f"`../{MANIFEST}` (relative to TP_SCRATCH) for the finder list, then read "
        "`../<finder>/reply.md` for each finder (relative to TP_SCRATCH). "
        "Re-emit every finding worth keeping as your own, setting `blocking` and "
        "severity yourself, and add any defect the finders missed. Before you drop "
        "a finding on a ruling, verify each ruling citation against the file it "
        "cites; drop it only if the citation holds. Tag EVERY finding you emit "
        '`"escape": {"from": "<angle>#<i>" or null, "disposition": '
        '"kept"|"downgraded"|"opus-added"}` (from is null for one you added). '
        "Your `blocking` is final: a finding you mark `downgraded` never blocks, "
        "whatever its reproducer does. "
        f"Any angle the manifest `{MANIFEST}` marks `unparseable` has no usable "
        "reply: review, by yourself, the focus of that angle (its prompt in the "
        "manifest) and emit its findings. Deliver the findings with the usual "
        "`put` command. Then deliver the findings you dropped, ONLY with this one "
        "Bash command (a quoted heredoc):\n\n"
        f"python3 {_SELF} put-dispositions --round-dir <round dir> <<'TP_DISP_EOF'\n"
        '{"dropped": [{"from": "<angle>#<i>", "class": "P|X|T|C"}]}\n'
        "TP_DISP_EOF\n\n"
        '`class` is optional, and `served` ("sonnet-busy") is set only for a finder '
        "that ran on Sonnet because the slot was busy. Replies marked `capped` "
        "hit the hard cap and may be truncated: weigh them accordingly, "
        "re-cover what they likely missed, and treat what they did not check "
        "as unchecked. A finder named `<angle>-s<k>` is one segment of a large diff "
        "(its manifest entry has `segment`): it saw only its own files, so judge "
        "cross-segment concerns yourself, count a finding two segments both report at "
        "the same file:line once, and read the deduped view at `segments-merged.json` "
        "inside your own scratch dir when it exists. A segment entry that is `skipped` "
        "(`segment-budget`) or `unparseable` was seen by no Strata finder: review, by "
        "yourself, every file in its `segment.files` (and the manifest's "
        "`uncovered_files` in `segments-merged.json`). A segment entry whose "
        "`skipped` is `retried` was split in two: its halves are `<name>a` and "
        "`<name>b`, so judge those instead of the parent. A segment whose "
        "telemetry outcome is "
        "`partial` covers only the files its progress lines named, so its other "
        "files are still yours to review. A segment whose telemetry outcome is "
        "`capped` left nothing: re-cover it exactly like an `unparseable` one. "
        "Whenever the round left any file uncovered, your own prompt lists every "
        "one of those paths between the `uncovered-files` markers."
    )
    return {"name": CHECK_NAME, "prompt": prompt, "role": "confirmer", "model": "opus"}


def round_angles(config, *, root, scope=None, rulings_path=None, available=None) -> list:
    """The round's angle list; `load_angles` unchanged when the engine is Opus.

    `scope` (names) marks every other loaded angle `skipped: "out-of-scope"`
    (never the check); an unknown name raises `ValueError`. `available` is a
    test seam for the backend probe.
    """
    loaded = angles.load_angles(config)
    kw = {} if available is None else {"available": available}
    engine = role_engine.resolve("review_finder", config, root=root, **kw)["engine"]
    if scope is not None:
        names = [a["name"] for a in loaded]
        unknown = [s for s in scope if s not in names]
        if unknown:
            raise ValueError(f"unknown scope angle(s) {unknown}; angles: {names}")
    if engine in CHEAP_ENGINES:
        if not rulings_path:
            raise ValueError("a cheap finder round needs --rulings <path> "
                             "(the context rulings file)")
        suffix = (f"\n\nRead the context rulings at {rulings_path} before you start. "
                  f"{strata_spawn.SLOT_LOSS_SUFFIX}")
        out = [{**a, "prompt": a["prompt"] + suffix, "role": "finder",
                "model": engine, "advisory": True} for a in loaded]
    else:
        out = loaded
    if scope is not None:
        for a in out:
            if a["name"] not in scope:
                a["skipped"] = "out-of-scope"
    if engine in CHEAP_ENGINES:
        out.append(check_angle(rulings_path))
    return out


def parse_required(manifest) -> list:
    """Entries whose reply must be parsed: not skipped, not marked unparseable."""
    return [e for e in manifest.get("angles") or ()
            if not e.get("skipped") and not e.get("unparseable")]


def merge_entries(manifest) -> list:
    """The parse-required entries that are not advisory (the ones merged)."""
    return [e for e in parse_required(manifest) if not e.get("advisory")]


def aligned_replies(round_dir) -> list:
    """One `(entry, reply text)` per manifest angle, in manifest order."""
    import json

    import round_scratch  # lazy: round_scratch imports this module

    round_dir = Path(round_dir)
    manifest = json.loads((round_dir / round_scratch.MANIFEST).read_text(encoding="utf-8"))
    return list(zip(manifest.get("angles") or (), round_scratch.read_replies(round_dir)))


def _atomic_write(path, text) -> None:
    """Write via a temp file in the same dir, then `os.replace`."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _fail(msg) -> int:
    print(f"finder_round: {msg}", file=sys.stderr)
    return 2


def _cmd_mark_unparseable(args) -> int:
    path = Path(args.round_dir) / MANIFEST
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(f"cannot read manifest: {exc}")
    if args.angle == CHECK_NAME:
        return _fail("refusing to mark the Opus check unparseable")
    for entry in manifest.get("angles") or ():
        if entry.get("name") == args.angle:
            if entry.get("advisory") is not True:
                return _fail(f"angle {args.angle!r} is not advisory")
            entry["unparseable"] = "re-covered-by-opus-check"
            _atomic_write(path, json.dumps(manifest, indent=2) + "\n")
            return 0
    return _fail(f"unknown angle {args.angle!r}")


def _cmd_mark_busy(args) -> int:
    path = Path(args.round_dir) / MANIFEST
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(f"cannot read manifest: {exc}")
    if args.angle == CHECK_NAME:
        return _fail("refusing to mark the Opus check busy")
    for entry in manifest.get("angles") or ():
        if entry.get("name") == args.angle:
            if entry.get("skipped"):
                return _fail(f"angle {args.angle!r} is out of scope")
            entry["served"] = "sonnet-busy"
            _atomic_write(path, json.dumps(manifest, indent=2) + "\n")
            return 0
    return _fail(f"unknown angle {args.angle!r}")


def _cmd_put_dispositions(args) -> int:
    try:
        data = json.loads(sys.stdin.read())
    except ValueError as exc:
        return _fail(f"bad JSON on stdin: {exc}")
    dropped = data.get("dropped") if isinstance(data, dict) else None
    if not isinstance(dropped, list) or not all(isinstance(d, (dict, str)) for d in dropped):
        return _fail('stdin must be {"dropped": [<object or id string>, ...]}')
    out_dir = Path(args.round_dir) / CHECK_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(out_dir / "dispositions.json", json.dumps(data, indent=2) + "\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="finder_round")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mu = sub.add_parser("mark-unparseable")
    mu.add_argument("--round-dir", required=True)
    mu.add_argument("--angle", required=True)
    mu.set_defaults(func=_cmd_mark_unparseable)
    mb = sub.add_parser("mark-busy")
    mb.add_argument("--round-dir", required=True)
    mb.add_argument("--angle", required=True)
    mb.set_defaults(func=_cmd_mark_busy)
    pd = sub.add_parser("put-dispositions")
    pd.add_argument("--round-dir", required=True)
    pd.set_defaults(func=_cmd_put_dispositions)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
