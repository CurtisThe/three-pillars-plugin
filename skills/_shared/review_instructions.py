"""review_instructions.py — status and scaffold for .github review instructions.

design: consumer-repo-parity (Task 8.2)

`status(repo, config)` reports one of `present` / `declined` / `absent`:
`present` when `<repo>/.github/review-instructions.md` exists; else `declined`
when `config["review"]["instructions_declined"] is True`; else `absent`.
`scaffold(repo)` writes that file byte-equal to the shared template and
`.github/copilot-instructions.md` (the same body under a sync header), never
overwriting an existing file, returning the Paths it wrote. `main(argv)` is the
`status` / `scaffold` CLI the `/tp-pr-iterate` prose calls; `--repo` defaults to
`git rev-parse --show-toplevel`. Stdlib-only.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Ensure _shared/ is on sys.path so sibling modules are importable when run as
# a script (same bootstrap as ci_gate_run.py / deterministic_gate.py).
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from repo_config_load import load_repo_config  # noqa: E402

TEMPLATE = _SHARED_DIR / "templates" / "review-instructions.md"
REVIEW_FILE = Path(".github") / "review-instructions.md"
COPILOT_FILE = Path(".github") / "copilot-instructions.md"

SYNC_HEADER = (
    "<!-- Synced from `.github/review-instructions.md` — the canonical source. "
    "Edit it there and re-sync this file by hand; do not maintain this copy "
    "in isolation. -->\n\n"
)

USAGE = "usage: review_instructions.py status [--repo P] | scaffold [--repo P]"


def status(repo, config) -> str:
    """`present` / `declined` / `absent` for the review-instructions file.

    `config` is the plain dict (e.g. `load_repo_config(repo).config`).
    `present` wins: an existing file means the offer was accepted, whatever
    the sticky declined flag says.
    """
    if (Path(repo) / REVIEW_FILE).exists():
        return "present"
    review = config.get("review") if isinstance(config, dict) else None
    if isinstance(review, dict) and review.get("instructions_declined") is True:
        return "declined"
    return "absent"


def scaffold(repo) -> list:
    """Write the two `.github` instruction files; never overwrite.

    `.github/review-instructions.md` is byte-equal to the shared template;
    `.github/copilot-instructions.md` is the sync header followed by the same
    body. Existing files are left untouched and are not returned. Returns the
    list of Paths written (order: review-instructions, copilot-instructions).
    """
    root = Path(repo)
    (root / ".github").mkdir(parents=True, exist_ok=True)
    template = TEMPLATE.read_bytes()
    written = []
    review_path = root / REVIEW_FILE
    if not review_path.exists():
        review_path.write_bytes(template)
        written.append(review_path)
    copilot_path = root / COPILOT_FILE
    if not copilot_path.exists():
        copilot_path.write_bytes(SYNC_HEADER.encode("utf-8") + template)
        written.append(copilot_path)
    return written


def _repo_default() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        print(f"error: not inside a git repository (and no --repo given); {USAGE}",
              file=sys.stderr)
        sys.exit(2)
    return Path(proc.stdout.strip())


def _split_repo(args: list):
    """`(args_without_repo, repo_or_None)` for a trailing `--repo P`."""
    repo = None
    if len(args) >= 2 and args[-2] == "--repo":
        repo = args[-1]
        args = args[:-2]
    elif args[-1:] == ["--repo"]:
        raise ValueError("--repo requires a path")
    return args, repo


def main(argv) -> int:
    """`review_instructions.py status [--repo P] | scaffold [--repo P]`.

    `status` prints the status word; `scaffold` prints each written path one
    per line (nothing when nothing was written). Both exit 0; bad usage exits
    2 with a usage line on stderr. `--repo` defaults to
    `git rev-parse --show-toplevel`.
    """
    args = list(argv or [])
    try:
        rest, repo = _split_repo(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    if len(rest) != 1 or rest[0] not in ("status", "scaffold"):
        print(USAGE, file=sys.stderr)
        return 2
    command = rest[0]
    if repo is None:
        repo = _repo_default()
    repo = Path(repo)
    if command == "status":
        print(status(repo, load_repo_config(repo).config))
    else:
        for path in scaffold(repo):
            print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
