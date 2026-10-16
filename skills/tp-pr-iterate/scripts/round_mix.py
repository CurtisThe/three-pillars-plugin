"""round_mix — what the last two rounds were stuck on, riding the round-cap stop.

design: review-convergence (Task 2.2, detailed-design-pr-loop §B)

Review bar: a round-cap stop tells the finalizer only that the loop ran out of
rounds, so it sends another patch at the same area that needs a rewrite. Two
consecutive rounds whose blockers carry the same structural signal — a regression
majority, or one fragile class concentrated in one area — is the evidence that
patching is the wrong move. `round_signal` reads one round's `tail/findings.json`
and names that signal; `mix` reports it only when the last two rounds both carry
one, with the area to rewrite; `attach` puts `mix` on a `pr-iterate` / `round-cap`
stop and nowhere else. Inputs are never mutated. Stdlib only; computes, never
shells out (C1).
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import severity  # noqa: E402
from finding_fields import FRAGILE_CLASSES  # noqa: E402

MIN_BLOCKERS = 2  # a round with fewer blockers carries no structural signal
MIX_SIGNAL = "structural-rewrite"
FINDINGS = "tail/findings.json"  # the reproducer's output (round_scratch tail)
_STOP_SOURCE = "pr-iterate"
_STOP_SIGNAL = "round-cap"
_ROUND_RE = re.compile(r"^r(\d+)(?:\.(\d+))?$")  # r<N> and its re-runs r<N>.<k>


def _majority(values, total: int):
    """The value held by a strict majority of `total`, or None when none does."""
    if not values:
        return None
    top, count = Counter(values).most_common(1)[0]
    return top if count * 2 > total else None


def _blockers(findings) -> list:
    """The findings that block, per the one severity authority."""
    return [f for f in findings if isinstance(f, dict) and severity.is_blocking(f)]


def area_of(paths) -> str | None:
    """The strict-majority file in `paths`, else their strict-majority parent dir.

    Empty and non-string paths are ignored; a bare name's parent dir is ".".
    None when neither a file nor a parent dir holds a strict majority — there is
    then no single area to rewrite.
    """
    clean = [p for p in paths if isinstance(p, str) and p]
    if not clean:
        return None
    top = _majority(clean, len(clean))
    if top is not None:
        return top
    return _majority([posixpath.dirname(p) or "." for p in clean], len(clean))


def round_signal(findings) -> dict | None:
    """One round's structural signal, or None when the round carries none.

    A regression majority outranks a class majority; otherwise one
    `FRAGILE_CLASSES` value shared by a majority of the blockers, in an area
    `area_of` can name.
    """
    blockers = _blockers(findings)
    if len(blockers) < MIN_BLOCKERS:
        return None
    regressions = [f for f in blockers if f.get("origin") == "regression"]
    if len(regressions) * 2 > len(blockers):
        return {"kind": "regression"}
    for cls in FRAGILE_CLASSES:
        same = [f.get("file") for f in blockers if f.get("fragility_class") == cls]
        if len(same) * 2 > len(blockers):
            area = area_of(same)
            if area is not None:
                return {"kind": f"class:{cls}@{area}"}
    return None


def _read_findings(round_dir: Path):
    """The round's findings list, or None when it is absent or malformed."""
    try:
        data = json.loads((round_dir / FINDINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _round_entries(rounds_dir) -> list:
    """(order key, dir name, findings) per round number, in round order.

    A re-run dir `r<N>.<k>` with a readable list supersedes `r<N>` and any lower
    re-run; a dir whose list is missing or malformed is skipped.
    """
    root = Path(rounds_dir)
    try:
        names = sorted(p.name for p in root.iterdir())
    except OSError:
        return []
    picked: dict = {}
    for name in names:
        match = _ROUND_RE.match(name)
        if not match:
            continue
        findings = _read_findings(root / name)
        if findings is None:
            continue
        key = (int(match.group(1)), int(match.group(2) or 0))
        if key[0] not in picked or key >= picked[key[0]][0]:
            picked[key[0]] = (key, name, findings)
    return [picked[num] for num in sorted(picked)]


def mix(rounds_dir) -> dict | None:
    """The structural-rewrite mix when the last two rounds both carry a signal.

    `reason` names each of the two rounds and its signal kind; `area` is the
    majority area over both rounds' blockers ("." when none holds).
    """
    entries = _round_entries(rounds_dir)
    if len(entries) < 2:
        return None
    last = entries[-2:]
    signals = [(name, round_signal(findings)) for _key, name, findings in last]
    if any(sig is None for _name, sig in signals):
        return None
    files = [f.get("file") for _key, _name, findings in last for f in _blockers(findings)]
    return {"signal": MIX_SIGNAL,
            "area": area_of(files) or ".",
            "reason": "; ".join(f"{name}: {sig['kind']}" for name, sig in signals)}


def attach(stop, rounds_dir) -> dict:
    """A copy of `stop`, given `mix` only when it is a mixing round-cap stop.

    Only a `pr-iterate` stop whose signal is `round-cap` is ever extended; the
    input stop is never mutated.
    """
    out = dict(stop)
    if out.get("source") != _STOP_SOURCE or out.get("signal") != _STOP_SIGNAL:
        return out
    found = mix(rounds_dir)
    if found is not None:
        out["mix"] = found
    return out


def main(argv=None) -> int:
    """`attach --stop-file F --rounds-dir D` — print the (possibly extended) stop."""
    parser = argparse.ArgumentParser(
        prog="round_mix.py", description="Attach the round mix to a round-cap stop.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    attach_cmd = sub.add_parser("attach", help="print the stop, extended with mix when due")
    attach_cmd.add_argument("--stop-file", required=True)
    attach_cmd.add_argument("--rounds-dir", required=True)
    args = parser.parse_args(argv)
    try:
        stop = json.loads(Path(args.stop_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"round_mix: unreadable stop file {args.stop_file}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(stop, dict):
        print(f"round_mix: stop file {args.stop_file} holds no JSON object", file=sys.stderr)
        return 2
    print(json.dumps(attach(stop, Path(args.rounds_dir))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
