"""html_briefing/launch.py — present_briefing: display/headless launcher.

Public API:
  present_briefing(model, out_path, *, env, opener) -> PresentResult

Writes the HTML briefing to out_path, then tries to open it via xdg-open.
Falls back to terminal mode gracefully when:
  - DISPLAY is not set in env
  - xdg-open is not on PATH (shutil.which returns None)
  - the opener raises or returns a non-zero exit code

Injectables (for testability):
  env    — dict-like, defaults to os.environ
  opener — callable(path) -> int, defaults to subprocess.run xdg-open

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import briefing as _briefing


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PresentResult:
    """Result of present_briefing.

    Attributes:
        opened:   True when the browser was successfully launched.
        fallback: 'terminal' when opened is False; None when opened is True.
        path:     The path to the written HTML file.
    """
    opened: bool
    fallback: Optional[str]
    path: Path


# ---------------------------------------------------------------------------
# present_briefing
# ---------------------------------------------------------------------------

def present_briefing(
    model,
    out_path: Path,
    *,
    env: Optional[dict] = None,
    opener: Optional[Callable] = None,
) -> PresentResult:
    """Write the HTML briefing and try to open it in a browser.

    Always writes the HTML file to out_path first.
    Then:
      - If DISPLAY is set in env AND xdg-open is on PATH → calls opener(out_path).
        If the opener succeeds (returns 0) → PresentResult(opened=True, …).
        If the opener raises or returns non-zero → terminal fallback.
      - Otherwise → terminal fallback (prints the file path).
    Never raises — always returns a PresentResult.
    """
    if env is None:
        env = dict(os.environ)
    if opener is None:
        opener = _real_opener

    # Step 1: Always write the file
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        html = _briefing.build_briefing_html(model)
        out_path.write_text(html, encoding="utf-8")
    except Exception as exc:
        print(f"[html-briefing] Failed to write briefing: {exc}")
        return PresentResult(opened=False, fallback="terminal", path=out_path)

    # Step 2: Determine if we can open a browser
    has_display = bool(env.get("DISPLAY"))
    xdg_open = shutil.which("xdg-open")

    if not has_display or not xdg_open:
        print(f"[html-briefing] Briefing written to: {out_path}")
        print("[html-briefing] No display available — use terminal confirm.")
        return PresentResult(opened=False, fallback="terminal", path=out_path)

    # Step 3: Try to open
    try:
        exit_code = opener(out_path)
        if exit_code == 0:
            return PresentResult(opened=True, fallback=None, path=out_path)
        else:
            print(
                f"[html-briefing] xdg-open returned exit code {exit_code}; "
                "falling back to terminal confirm."
            )
            return PresentResult(opened=False, fallback="terminal", path=out_path)
    except Exception as exc:
        print(f"[html-briefing] Failed to open browser: {exc}; using terminal confirm.")
        return PresentResult(opened=False, fallback="terminal", path=out_path)


def _real_opener(path: Path) -> int:
    """Default opener: invoke xdg-open via subprocess."""
    result = subprocess.run(  # nosec B603 B607
        ["xdg-open", str(path)],
        capture_output=True,
    )
    return result.returncode
