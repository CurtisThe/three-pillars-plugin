"""Tests for local_timeouts.py: apply / decline / status (tmp_path only)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_timeouts as lt  # noqa: E402

STR = {k: str(v) for k, v in lt.TIMEOUTS.items()}


def _repo(tmp_path, wanted=True, settings=None):
    cfg = {"schema_version": 1}
    if wanted:
        cfg["local_implement"] = {"enabled": True}
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    if settings is not None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return tmp_path


def _settings(root):
    return json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _cfg(root):
    return json.loads((root / ".three-pillars" / "config.json").read_text(encoding="utf-8"))


def _record(root):
    return _cfg(root)["local_implement"]["client_timeouts"]


def test_apply_creates_and_records(tmp_path):
    root = _repo(tmp_path)
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    lt.apply(root, now=now)
    assert _settings(root) == {"env": STR}
    assert _record(root) == {"applied_at": "2026-01-02T03:04:05Z", "declined": False,
                             "values": lt.TIMEOUTS}
    assert lt.settled(_cfg(root))


def test_apply_only_missing_keys_keeps_others(tmp_path):
    first = next(iter(lt.TIMEOUTS))
    root = _repo(tmp_path, settings={"permissions": {"deny": ["x"]},
                                     "env": {"FOO": "1", first: "5"}})
    lt.apply(root)
    s = _settings(root)
    assert s["permissions"] == {"deny": ["x"]}
    assert s["env"]["FOO"] == "1" and s["env"][first] == "5"
    for k, v in STR.items():
        if k != first:
            assert s["env"][k] == v
    assert first not in _record(root)["values"]


def test_apply_idempotent(tmp_path):
    root = _repo(tmp_path)
    lt.apply(root)
    path = root / ".claude" / "settings.json"
    before = path.read_bytes()
    lt.apply(root)
    assert path.read_bytes() == before
    assert _record(root)["values"] == lt.TIMEOUTS


def test_decline_records_and_settles(tmp_path):
    root = _repo(tmp_path)
    lt.decline(root)
    assert _record(root) == {"applied_at": None, "declined": True, "values": {}}
    assert lt.settled(_cfg(root))
    assert lt.status(root)["state"] == "declined"
    assert not (root / ".claude" / "settings.json").exists()


def test_status_not_wanted(tmp_path):
    r = lt.status(_repo(tmp_path, wanted=False))
    assert r["state"] == "not-wanted" and r["line"] and r["drift"] == []


def test_status_unoffered(tmp_path):
    r = lt.status(_repo(tmp_path))
    assert r["state"] == "unoffered" and r["line"]


def test_status_applied_with_record(tmp_path):
    root = _repo(tmp_path)
    lt.apply(root)
    r = lt.status(root)
    assert r["state"] == "applied" and r["line"]


def test_status_applied_without_record(tmp_path):
    root = _repo(tmp_path, settings={"env": dict(STR)})
    r = lt.status(root)
    assert r["state"] == "applied" and r["line"]


def test_status_drifted_changed_and_removed(tmp_path):
    root = _repo(tmp_path)
    lt.apply(root)
    keys = list(lt.TIMEOUTS)
    s = _settings(root)
    s["env"][keys[0]] = "7"
    del s["env"][keys[1]]
    (root / ".claude" / "settings.json").write_text(json.dumps(s), encoding="utf-8")
    r = lt.status(root)
    assert r["state"] == "drifted" and r["line"]
    d = {x["key"]: x for x in r["drift"]}
    assert d[keys[0]] == {"key": keys[0], "recorded": lt.TIMEOUTS[keys[0]], "now": "7"}
    assert d[keys[1]]["now"] is None
    assert _settings(root) == s
