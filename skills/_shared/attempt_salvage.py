#!/usr/bin/env python3
"""attempt_salvage.py — record a failed attempt under the ladder dir before it is discarded.

design: ladder-diagnose-and-size-pins (plan Task 1.4)

``salvage --attempt <slug/task-nonce> --ladder-dir L --agent-id ID [--root .] [--config-dir D]
[--test-command CMD]`` writes ``L/<task>.salvage/<nonce>.json`` (``attempt_id``, ``task_id``,
``base_sha``, ``red_sha``, ``commits``, ``patch``, ``digest``) and, when the attempt has any
commit beyond ``base_sha`` or uncommitted/untracked work, ``<nonce>.patch`` beside it. The Red
is the first commit beyond ``base_sha`` whose subject starts ``Red:``. Writes only under ``L``.
Fail-open: any error prints one stderr line and ``{"salvaged": false, ...}``, exit 0. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attempt_scan  # noqa: E402
import salvage_digest  # noqa: E402
import task_verify_load  # noqa: E402

__all__ = ["salvage", "main"]


def _git(repo, *args, ok=(0,)) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=60)
    if proc.returncode not in ok:
        raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


def _commits(adir, base_sha: str) -> list[dict]:
    """Commits beyond ``base_sha``, newest first."""
    rows = _git(adir, "log", "--format=%H%x09%s", f"{base_sha}..HEAD").splitlines()
    return [{"sha": r.split("\t", 1)[0], "subject": r.split("\t", 1)[1] if "\t" in r else ""}
            for r in rows if r]


def _patch_text(adir, base_sha: str) -> str:
    text = _git(adir, "diff", "--binary", base_sha)
    for rel in _git(adir, "ls-files", "--others", "--exclude-standard").splitlines():
        if rel:
            text += _git(adir, "diff", "--no-index", "--binary", "--", os.devnull, rel, ok=(0, 1))
    return text


def _read_check(check_json) -> dict | None:
    """``{"reason", "test_output_tail"}`` of a FAIL check JSON; ``None`` when absent or bad."""
    if not check_json:
        return None
    try:
        data = json.loads(Path(check_json).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("verdict") != "FAIL":
        return None
    return {"reason": data.get("reason"), "test_output_tail": data.get("test_output_tail")}


def salvage(attempt_id: str, ladder_dir, agent_id: str, root=".", config_dir=None,
            test_command: str | None = None, check_json=None) -> dict:
    """Write the salvage record for ``attempt_id`` → ``{"salvaged": true, "record", "patch"}``."""
    try:
        attempt = task_verify_load.load_attempt(root, attempt_id)
        adir, base = Path(attempt["attempt_dir"]), attempt["base_sha"]
        if not adir.is_dir():
            raise RuntimeError(f"attempt dir missing: {adir}")
        commits = _commits(adir, base)
        red = next((c["sha"] for c in reversed(commits) if c["subject"].startswith("Red:")), None)
        task = str(attempt["task_id"])
        nonce = attempt_id.split("/", 1)[1]
        out_dir = Path(ladder_dir) / f"{task}.salvage"
        out_dir.mkdir(parents=True, exist_ok=True)
        patch_text = _patch_text(adir, base)
        patch = None
        if patch_text.strip():
            patch = str(out_dir / f"{nonce}.patch")
            Path(patch).write_text(patch_text, encoding="utf-8")
        transcript = attempt_scan.locate(agent_id, config_dir)
        record = {"attempt_id": attempt_id, "task_id": task, "base_sha": base, "red_sha": red,
                  "commits": commits, "patch": patch,
                  "digest": salvage_digest.digest(transcript, adir, base, test_command)}
        check = _read_check(check_json)
        if check is not None:
            record["check"] = check
        path = out_dir / f"{nonce}.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"salvaged": True, "record": str(path), "patch": patch}
    except Exception as exc:  # fail-open: salvage never blocks the discard
        detail = getattr(exc, "payload", None) or str(exc)
        print(f"attempt_salvage: {attempt_id}: {detail}", file=sys.stderr)
        return {"salvaged": False, "attempt_id": attempt_id, "error": str(detail)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Record an attempt before it is discarded.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("salvage")
    sp.add_argument("--attempt", required=True)
    sp.add_argument("--ladder-dir", required=True)
    sp.add_argument("--agent-id", required=True)
    sp.add_argument("--root", default=".")
    sp.add_argument("--config-dir")
    sp.add_argument("--test-command")
    sp.add_argument("--check-json")
    args = parser.parse_args(argv)
    result = salvage(args.attempt, args.ladder_dir, args.agent_id, args.root,
                     args.config_dir, args.test_command, args.check_json)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
