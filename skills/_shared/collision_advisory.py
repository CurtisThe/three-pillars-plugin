"""collision_advisory.py — helper for framework-check.sh collision advisory.

Called by framework-check.sh with the repo root as the first argument.
Prints "COLLISION self_login=<login>" if single_account_collision_live()
returns True; prints nothing otherwise. Any error is silently swallowed
(fail-open — the advisory must never block a commit).

Exit code is always 0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    repo_root = argv[0] if argv else "."
    shared = Path(repo_root) / "skills" / "_shared"
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    try:
        from single_account_detect import single_account_collision_live  # noqa: PLC0415

        if single_account_collision_live(config={}):
            r = subprocess.run(
                ["gh", "api", "user", "--jq", ".login"],
                capture_output=True, text=True, check=False,
            )
            login = r.stdout.strip() if r.returncode == 0 else "unknown"
            print(f"COLLISION self_login={login}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
