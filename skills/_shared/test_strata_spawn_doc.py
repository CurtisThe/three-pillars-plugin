"""test_strata_spawn_doc.py — the Strata spawn discipline doc and its slot-loss suffix.

design: local-role-routing (Task 2.5). The one slot-loss suffix lives in code
(`strata_spawn.SLOT_LOSS_SUFFIX`) and `strata-spawn.md` quotes it verbatim; the
doc also names the CLI verbs, the dispatch-row flags and the halt rules. Prose
assertions are set membership, never order (test-fragility.md).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import dispatch_log  # noqa: E402
import strata_spawn  # noqa: E402

DOC = _SHARED / "strata-spawn.md"


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_suffix_content():
    s = strata_spawn.SLOT_LOSS_SUFFIX
    for needle in ("120 s", "timeout 100", "targeted tests", "never kill", "by name or pattern"):
        assert needle in s


def test_doc_quotes_suffix_verbatim():
    assert strata_spawn.SLOT_LOSS_SUFFIX in _doc()


@pytest.mark.parametrize("needle", [
    "strata_spawn.py wait", "mark", "verify", "release", "decide",
    "in Bash with timeout 300000",
    "strata_spawn.py wait --started-at",
    "decisions.md",
    "exit 4", "exit 5", "strata-wait-exhausted", "finalizer",
    "--rung local-medium --requested-rung local-medium",
    "--rung sonnet-xhigh --reason slot-lost",
    "strata_spawn.busy", "--busy", "busy-fallback", "fallback-busy",
    "accepted Sonnet service",
    "advisory", "exit 3",
    "pkill", "killall",
])
def test_doc_names(needle):
    assert " ".join(needle.split()) in " ".join(_doc().split())


def test_doc_never_pins_sonnet_model():
    assert 'model="sonnet"' not in _doc()


def test_doc_lines_wrapped():
    assert max(len(line) for line in _doc().splitlines()) <= 110


def _row(tmp_path, fallback_requests):
    rc = dispatch_log.main([
        "record", "--design-dir", str(tmp_path), "--role", "council_member",
        "--agent", "council-feynman-medium", "--reason", "r", "--outcome", "ok",
        "--rung", "local-medium", "--requested-rung", "local-medium",
        "--local-requests", "3", "--fallback-requests", str(fallback_requests)])
    assert rc == 0
    lines = (tmp_path / "dispatch-telemetry.ndjson").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def test_row_records_local_engine(tmp_path):
    row = _row(tmp_path, 0)
    assert row["served_by"] == "local"
    assert row["served_rung"] == "local"


def test_row_records_sonnet_mirror(tmp_path):
    assert _row(tmp_path, 1)["served_rung"] == "sonnet-mirror"
