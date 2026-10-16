"""test_dispatch_log_ab_fields.py — the ab-review fields on dispatch_log.

design: cheap-tier-review-prep (Task 7.1)

`findings`, `shape` and `ab_arm` are added to a record only when not None,
the same rule as `served` and the slot fields, so a legacy call (and a
legacy CLI row) stays byte-identical. The CLI takes `--findings` (a JSON
`{n: int, classes: list}` — anything else exits 2), `--shape` and
`--ab-arm {base,prep}`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import dispatch_log  # noqa: E402

CLI = _SHARED / "dispatch_log.py"
AB_KEYS = {"findings", "shape", "ab_arm"}
LEGACY_KW = dict(role="task", agent=None, reason="attempt 1", outcome="green",
                 started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:00:05Z",
                 tokens=123)
FINDINGS = {"n": 2, "classes": [["a.py", "P"], ["b.md", "L"]]}


def test_all_none_ab_kwargs_add_nothing():
    rec = dispatch_log.record("unused", findings=None, shape=None, ab_arm=None, **LEGACY_KW)
    assert AB_KEYS.isdisjoint(rec)
    assert rec == dispatch_log.record("unused", **LEGACY_KW)


def test_ab_none_kwargs_are_byte_identical_to_a_legacy_call():
    # both calls are timing-free, so the rows compare whole
    legacy = dispatch_log.record("unused", **LEGACY_KW)
    ab = dispatch_log.record("unused", findings=None, shape=None, ab_arm=None, **LEGACY_KW)
    assert json.dumps(ab, sort_keys=True) == json.dumps(legacy, sort_keys=True)


@pytest.mark.parametrize("key, value", [("findings", FINDINGS),
                                        ("findings", {"n": 0, "classes": []}),
                                        ("shape", "s"), ("ab_arm", "base"),
                                        ("ab_arm", "prep")])
def test_each_key_appears_only_when_set(key, value):
    rec = dispatch_log.record("unused", **LEGACY_KW, **{key: value})
    assert rec[key] == value
    assert AB_KEYS & set(rec) == {key}
    rest = {k: v for k, v in rec.items() if k != key}
    assert rest == dispatch_log.record("unused", **LEGACY_KW)


def test_all_ab_keys_together():
    rec = dispatch_log.record("unused", findings=FINDINGS, shape="s", ab_arm="prep",
                              **LEGACY_KW)
    assert (rec["findings"], rec["shape"], rec["ab_arm"]) == (FINDINGS, "s", "prep")


def _cli(tmp_path, *extra):
    base = ["record", "--design-dir", str(tmp_path), "--role", "r", "--agent",
            "tp-drafter", "--reason", "x", "--outcome", "y", "--root", str(tmp_path)]
    proc = subprocess.run([sys.executable, str(CLI), *base, *extra],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    printed = json.loads(proc.stdout)
    rows = (tmp_path / dispatch_log.NDJSON_NAME).read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[-1]) == printed
    return printed


def test_legacy_cli_row_has_none_of_the_new_keys(tmp_path):
    rec = _cli(tmp_path)
    assert AB_KEYS.isdisjoint(rec)


def test_cli_round_trips_the_three_fields(tmp_path):
    rec = _cli(tmp_path, "--findings", '{"n": 2, "classes": [["a.py", "P"]]}',
               "--shape", "s", "--ab-arm", "prep")
    assert (rec["findings"], rec["shape"], rec["ab_arm"]) == (
        {"n": 2, "classes": [["a.py", "P"]]}, "s", "prep")


@pytest.mark.parametrize("bad", ["not json", "[]", '{"n": "2", "classes": []}',
                                 '{"n": 1}', '{"n": true, "classes": []}'])
def test_cli_refuses_bad_findings(tmp_path, bad):
    with pytest.raises(SystemExit) as exc:
        dispatch_log.main(["record", "--design-dir", str(tmp_path), "--role", "r",
                           "--agent", "tp-drafter", "--reason", "x", "--outcome", "y",
                           "--root", str(tmp_path), "--findings", bad])
    assert exc.value.code == 2
    assert not (tmp_path / dispatch_log.NDJSON_NAME).exists()


def test_cli_refuses_an_unknown_ab_arm(tmp_path):
    with pytest.raises(SystemExit) as exc:
        dispatch_log.main(["record", "--design-dir", str(tmp_path), "--role", "r",
                           "--agent", "tp-drafter", "--reason", "x", "--outcome", "y",
                           "--root", str(tmp_path), "--ab-arm", "other"])
    assert exc.value.code == 2
    assert not (tmp_path / dispatch_log.NDJSON_NAME).exists()
