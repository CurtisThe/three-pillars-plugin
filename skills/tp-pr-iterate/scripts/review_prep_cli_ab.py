"""review_prep_cli_ab — the `shadow` and `ab-record` subcommands of review_prep_cli.

design: cheap-tier-review-prep (Task 7.5)

`shadow` builds the A/B shadow arm (moving the prep work dir into the round and
writing `R/prep/shadow/angles.json`); `ab-record` writes the paired `dispatch_log`
rows (Opus `base` + `prep` per angle) or nothing — an unparseable reply logs
`ab-unparseable: <angle>` and writes no row. Nothing here picks a model: both
rows are `--rung opus` (reviews always run on Opus). Stdlib only.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import angles  # noqa: E402,F401 — first: it puts skills/_shared on sys.path
import cheap_ab  # noqa: E402
import dispatch_log  # noqa: E402
import review_prep_ab  # noqa: E402


def _log(path, line) -> None:
    """Append one line to the log file; an unreadable/writable path is silent."""
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _reply_text(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def cmd_shadow(args, now=None) -> dict:
    """Build the shadow arm from the round and the drafter's specs; print its path."""
    specs = _read_json(args.specs)
    rows = cheap_ab.load_rows(args.root)[0]
    path = review_prep_ab.shadow(args.round_dir, args.work, specs, rows)
    return {"shadow": str(path)}


def _skip_reason(pair, real_entry, shadow_entry):
    """Why an angle records no rows (`ab-missing-ids` / `ab-unparseable`), or None."""
    if not isinstance(pair, dict) or not pair.get("real") or not pair.get("shadow"):
        return "ab-missing-ids"
    for entry in (real_entry, shadow_entry):
        if review_prep_ab.findings_of(_reply_text(entry["reply_path"])) is None:
            return "ab-unparseable"
    return None


def cmd_ab_record(args, now=None) -> dict:
    """Write the paired Opus `dispatch_log` rows (base + prep) or nothing."""
    R = Path(args.round_dir)
    ids = _read_json(R / "prep" / "shadow" / "ids.json")
    real_man = _read_json(R / "angles.json")
    real = {e["name"]: e for e in real_man["angles"]}
    shadow_entries = _read_json(R / "prep" / "shadow" / "angles.json")["angles"]
    skipped = []
    for e in shadow_entries:
        pair = ids.get(e["name"]) if isinstance(ids, dict) else None
        why = _skip_reason(pair, real[e["name"]], e)
        if why:
            _log(real_man["paths"]["log_path"], f"{why}: {e['name']}")
            skipped.append(e["name"])
    argvs = review_prep_ab.record_argv(R, ids, args.design_dir)
    with contextlib.redirect_stdout(io.StringIO()):  # dispatch_log prints; the CLI prints one line
        for argv in argvs:
            dispatch_log.main(argv)
    base_pairs = {a[a.index("--ab-pair") + 1] for a in argvs
                  if a[a.index("--ab-arm") + 1] == "base"}
    recorded = [e["name"] for e in shadow_entries
                if e["name"] not in skipped and e["pair_id"] in base_pairs]
    return {"recorded": recorded, "skipped": skipped}


def register(sub, make) -> None:
    """Add the two A/B subparsers using `review_prep_cli`'s own `make` (`_sub`)."""
    make(sub, "shadow", cmd_shadow, "round-dir", "work", "specs", root=".")
    make(sub, "ab-record", cmd_ab_record, "round-dir", "design-dir")
