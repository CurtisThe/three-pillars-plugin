"""conftest.py — stub the Tier 3.5 phase re-run for the legacy wrapper suite only.

design: local-implement-and-review

`test_run_tier_3_5.py` predates the re-run and fakes `subprocess.run` globally, so a
real re-run inside it would be meaningless. The stub is patched on the **source
module** (`rerun_phase_tests.rerun_phase`): the wrapper calls it through the module
attribute, so each legacy test's `del sys.modules["run_tier_3_5"]` + re-import keeps it.
"""
from __future__ import annotations

import pytest

_LEGACY_MODULE = "test_run_tier_3_5"


@pytest.fixture(autouse=True)
def _stub_rerun_for_legacy_wrapper_suite(request, monkeypatch):
    if request.module.__name__.rsplit(".", 1)[-1] == _LEGACY_MODULE:
        import rerun_phase_tests

        monkeypatch.setattr(rerun_phase_tests, "rerun_phase", lambda *a, **k: {
            "status": "passed", "reason": "", "case": None, "nodes": [],
            "escaped_files": [], "unparsed_files": [], "output_tail": "", "rc": None,
            "control": None})
    yield
