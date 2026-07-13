"""Tests for inflight_registry.py — pure-logic units + temp-repo git integration.

Run with: python -m pytest skills/_shared/test_inflight_registry.py -q
"""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import inflight_registry
from inflight_registry import (
    Registry,
    RegistryEntry,
    STALE_DAYS,
    classify,
    collision_verdict,
    format_table,
    to_json,
    list_tp_branches,
    read_lock_blob,
    build_registry,
    main,
)


# --------------------------------------------------------------------------- #
# Temp-repo helpers (bare "origin" + clone), matching test_migrate style.
# --------------------------------------------------------------------------- #


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def _init_clone(repo):
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    _run(["git", "config", "commit.gpgsign", "false"], repo)


def _make_origin_and_clone(tmp_path):
    """Create a bare origin + a clone wired to it. Returns (origin, clone)."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _run(["git", "init", "-q", "--bare", "-b", "main"], origin)

    clone = tmp_path / "clone"
    clone.mkdir()
    _init_clone(clone)
    _run(["git", "remote", "add", "origin", str(origin)], clone)
    # Seed an initial commit on main so HEAD exists.
    (clone / "README.md").write_text("seed\n")
    _run(["git", "add", "README.md"], clone)
    _run(["git", "commit", "-q", "-m", "seed"], clone)
    _run(["git", "push", "-q", "-u", "origin", "main"], clone)
    return origin, clone


def _push_branch(clone, branch, design_name, lock_obj=None, write_lock=True):
    """Create `branch` carrying a lock.json (under design_name's dir) and push it.

    `branch` is the full short branch name to push (e.g. 'tp/alpha',
    'tp/a/b', 'candidate/x/single'). `write_lock=False` pushes a branch with
    no lock at the expected path.
    """
    _run(["git", "checkout", "-q", "-b", branch], clone)
    if write_lock:
        d = clone / "three-pillars-docs" / "tp-designs" / design_name
        d.mkdir(parents=True, exist_ok=True)
        (d / "lock.json").write_text(json.dumps(lock_obj or {}))
        _run(["git", "add", "-A"], clone)
    else:
        marker = clone / f"marker-{design_name}.txt"
        marker.write_text("no lock\n")
        _run(["git", "add", "-A"], clone)
    _run(["git", "commit", "-q", "-m", f"branch {branch}"], clone)
    _run(["git", "push", "-q", "origin", f"refs/heads/{branch}"], clone)
    _run(["git", "checkout", "-q", "main"], clone)
    return _run(["git", "rev-parse", branch], clone).stdout.strip()


def _entry(design, owner, readable=True):
    return RegistryEntry(
        design=design,
        branch=f"tp/{design}",
        owner=owner,
        phase="plan",
        last_touched=_iso_days_ago(1),
        sha="deadbeef",
        age_days=1.0,
        stale=False,
        readable=readable,
    )


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso_days_ago(days):
    return (_NOW - timedelta(days=days)).isoformat()


# --------------------------------------------------------------------------- #
# Task 1.1 — classify() + dataclasses
# --------------------------------------------------------------------------- #


def test_classify_staleness():
    # Basic field mapping
    lock = {"owner": "a@x", "phase": "plan", "last_touched": _iso_days_ago(5)}
    e = classify(design="d", branch="tp/d", sha="abc", lock=lock, now=_NOW, stale_days=30)
    assert isinstance(e, RegistryEntry)
    assert e.design == "d"
    assert e.branch == "tp/d"
    assert e.sha == "abc"
    assert e.owner == "a@x"
    assert e.phase == "plan"
    assert e.readable is True
    assert e.age_days == pytest.approx(5.0, abs=0.01)
    assert e.stale is False

    # Staleness boundary: 29 not stale, exactly 30 NOT stale (strict >), 31 stale
    e29 = classify("d", "tp/d", "s", {"owner": "a", "last_touched": _iso_days_ago(29)}, _NOW, 30)
    assert e29.stale is False
    e30 = classify("d", "tp/d", "s", {"owner": "a", "last_touched": _iso_days_ago(30)}, _NOW, 30)
    assert e30.stale is False  # exactly 30 days is NOT stale (strict boundary)
    e31 = classify("d", "tp/d", "s", {"owner": "a", "last_touched": _iso_days_ago(31)}, _NOW, 30)
    assert e31.stale is True

    # last_touched explicitly None
    e_none = classify("d", "tp/d", "s", {"owner": "a", "last_touched": None}, _NOW, 30)
    assert e_none.age_days is None
    assert e_none.stale is False

    # last_touched key absent entirely (read via .get, not [...])
    e_absent = classify("d", "tp/d", "s", {"owner": "a"}, _NOW, 30)
    assert e_absent.age_days is None
    assert e_absent.stale is False

    # lock=None → unreadable
    e_unread = classify("d", "tp/d", "s", None, _NOW, 30)
    assert e_unread.readable is False
    assert e_unread.stale is False
    assert e_unread.age_days is None
    assert e_unread.owner is None


# --------------------------------------------------------------------------- #
# Task 1.2 — collision_verdict()
# --------------------------------------------------------------------------- #


def test_collision_verdict():
    me = "me@x"
    entries = [
        _entry("released", owner=None),
        _entry("mine", owner=me),
        _entry("theirs", owner="other@x"),
        _entry("unread", owner=None, readable=False),
    ]

    # No same-name entry → clear, None
    v, ent = collision_verdict(entries, "absent", me)
    assert v == "clear" and ent is None

    # readable & owner None → clear (released)
    v, ent = collision_verdict(entries, "released", me)
    assert v == "clear" and ent is not None and ent.design == "released"

    # readable & owner == me → self
    v, ent = collision_verdict(entries, "mine", me)
    assert v == "self" and ent.design == "mine"

    # readable & owner == other → conflict
    v, ent = collision_verdict(entries, "theirs", me)
    assert v == "conflict" and ent.design == "theirs"

    # not readable same-name → conflict (ownership unconfirmed)
    v, ent = collision_verdict(entries, "unread", me)
    assert v == "conflict" and ent.design == "unread"


# --------------------------------------------------------------------------- #
# Task 1.3 — format_table()
# --------------------------------------------------------------------------- #


def test_format_table():
    stale = RegistryEntry("old", "tp/old", "a@x", "plan", _iso_days_ago(40),
                          "s1", 40.0, True, True)
    fresh = RegistryEntry("new", "tp/new", "b@x", "design", _iso_days_ago(2),
                          "s2", 2.0, False, True)
    unread = RegistryEntry("bad", "tp/bad", None, None, None, "s3", None, False, False)

    out = format_table(Registry(entries=[stale, fresh, unread], degraded=False, source="remote"))
    assert "old" in out and "new" in out and "bad" in out
    assert "a@x" in out and "b@x" in out
    assert "tp/old" in out
    assert "⚠ stale" in out
    assert "· unreadable" in out

    # degraded banner — accurate wording: unavailable, not "showing local view"
    # (the degraded path returns empty; Copilot re-review #3 on PR #24).
    deg = format_table(Registry(entries=[], degraded=True, source="local"))
    assert "unavailable" in deg.lower() and "unreachable" in deg.lower()
    assert "local view only" not in deg.lower()

    # empty (reachable) → no-in-flight line
    empty = format_table(Registry(entries=[], degraded=False, source="remote"))
    assert "no in-flight" in empty.lower()


# --------------------------------------------------------------------------- #
# Task 1.4 — to_json()
# --------------------------------------------------------------------------- #


def test_to_json():
    fresh = RegistryEntry("new", "tp/new", "b@x", "design", _iso_days_ago(2),
                          "s2", 2.0, False, True)
    nullage = RegistryEntry("bad", "tp/bad", None, None, None, "s3", None, False, False)
    reg = Registry(entries=[fresh, nullage], degraded=False, source="remote")

    parsed = json.loads(to_json(reg))
    assert parsed["degraded"] is False
    assert parsed["source"] == "remote"
    assert isinstance(parsed["entries"], list) and len(parsed["entries"]) == 2

    keys = {"design", "branch", "owner", "phase", "last_touched",
            "sha", "age_days", "stale", "readable"}
    for e in parsed["entries"]:
        assert keys.issubset(e.keys())

    # age_days is None → JSON null, key present (not absent, not 0)
    bad = next(e for e in parsed["entries"] if e["design"] == "bad")
    assert "age_days" in bad
    assert bad["age_days"] is None
    assert bad["owner"] is None
    assert bad["readable"] is False


# --------------------------------------------------------------------------- #
# Task 2.1 — list_tp_branches()
# --------------------------------------------------------------------------- #


def test_list_tp_branches(tmp_path):
    origin, clone = _make_origin_and_clone(tmp_path)
    sha_a = _push_branch(clone, "tp/alpha", "alpha", {"owner": "a@x"})
    sha_b = _push_branch(clone, "tp/beta", "beta", {"owner": "b@x"})
    # Outside the glob entirely:
    _push_branch(clone, "candidate/x/single", "x", {"owner": "c@x"})
    # Inside the glob but non-conforming names → filter must reject:
    _push_branch(clone, "tp/Has_Underscore", "Has_Underscore", {"owner": "d@x"})
    _push_branch(clone, "tp/a/b", "a", {"owner": "e@x"})

    branches = list_tp_branches(remote=str(origin))
    assert branches == sorted([("alpha", sha_a), ("beta", sha_b)])


# --------------------------------------------------------------------------- #
# Task 2.2 — read_lock_blob()
# --------------------------------------------------------------------------- #


def test_read_lock_blob(tmp_path, monkeypatch):
    origin, clone = _make_origin_and_clone(tmp_path)
    lock = {"owner": "a@x", "phase": "plan", "last_touched": _iso_days_ago(3)}
    sha_valid = _push_branch(clone, "tp/alpha", "alpha", lock)
    # A branch with no lock at the expected path:
    sha_nolock = _push_branch(clone, "tp/gamma", "gamma", write_lock=False)
    # A branch carrying a malformed (non-JSON) blob at the lock path:
    _run(["git", "checkout", "-q", "-b", "tp/delta"], clone)
    d = clone / "three-pillars-docs" / "tp-designs" / "delta"
    d.mkdir(parents=True, exist_ok=True)
    (d / "lock.json").write_text("{ this is : not json , }")
    _run(["git", "add", "-A"], clone)
    _run(["git", "commit", "-q", "-m", "bad lock"], clone)
    sha_bad = _run(["git", "rev-parse", "tp/delta"], clone).stdout.strip()
    _run(["git", "checkout", "-q", "main"], clone)

    # git operations run from within the clone for these reads:
    monkeypatch.chdir(clone)

    # (1) valid lock → parsed dict
    assert read_lock_blob(sha_valid, "alpha") == lock
    # (2) object not present locally (fabricated SHA) → None, no crash
    fake_sha = "0" * 40
    assert read_lock_blob(fake_sha, "alpha") is None
    # (3) branch with no lock at the expected path → None
    assert read_lock_blob(sha_nolock, "gamma") is None
    # (4) malformed (non-JSON) blob → None
    assert read_lock_blob(sha_bad, "delta") is None


# --------------------------------------------------------------------------- #
# Task 2.3 — build_registry() + fail-open
# --------------------------------------------------------------------------- #


def test_build_registry(tmp_path, monkeypatch):
    origin, clone = _make_origin_and_clone(tmp_path)
    fresh = {"owner": "a@x", "phase": "plan", "last_touched": _iso_days_ago(2)}
    old = {"owner": "b@x", "phase": "design", "last_touched": _iso_days_ago(45)}
    _push_branch(clone, "tp/alpha", "alpha", fresh)
    _push_branch(clone, "tp/beta", "beta", old)

    # A branch whose lock object is NOT present in `clone`: push it from a
    # second clone, so build_registry run from `clone` can't read its blob.
    other = tmp_path / "other"
    _run(["git", "clone", "-q", str(origin), str(other)], tmp_path)
    _run(["git", "config", "user.email", "test@example.com"], other)
    _run(["git", "config", "user.name", "Test"], other)
    _run(["git", "config", "commit.gpgsign", "false"], other)
    _push_branch(other, "tp/orphan", "orphan", {"owner": "c@x"})

    monkeypatch.chdir(clone)
    reg = build_registry(remote=str(origin), now=_NOW)
    assert reg.degraded is False
    assert reg.source == "remote"

    by_name = {e.design: e for e in reg.entries}
    assert set(by_name) == {"alpha", "beta", "orphan"}
    assert by_name["alpha"].owner == "a@x"
    assert by_name["alpha"].stale is False
    assert by_name["beta"].owner == "b@x"
    assert by_name["beta"].stale is True  # 45 days > 30
    # orphan's lock object isn't local → unreadable, not a crash
    assert by_name["orphan"].readable is False


def test_build_registry_empty(tmp_path, monkeypatch):
    origin, clone = _make_origin_and_clone(tmp_path)
    monkeypatch.chdir(clone)
    reg = build_registry(remote=str(origin), now=_NOW)
    # Reachable remote, zero tp/* branches — distinct from degraded.
    assert reg.entries == []
    assert reg.degraded is False
    assert reg.source == "remote"


def test_build_registry_failopen(tmp_path, monkeypatch):
    # A repo with no remote at all → ls-remote against a missing remote fails.
    repo = tmp_path / "lonely"
    repo.mkdir()
    _init_clone(repo)
    (repo / "x.txt").write_text("x\n")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-q", "-m", "init"], repo)
    monkeypatch.chdir(repo)
    reg = build_registry(remote="origin", now=_NOW)
    assert reg.entries == []
    assert reg.degraded is True
    assert reg.source == "local"


def test_list_tp_branches_oserror_failopen(monkeypatch):
    # git not installed / not on PATH → subprocess.run raises OSError. It must
    # surface as RemoteUnreachable (not a raw OSError) so build_registry can
    # fail-open to the degraded local view rather than crashing. (Copilot
    # review #3 on PR #24 — list_tp_branches previously didn't catch OSError.)
    def _boom(*_a, **_k):
        raise OSError("No such file or directory: 'git'")

    monkeypatch.setattr(inflight_registry.subprocess, "run", _boom)
    with pytest.raises(inflight_registry.RemoteUnreachable):
        list_tp_branches(remote="origin")
    reg = build_registry(remote="origin", now=_NOW)
    assert reg.entries == []
    assert reg.degraded is True
    assert reg.source == "local"


# --------------------------------------------------------------------------- #
# Task 3.1 — main(argv) CLI, always exit 0
# --------------------------------------------------------------------------- #


_MODULE = Path(inflight_registry.__file__).resolve()


def _cli(args, cwd):
    return subprocess.run(
        ["python3", str(_MODULE), *args],
        cwd=cwd, capture_output=True, text=True,
    )


def test_main_cli(tmp_path):
    origin, clone = _make_origin_and_clone(tmp_path)
    _push_branch(clone, "tp/alpha", "alpha", {"owner": "a@x", "last_touched": _iso_days_ago(1)})

    # --json --remote <temp> → exit 0, stdout parses as JSON
    r = _cli(["--json", "--remote", str(origin)], cwd=clone)
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["source"] == "remote"
    assert any(e["design"] == "alpha" for e in payload["entries"])

    # --remote <bad> (unreachable) → exit 0 with degraded payload
    r = _cli(["--json", "--remote", str(tmp_path / "nope.git")], cwd=clone)
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["degraded"] is True
    assert payload["source"] == "local"

    # default (no --json) prints a table → exit 0
    r = _cli(["--remote", str(origin)], cwd=clone)
    assert r.returncode == 0
    assert "alpha" in r.stdout

    # --stale-days honored (force everything stale at 0 days)
    r = _cli(["--json", "--remote", str(origin), "--stale-days", "0"], cwd=clone)
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    alpha = next(e for e in payload["entries"] if e["design"] == "alpha")
    assert alpha["stale"] is True

    # argparse usage errors honor the always-exit-0 contract (Copilot re-review
    # on PR #24): unknown flag and bad --stale-days value both return 0, not 2.
    assert _cli(["--bogus-flag"], cwd=clone).returncode == 0
    assert _cli(["--stale-days", "notanint"], cwd=clone).returncode == 0


# --------------------------------------------------------------------------- #
# Task 3.2 — /tp-inflight standalone skill prose-presence
# --------------------------------------------------------------------------- #


_SKILLS_DIR = _MODULE.parent.parent  # skills/
_TP_INFLIGHT_SKILL = _SKILLS_DIR / "tp-inflight" / "SKILL.md"


def test_tp_inflight_skill_prose():
    assert _TP_INFLIGHT_SKILL.exists(), "skills/tp-inflight/SKILL.md must exist"
    text = _TP_INFLIGHT_SKILL.read_text(encoding="utf-8")

    # Frontmatter: name + description
    assert "name: tp-inflight" in text
    assert "description:" in text

    # Documents the fail-open first-step fetch of tp/* refs
    assert "git fetch" in text
    assert "refs/heads/tp/*" in text
    assert "|| true" in text

    # Invokes the shared helper
    assert "inflight_registry.py" in text


# --------------------------------------------------------------------------- #
# Task 4.1 — collaboration.md preflight wiring prose-presence
# --------------------------------------------------------------------------- #


_COLLABORATION = _MODULE.parent / "collaboration.md"


def test_collaboration_wiring_prose():
    assert _COLLABORATION.exists()
    text = _COLLABORATION.read_text(encoding="utf-8")
    low = text.lower()

    # Names the helper
    assert "inflight_registry" in text

    # Remote same-name tp/{name} collision check
    assert "collision" in low
    assert "tp/{design-name}" in text or "tp/{name}" in text

    # Refuse unless --force-takeover
    assert "--force-takeover" in text
    assert "refuse" in low

    # Situational-awareness registry print
    assert "situational-awareness" in low or "situational awareness" in low
    assert "format_table" in text or "registry" in low

    # self-verdict non-blocking notice
    assert "self" in low
    assert "non-blocking" in low or "does not refuse" in low or "do not refuse" in low

    # States it augments, not replaces, the existing local lock check
    assert "augment" in low
    assert "replace" in low

    # Freshness dependency: step 5 relies on step 2's unscoped git fetch
    assert "step 2" in low
    assert "fetch" in low
    assert "unscoped" in low
