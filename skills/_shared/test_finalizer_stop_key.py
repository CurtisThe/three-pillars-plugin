"""Tests for finalizer.stop_key — the one-finalizer-per-stop identity.

design: fable-first-stops (Task 1.3). The key is
``source:signal:target[:sha256(detail)[:8]]``: per signal for ``pr-iterate``, per
slot for ``audit-gate``, per occurrence for ``halt`` (a normalised detail hash, so
a recurring halt with a new timestamp / PID / temp path keys the same).
Run with: python3 -m pytest skills/_shared/test_finalizer_stop_key.py
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer as fin  # noqa: E402

URL = "https://github.com/acme/widgets/pull/42"


def _pr(signal="round-cap", **extra):
    return {"source": "pr-iterate", "signal": signal, "target": URL, **extra}


def _halt(detail, signal="env-error", target="my-design"):
    return {"source": "halt", "signal": signal, "target": target, "detail": detail}


def test_constants():
    assert set(fin.SOURCES) == {"pr-iterate", "audit-gate", "halt", "question"}
    assert set(fin.AUDIT_SLOTS) == {"design", "plan", "implementation"}
    assert fin.STALE_SEC == 7200


def test_pr_iterate_key_is_source_signal_url():
    assert fin.stop_key(_pr("round-cap")) == f"pr-iterate:round-cap:{URL}"


def test_pr_iterate_key_ignores_head_and_detail():
    base = fin.stop_key(_pr())
    assert fin.stop_key(_pr(head="a" * 40)) == base
    assert fin.stop_key(_pr(head="b" * 40, detail={"measured": 9, "limit": 6})) == base


def test_pr_iterate_signals_get_distinct_keys():
    keys = {fin.stop_key(_pr(s)) for s in ("round-cap", "wall-clock", "growth-lines")}
    assert len(keys) == 3


def test_audit_gate_slots_get_distinct_keys():
    def key(slot):
        return fin.stop_key({"source": "audit-gate", "signal": slot, "target": "my-design"})

    assert key("design") == "audit-gate:design:my-design"
    assert len({key("design"), key("plan"), key("implementation")}) == 3


@pytest.mark.parametrize("signal", ["retry-exhausted", "review", "", None, "Design"])
def test_audit_gate_rejects_signal_outside_the_slots(signal):
    with pytest.raises(ValueError):
        fin.stop_key({"source": "audit-gate", "signal": signal, "target": "my-design"})


def test_halt_appends_eight_hex_of_detail_hash():
    key = fin.stop_key(_halt("boom: disk full"))
    head, _, digest = key.rpartition(":")
    assert head == "halt:env-error:my-design"
    assert re.fullmatch(r"[0-9a-f]{8}", digest)
    normalised = fin.normalize_detail("boom: disk full")
    assert digest == hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:8]


def test_two_different_halts_do_not_collide():
    assert fin.stop_key(_halt("missing dependency foo")) != fin.stop_key(
        _halt("missing dependency bar")
    )
    assert fin.stop_key(_halt("x", signal="env-error")) != fin.stop_key(
        _halt("x", signal="question")
    )


def test_identical_recurring_halt_gets_the_same_key():
    assert fin.stop_key(_halt("router unreachable")) == fin.stop_key(_halt("router unreachable"))


@pytest.mark.parametrize(
    "first, second",
    [
        ("failed at 2026-09-29T10:15:03Z: router unreachable",
         "failed at 2026-09-30T23:59:59Z: router unreachable"),
        ("worker pid 4242 crashed: no such file", "worker pid 977 crashed: no such file"),
        ("cannot write /var/scratch/tmpab12cd/out.log: EROFS",
         "cannot write /var/scratch/tmpzz99yy/out.log: EROFS"),
        ("checkout at 3fa9c1d2e4b5 is dirty", "checkout at 0ab1c2d3e4f5 is dirty"),
        ("open '/home/curtis/wt/a1/x.py' failed", "open '/home/other/wt/b2/x.py' failed"),
    ],
)
def test_recurrence_differing_only_in_volatile_tokens_keys_the_same(first, second):
    assert fin.stop_key(_halt(first)) == fin.stop_key(_halt(second))


def test_normalisation_strips_digits_hex_ids_and_absolute_paths():
    text = fin.normalize_detail("pid 4242 at /var/scratch/x9/y.log sha 3fa9c1d2e4b5 code 7")
    assert not re.search(r"\d", text)
    assert "/var" not in text and "3fa9c1d2e4b5" not in text
    assert "pid" in text and "sha" in text and "code" in text


def test_normalisation_keeps_urls_readable():
    assert "github.com" in fin.normalize_detail("see https://github.com/acme/widgets/pull/42")


def test_halt_detail_may_be_missing_or_structured():
    assert fin.stop_key({"source": "halt", "signal": "question", "target": "d"}) == fin.stop_key(
        {"source": "halt", "signal": "question", "target": "d", "detail": ""}
    )
    assert fin.stop_key(_halt({"a": 1, "b": 2})) == fin.stop_key(_halt({"b": 2, "a": 1}))


def test_unknown_source_raises():
    with pytest.raises(ValueError):
        fin.stop_key({"source": "cron", "signal": "x", "target": "t"})


@pytest.mark.parametrize(
    "stop",
    [
        {"source": "pr-iterate", "signal": "round-cap"},
        {"source": "pr-iterate", "signal": "round-cap", "target": ""},
        {"source": "pr-iterate", "signal": "", "target": URL},
        {"source": "pr-iterate", "signal": "a:b", "target": URL},
        {"source": "halt", "signal": "env-error", "target": None},
        "not-a-dict",
    ],
)
def test_malformed_stop_raises(stop):
    with pytest.raises(ValueError):
        fin.stop_key(stop)
