"""test_role_engine_effort.py — a `local` engine row states the Strata effort.

design: strata-effort-every-call (Task 2.2). Every call routed to the local
Strata model states an effort on purpose — `medium` or `xhigh`, never a bare
`high`. The engine row a dispatch is written from is that statement, so a
`local` row for every engine role states the effort `strata_effort` maps for
that role, and a `sonnet` row keeps `high` (the Sonnet row label is unchanged).

`row_effort(role, engine)` is the entry point: the local effort per role from
`strata_effort`, `SONNET_ROW_EFFORT` otherwise. `resolve` writes its `effort`
through it, and so does the explainer's own row builder.

Hermetic: the backend probe is injected, roots are tmp dirs, the run is pinned
with `local=`. Assertions are on the returned row's fields
(skills/_shared/test-fragility.md).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "explainer"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_engine  # noqa: E402 — the explainer's row builder
import role_engine as re_  # noqa: E402

YES = lambda: True  # the backend is installed (injected probe, never mocked)


def _local_repo(tmp_path, model="haiku"):
    """A tmp repo whose `local_implement.model` is `model`; returns the root."""
    conf = tmp_path / ".three-pillars"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "config.json").write_text(
        json.dumps({"local_implement": {"enabled": True, "model": model}}),
        encoding="utf-8",
    )
    return tmp_path


# --- a local row states the inventory effort, per engine role ----------------

def test_every_engine_role_local_row_states_medium(tmp_path):
    root = _local_repo(tmp_path)
    for role in ("council_member", "review_finder", "context_scout", "explainer"):
        got = re_.resolve(role, {}, root=root, available=YES, local=True)
        assert got["engine"] == "local", role
        assert got["effort"] == "medium", role


# --- a sonnet row keeps the Sonnet label ------------------------------------

def test_sonnet_row_keeps_high():
    got = re_.resolve("council_member", {}, available=YES, local=False)
    assert (got["engine"], got["effort"]) == ("sonnet", "high")


# --- row_effort is the entry point both row builders use --------------------

def test_row_effort_is_medium_for_local_and_high_otherwise():
    assert re_.row_effort("explainer", "local") == "medium"
    assert re_.row_effort("explainer", "sonnet") == "high"


def test_explainer_local_row_states_medium():
    assert explain_engine._row("local", "haiku", None)["effort"] == "medium"
