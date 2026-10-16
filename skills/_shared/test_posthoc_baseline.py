"""Tests for posthoc_baseline: the baseline manifest and the compare that never bends.

design: cheap-tier-local-routing 8.2 (detailed-design-posthoc.md, Baseline; plan Task 8.2).
Every test builds its telemetry under tmp_path, passes explicit `roots` to the pure functions
and an explicit `env` (XDG_STATE_HOME under tmp_path), and for the CLI monkeypatches
`cheap_ab_state.worktree_roots`, so no test reads the operator's state or worktrees.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cheap_ab_state  # noqa: E402
import posthoc_baseline  # noqa: E402
import posthoc_rows  # noqa: E402

UNTIL = "2026-10-01T22:00:00Z"
DOCS = Path("three-pillars-docs")
TELEMETRY = "dispatch-telemetry.ndjson"
ADDED = ("design", "measure", "ordinal", "time", "time_src")  # keys posthoc_rows.load adds


def _at(minute) -> str:
    return f"2026-10-01T10:{minute:02d}:00.000000Z"


def _row(task_id, **fields) -> dict:
    """A local-medium task row that was served locally; `fields` override (None = JSON null)."""
    row = {"task_id": task_id, "role": "task", "rung": "local-medium", "outcome": "PASS",
           "served_by": "local", "started_at": _at(0)}
    row.update(fields)
    return row


def _put(root, design, rows, sub="tp-designs") -> None:
    path = Path(root) / DOCS / sub / design
    path.mkdir(parents=True, exist_ok=True)
    with (path / TELEMETRY).open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _env(base) -> dict:
    return {"XDG_STATE_HOME": str(Path(base) / "state")}


def _load(base, roots) -> list[dict]:
    return posthoc_rows.load(roots[0], until=UNTIL, roots=roots, env=_env(base))


def _canonical_sha(row) -> str:
    raw = {k: v for k, v in row.items() if k not in ADDED}
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()


def _world(tmp_path):
    """One root, two designs: 3 in-scope rows in alpha, 4 in bravo, and out-of-scope noise."""
    root = tmp_path.resolve() / "main"
    _put(root, "alpha", [
        _row("1.1"),
        _row("1.2", served_by="fallback", started_at=_at(1)),
        _row("1.3", rung="sonnet", requested_rung="local-medium", served_by="fallback", started_at=_at(2)),
        _row("1.4", role="review", started_at=_at(3)),
        _row("1.5", rung="sonnet", started_at=_at(4)),
        _row("1.6", rung="local-low", requested_rung="sonnet", started_at=_at(5)),
        _row("1.7", started_at="2026-10-01T23:00:00.000000Z"),
    ])
    _put(root, "bravo", [
        _row("2.1", outcome="unavailable", served_by=None, started_at=_at(6)),
        _row("2.2", outcome="FAIL", served_by=None, started_at=None),
        _row("2.3", outcome="unavailable", served_by="local", started_at=_at(7)),
        _row("2.4", outcome="FAIL", served_by=None, started_at=_at(8)),
    ])
    return root, _load(tmp_path, [root])


def _classes(m) -> Counter:
    return Counter(r["class"] for r in m["rows"])


def _solo(tmp_path, fields) -> dict:
    """The manifest of a design holding one timed local row and one row built from `fields`."""
    root = tmp_path.resolve() / "main"
    _put(root, "solo", [_row("0.0"), _row("9.9", **fields)])
    return posthoc_baseline.manifest(_load(tmp_path, [root]), [root])


def test_manifest_shape_counts_and_sorting(tmp_path):
    root, rows = _world(tmp_path)
    m = posthoc_baseline.manifest(rows, [root])
    assert set(m) == {"roots", "per_design", "rows"}
    assert m["roots"] == [str(root)]
    assert m["per_design"] == {"alpha": 3, "bravo": 4}
    assert all(set(r) == {"design", "line_sha", "class"} for r in m["rows"])
    keys = [(r["design"], r["line_sha"], r["class"]) for r in m["rows"]]
    assert keys == sorted(keys)
    assert _classes(m) == {"local": 1, "fallback": 3, "never-spawned": 3}


def test_line_sha_is_the_canonical_row_digest(tmp_path):
    root, rows = _world(tmp_path)
    shas = [r["line_sha"] for r in posthoc_baseline.manifest(rows, [root])["rows"]]
    digests = {_canonical_sha(r) for r in rows if r["task_id"] in {"1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "2.4"}}
    assert len(digests) == len(shas) == len(set(shas)) == 7  # every distinct line, its own digest
    assert all(len(sha) >= 16 and any(d.startswith(sha) for d in digests) for sha in shas)


@pytest.mark.parametrize("fields, expected", [
    ({"served_by": "local"}, "local"),
    ({"served_by": "fallback"}, "fallback"),
    ({"served_by": "sonnet"}, "fallback"),
    ({"served_by": None, "outcome": "FAIL"}, "fallback"),
    ({"rung": "sonnet", "requested_rung": "local-medium", "served_by": "fallback"}, "fallback"),
    ({"outcome": "unavailable", "served_by": None}, "never-spawned"),
    ({"outcome": "unavailable", "served_by": "local"}, "never-spawned"),
    ({"outcome": "FAIL", "served_by": None, "started_at": None}, "never-spawned"),
])
def test_class_of_each_kind_of_row(tmp_path, fields, expected):
    assert _classes(_solo(tmp_path, fields)) == Counter(["local", expected])


@pytest.mark.parametrize("fields", [
    {"role": "review"}, {"role": None}, {"rung": "sonnet"}, {"rung": "opus"}, {"rung": None},
    {"requested_rung": "sonnet"}, {"requested_rung": "opus", "rung": "local-low"},
    {"started_at": "2026-10-01T23:00:00.000000Z"},
])
def test_rows_outside_the_baseline_scope_are_left_out(tmp_path, fields):
    assert _classes(_solo(tmp_path, fields)) == Counter(["local"])


def test_manifest_drops_transient_roots_but_keeps_their_rows(tmp_path):
    base = tmp_path.resolve()
    main = base / "main"
    nested = main / ".claude" / "worktrees" / "agent-1"
    attempt = base / "other" / ".claude" / "worktrees" / "tp-attempt-d-1.1-abc"
    _put(main, "alpha", [_row("1.1")])
    _put(nested, "nested", [_row("2.2", started_at=_at(2))])
    _put(attempt, "attempt", [_row("3.3", started_at=_at(3))])
    roots = [main, nested, attempt]
    m = posthoc_baseline.manifest(_load(base, roots), roots)
    assert m["roots"] == [str(main)]
    assert m["per_design"] == {"alpha": 1, "attempt": 1, "nested": 1}


def test_identical_lines_are_counted_by_multiplicity(tmp_path):
    root = tmp_path.resolve() / "main"
    _put(root, "alpha", [_row("1.1"), _row("1.1")])
    rows = _load(tmp_path, [root])
    m = posthoc_baseline.manifest(rows, [root])
    assert m["per_design"] == {"alpha": 2}
    assert m["rows"][0] == m["rows"][1]
    assert posthoc_baseline.check(rows, m) == 0
    assert posthoc_baseline.check(rows[:1], m) == 1


def test_check_passes_on_the_rows_it_was_cut_from(tmp_path, capsys):
    root, rows = _world(tmp_path)
    m = json.loads(json.dumps(posthoc_baseline.manifest(rows, [root])))
    assert posthoc_baseline.check(rows, m) == 0
    out = capsys.readouterr().out
    assert "recount: local=1 fallback=3 never-spawned=3 total=7" in out
    for problem in ("missing row", "reclassified", "drift", "missing root", "late rows"):
        assert problem not in out


def test_check_fails_on_a_missing_row_and_names_the_drift(tmp_path, capsys):
    root, rows = _world(tmp_path)
    m = posthoc_baseline.manifest(rows, [root])
    kept = [r for r in rows if r["task_id"] != "1.1"]
    assert posthoc_baseline.check(kept, m) == 1
    out = capsys.readouterr().out
    assert "missing row" in out
    assert "drift: alpha manifest=3 recount=2" in out
    assert "recount: local=0 fallback=3 never-spawned=3 total=6" in out


def test_check_fails_on_a_reclassified_row(tmp_path, capsys):
    root, rows = _world(tmp_path)
    m = posthoc_baseline.manifest(rows, [root])
    old = m["rows"][0]["class"]
    m["rows"][0]["class"] = "local" if old != "local" else "fallback"
    assert posthoc_baseline.check(rows, m) == 1
    out = capsys.readouterr().out
    assert "reclassified" in out
    assert "missing row" not in out
    assert "late rows" not in out


def test_an_in_range_extra_row_is_a_late_row_not_a_failure(tmp_path, capsys):
    root, rows = _world(tmp_path)
    m = posthoc_baseline.manifest(rows, [root])
    _put(root, "alpha", [_row("1.8", started_at=_at(9))])
    assert posthoc_baseline.check(_load(tmp_path, [root]), m) == 0
    out = capsys.readouterr().out
    assert "late rows: 1" in out
    assert "drift: alpha manifest=3 recount=4" in out
    assert "recount: local=2 fallback=3 never-spawned=3 total=8" in out
    assert "missing row" not in out


def test_an_edited_row_is_missing_and_its_replacement_late(tmp_path, capsys):
    root, rows = _world(tmp_path)
    m = posthoc_baseline.manifest(rows, [root])
    edited = [dict(r, served_by="fallback") if r["task_id"] == "1.1" else r for r in rows]
    assert posthoc_baseline.check(edited, m) == 1
    out = capsys.readouterr().out
    assert "missing row" in out
    assert "late rows: 1" in out


def test_a_recorded_root_that_no_longer_exists_is_printed(tmp_path, capsys):
    root, rows = _world(tmp_path)
    m = posthoc_baseline.manifest(rows, [root])
    gone = tmp_path.resolve() / "gone"
    m["roots"].append(str(gone))
    assert posthoc_baseline.check(rows, m) == 0
    out = capsys.readouterr().out
    assert f"missing root: {gone}" in out
    assert f"missing root: {root}" not in out


def test_a_hand_edited_per_design_count_is_a_drift_line(tmp_path, capsys):
    root, rows = _world(tmp_path)
    m = posthoc_baseline.manifest(rows, [root])
    m["per_design"]["alpha"] = 5
    assert posthoc_baseline.check(rows, m) == 0
    assert "drift: alpha manifest=5 recount=3" in capsys.readouterr().out


def _cli(tmp_path, monkeypatch):
    root, _ = _world(tmp_path)
    monkeypatch.setattr(cheap_ab_state, "worktree_roots", lambda r: [root])
    base = ["--root", str(root), "--until", UNTIL, "--utc-offset", "-06:00"]
    return root, base, _env(tmp_path)


def test_cli_manifest_writes_the_pure_manifest_deterministically(tmp_path, monkeypatch):
    root, base, env = _cli(tmp_path, monkeypatch)
    out_path = tmp_path / "manifest.json"
    assert posthoc_baseline.main(["manifest", *base, "--manifest", str(out_path)], env=env) == 0
    text = out_path.read_text(encoding="utf-8")
    assert json.loads(text) == posthoc_baseline.manifest(_load(tmp_path, [root]), [root])
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


def test_cli_manifest_without_a_path_prints_json(tmp_path, monkeypatch, capsys):
    root, base, env = _cli(tmp_path, monkeypatch)
    assert posthoc_baseline.main(["manifest", *base], env=env) == 0
    assert json.loads(capsys.readouterr().out)["per_design"] == {"alpha": 3, "bravo": 4}


def test_cli_check_round_trip_then_late_row_then_missing_row(tmp_path, monkeypatch, capsys):
    root, base, env = _cli(tmp_path, monkeypatch)
    path = str(tmp_path / "manifest.json")
    assert posthoc_baseline.main(["manifest", *base, "--manifest", path], env=env) == 0
    capsys.readouterr()
    assert posthoc_baseline.main(["check", *base, "--manifest", path], env=env) == 0
    assert "recount: local=1 fallback=3 never-spawned=3 total=7" in capsys.readouterr().out
    _put(root, "alpha", [_row("1.8", started_at=_at(9))])
    assert posthoc_baseline.main(["check", *base, "--manifest", path], env=env) == 0
    assert "late rows: 1" in capsys.readouterr().out
    telemetry = root / DOCS / "tp-designs" / "bravo" / TELEMETRY
    lines = telemetry.read_text(encoding="utf-8").splitlines()
    telemetry.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    assert posthoc_baseline.main(["check", *base, "--manifest", path], env=env) == 1
    assert "missing row" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [
    ["--nope"], ["--until", "not-a-time"], ["--utc-offset", "six"], ["--utc-offset", "-06"],
])
def test_cli_bad_flag_or_value_returns_2(tmp_path, monkeypatch, extra):
    _, base, env = _cli(tmp_path, monkeypatch)
    assert posthoc_baseline.main(["manifest", *base, *extra], env=env) == 2


def test_cli_bad_invocations_return_2(tmp_path, monkeypatch):
    _, base, env = _cli(tmp_path, monkeypatch)
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    unwritable = ["manifest", *base, "--manifest", str(blocker / "m.json")]
    for argv in ([], ["compare"], ["check", *base], unwritable):  # no command, unknown, no --manifest
        assert posthoc_baseline.main(argv, env=env) == 2, argv


@pytest.mark.parametrize("content", [None, "{not json", "[]", '{"roots": [], "per_design": {}}'])
def test_cli_check_with_an_unusable_manifest_returns_2(tmp_path, monkeypatch, content):
    _, base, env = _cli(tmp_path, monkeypatch)
    path = tmp_path / "manifest.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert posthoc_baseline.main(["check", *base, "--manifest", str(path)], env=env) == 2
