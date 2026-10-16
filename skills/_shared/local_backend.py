"""local_backend.py — probe whether the `--local` backend (`tp-local`) is installed.

design: consumer-repo-parity (Phase 7)

`--local` runs the `local` tier's `tp-task-worker` spawn against the local-llm-skills
backend, reached by its `tp-local` binary on `PATH`. When that binary is absent the
backend is not installed and `--local` must refuse before Tier 2, with the operator
told to re-run without the flag (the `local` rung then falls back to a real model).

`available(which=...)` returns True only when `which("tp-local")` resolves to a path.
`main(argv)` is the CLI the SKILL prose runs — exits 0 when available, otherwise
prints the single refusal line and exits 1.
"""
from __future__ import annotations

import shutil
import sys

REFUSAL = ("local backend (local-llm-skills / tp-local) not installed — "
           "re-run without --local")


def available(*, which=shutil.which) -> bool:
    """True when the `tp-local` binary resolves on `PATH`, else False.

    `which` is injectable (defaults to `shutil.which`) so callers/tests can fake the
    probe without touching the environment.
    """
    return which("tp-local") is not None


def main(argv=None, *, which=shutil.which) -> int:
    """Exit 0 when the backend is available; else print the refusal and exit 1.

    `which` is injectable (defaults to `shutil.which`) so the refusal path is testable
    deterministically on a machine that happens to have `tp-local` on `PATH`.
    """
    if available(which=which):
        return 0
    print(REFUSAL)
    return 1


if __name__ == "__main__":
    sys.exit(main())
