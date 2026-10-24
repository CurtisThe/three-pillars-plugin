"""Go-autonomous gate: skip the human question only for a seat-launched run.

design: followups-1023 item 1. `claude -p` children inherit TP_DESIGN_RUN=1,
so the marker alone must not skip the only human gate; a child session is
marked by the presence of TP_CHILD_SESSION and must still ask.
"""
from __future__ import annotations

import argparse
import os
import sys

MARKER_ENV = "TP_DESIGN_RUN"
CHILD_ENV = "TP_CHILD_SESSION"  # mirrors child_spawn_ops.CHILD_SESSION_ENV (no import)


def seat_launched(env) -> bool:
    return env.get(MARKER_ENV) == "1" and CHILD_ENV not in env


def main(argv=None, env=None) -> int:
    parser = argparse.ArgumentParser(
        description="Exit 0 (print skip) only for a seat-launched design run "
        "that is not a child session; else exit 1 (print ask).")
    parser.parse_args(argv)
    env = os.environ if env is None else env
    if seat_launched(env):
        print("skip")
        return 0
    print("ask")
    return 1


if __name__ == "__main__":
    sys.exit(main())
