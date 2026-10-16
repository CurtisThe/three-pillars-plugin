"""The design-run (orchestrator) model defaults to `sonnet[1m]`; `opus[1m]` is an override."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model_policy as mp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_is_sonnet_1m():
    assert mp.model_for("design_run", None) == "sonnet[1m]", (
        "an unconfigured design run must start on the sonnet default")


def test_repo_config_pins_sonnet_1m():
    cfg = json.loads((REPO_ROOT / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
    assert cfg["models"]["design_run"] == "sonnet[1m]", (
        "this repo's config.json no longer pins the sonnet design run")


def test_sonnet_1m_validates():
    out, warns = mp.validate_models({"design_run": "sonnet[1m]"})
    assert out["design_run"] == "sonnet[1m]" and not warns


def test_opus_1m_override_still_validates():
    out, warns = mp.validate_models({"design_run": "opus[1m]"})
    assert out.get("design_run") == "opus[1m]" and not warns, (
        "an opus override must still validate for a design run")
