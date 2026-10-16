"""forge_config.py — the `forge` block in `.three-pillars/config.json` (Task 1.7).

design: forge-interface (Phase 1). One record, read once:

- `record_kind(repo, info, web_base=None)` writes the resolved forge
  (`forge.kind` / `forge.host` / `forge.recorded_at`, plus `forge.web_base` when a
  string is passed) exactly once — it returns False and touches nothing when
  `forge.kind` is already set. The write **merges** (`forge = data.setdefault(
  "forge", {})`, the `github_auth_check.mark_configured` pattern), so an
  operator-written `forge.web_base` — the ssh-alias / custom-port Gitea setup
  detection cannot classify — survives a later first-run. A `None` argument never
  writes `web_base: null` over a set value.
- `read_kind(config)` / `read_web_base(config)` read it back defensively: a
  non-dict block, a missing key or a wrong type is `None`, and `read_kind` returns
  only one of the three schema kinds.

Read-validates-mutates-writes, then an atomic tmp-file-and-rename in the config's
own directory (`os.replace` is a same-filesystem POSIX rename). Stdlib only.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# The three kinds the schema allows. Anything else is a stale/hand-typo value.
KINDS = ("github", "gitea", "other")

CONFIG_FILE = Path(".three-pillars") / "config.json"


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_config(repo: Path) -> dict:
    """The raw config, or a fresh shell. A corrupt file is NOT clobbered blindly:
    the caller writes the merged block, so an unreadable file reads as `{}` here
    and the per-key prune (`repo_config_load`) is the reader's safety net."""
    config_path = Path(repo) / CONFIG_FILE
    if not config_path.exists():
        return {"schema_version": 1}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {"schema_version": 1}
    return data if isinstance(data, dict) else {"schema_version": 1}


def _unparseable(config_path: Path) -> bool:
    """True when the config file exists but is not a JSON object. Such a file is
    never rewritten: repo-config.md says to leave it for the user to inspect."""
    if not config_path.exists():
        return False
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return True
    return not isinstance(data, dict)


def _atomic_write_config(config_path: Path, data: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=config_path.parent,
        prefix=".config.",
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(data, tmp, indent=2)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, config_path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def record_kind(repo, info, web_base: Optional[str] = None) -> bool:
    """Record `info.kind` / `info.host` under `forge` — once, merging.

    Returns True when the block was written, False when `forge.kind` was already
    set or the existing file does not parse (a no-op that rewrites no byte). `web_base` is written only when it is a
    string, so an absent argument leaves an operator's value alone.
    """
    config_path = Path(repo) / CONFIG_FILE
    if _unparseable(config_path):  # repo-config.md: leave a broken file for the user
        return False
    data = _read_config(Path(repo))
    forge_block = data.setdefault("forge", {})
    if not isinstance(forge_block, dict):  # junk block: replace it, it holds nothing
        forge_block = data["forge"] = {}
    if forge_block.get("kind") in KINDS:
        return False
    forge_block["kind"] = info.kind
    forge_block["host"] = info.host
    forge_block["recorded_at"] = _now_iso_utc()
    if isinstance(web_base, str):
        forge_block["web_base"] = web_base
    _atomic_write_config(config_path, data)
    return True


def _block(config) -> dict:
    block = config.get("forge") if isinstance(config, dict) else None
    return block if isinstance(block, dict) else {}


def read_kind(config) -> Optional[str]:
    """`forge.kind` when it is one of `KINDS`, else None."""
    kind = _block(config).get("kind")
    return kind if kind in KINDS else None


def read_web_base(config) -> Optional[str]:
    """`forge.web_base` when it is a non-empty string, else None."""
    base = _block(config).get("web_base")
    return base if isinstance(base, str) and base else None
