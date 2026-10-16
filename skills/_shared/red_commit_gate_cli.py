"""red_commit_gate_cli: the commit-msg hook front end for the red-commit gate.

Design red-commit-hook-refusal, Part 2. Owns the subprocess side of the gate —
reading the message file, listing staged paths, running the project's test
command — and defers every rule to the pure `red_commit_gate.decide`.

Usage:
    python3 red_commit_gate_cli.py commit-msg MSGFILE [--test-cmd CMD] [--test-glob G]...
    python3 red_commit_gate_cli.py snippet --test-cmd CMD
"""

import json
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from red_commit_gate import decide  # noqa: E402

CONFIG_PATH = ".three-pillars/config.json"


def _repo_top():
    res = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def _staged_paths():
    res = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True
    )
    if res.returncode != 0:
        return []
    return [line for line in res.stdout.splitlines() if line.strip()]


def _recorded_test_command(top):
    """`test.command` read raw from the repo config; None when absent/unreadable."""
    try:
        with open(os.path.join(top, CONFIG_PATH), encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError):
        return None
    test = config.get("test") if isinstance(config, dict) else None
    if isinstance(test, dict):
        command = test.get("command")
        if isinstance(command, str) and command.strip():
            return command
    return None


def _run_test_command(command, top):
    res = subprocess.run(
        command,  # nosec B602 — the repo's own recorded/flag-supplied test command
        shell=True,
        cwd=top,
        capture_output=True,
        text=True,
    )
    output = (res.stdout or "") + (res.stderr or "")
    return res.returncode, output


def _last_lines(text, count=40):
    lines = text.splitlines()
    return "\n".join(lines[-count:]) if lines else ""


def _commit_msg(argv):
    msgfile = None
    command = None
    globs = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--test-cmd":
            i += 1
            command = argv[i] if i < len(argv) else ""
        elif arg == "--test-glob":
            i += 1
            if i < len(argv):
                globs.append(argv[i])
        elif msgfile is None:
            msgfile = arg
        i += 1

    if msgfile is None:
        sys.stderr.write("red-commit-gate: missing message file\n")
        return 0
    try:
        with open(msgfile, encoding="utf-8") as handle:
            message = handle.read()
    except OSError:
        return 0

    top = _repo_top()
    if top is None:
        return 0
    if not command:
        command = _recorded_test_command(top)
    if not command:
        sys.stderr.write("red-commit-gate: no test command, skipped\n")
        return 0

    exit_code, output = _run_test_command(command, top)
    verdict = decide(
        message, _staged_paths(), exit_code, output, extra_globs=globs, top=top
    )
    if verdict["status"] == "pass":
        return 0
    sys.stderr.write("red-commit-gate: %s\n" % verdict["reason"])
    tail = _last_lines(output)
    if tail:
        sys.stderr.write(tail + "\n")
    return 1


def _snippet(argv):
    command = None
    i = 0
    while i < len(argv):
        if argv[i] == "--test-cmd":
            i += 1
            command = argv[i] if i < len(argv) else ""
        i += 1
    if not command:
        sys.stderr.write("red-commit-gate: snippet needs --test-cmd\n")
        return 2
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "red_commit_gate_cli.py")
    sys.stdout.write(
        'if [ -f "%s" ]; then python3 "%s" commit-msg "$1" --test-cmd %s '
        '|| exit 1; else echo "red-commit-gate: %s missing, tests NOT run at '
        'commit (re-run /tp-test-setup)" >&2; fi\n'
        % (path, path, shlex.quote(command), path)
    )
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write("red-commit-gate: usage: commit-msg MSGFILE | snippet --test-cmd CMD\n")
        return 2
    if argv[0] == "commit-msg":
        return _commit_msg(argv[1:])
    if argv[0] == "snippet":
        return _snippet(argv[1:])
    sys.stderr.write("red-commit-gate: unknown subcommand %r\n" % argv[0])
    return 2


if __name__ == "__main__":
    sys.exit(main())
