#!/usr/bin/env python3
"""Gate for the design-learn retro step: exit 0 only when retro.enabled is true."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import repo_config_load  # noqa: E402


def enabled(repo) -> bool:
    retro = repo_config_load.load_repo_config(repo).config.get("retro", {})
    return isinstance(retro, dict) and retro.get("enabled") is True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    on = enabled(args.repo)
    print("retro: on" if on else "retro: off")
    return 0 if on else 1


if __name__ == "__main__":
    sys.exit(main())
