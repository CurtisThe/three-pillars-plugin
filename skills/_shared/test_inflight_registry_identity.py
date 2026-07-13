"""Tests for the identity-gated collision_verdict softening (Part B).

A NEW sibling so test_inflight_registry.py (494/500 lines) is never touched.
Imports inflight_registry flat, same way the existing test files do.

Run with: python -m pytest skills/_shared/test_inflight_registry_identity.py -q
"""

import json
import subprocess

import inflight_registry
from inflight_registry import (
    RegistryEntry,
    collision_verdict,
    read_local_lock_owner,
    ref_is_ancestor,
)


# --------------------------------------------------------------------------- #
# Git helpers (temp-repo, matching test_inflight_registry.py style)
# --------------------------------------------------------------------------- #


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def _init_repo(repo):
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    _run(["git", "config", "commit.gpgsign", "false"], repo)


def _commit(repo, filename, content, message):
    (repo / filename).write_text(content)
    _run(["git", "add", filename], repo)
    _run(["git", "commit", "-q", "-m", message], repo)
    return _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()


# --------------------------------------------------------------------------- #
# Task 2.1 — read_local_lock_owner() (fail-open)
# --------------------------------------------------------------------------- #


def test_read_local_lock_owner_wellformed(tmp_path):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "mydesign"
    d.mkdir(parents=True)
    (d / "lock.json").write_text(json.dumps({"owner": "me@x", "phase": "implement"}))
    assert read_local_lock_owner("mydesign", root=str(tmp_path)) == "me@x"


def test_read_local_lock_owner_absent_file(tmp_path):
    assert read_local_lock_owner("nope", root=str(tmp_path)) is None


def test_read_local_lock_owner_unparseable_json(tmp_path):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "bad"
    d.mkdir(parents=True)
    (d / "lock.json").write_text("{ this is : not json , }")
    assert read_local_lock_owner("bad", root=str(tmp_path)) is None


def test_read_local_lock_owner_non_dict_json(tmp_path):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "listy"
    d.mkdir(parents=True)
    (d / "lock.json").write_text(json.dumps(["not", "a", "dict"]))
    assert read_local_lock_owner("listy", root=str(tmp_path)) is None


def test_read_local_lock_owner_missing_owner_key(tmp_path):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "noowner"
    d.mkdir(parents=True)
    (d / "lock.json").write_text(json.dumps({"phase": "implement"}))
    assert read_local_lock_owner("noowner", root=str(tmp_path)) is None


def test_read_local_lock_owner_empty_string_owner(tmp_path):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "emptyowner"
    d.mkdir(parents=True)
    (d / "lock.json").write_text(json.dumps({"owner": ""}))
    assert read_local_lock_owner("emptyowner", root=str(tmp_path)) is None


def test_read_local_lock_owner_non_str_owner(tmp_path):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "numowner"
    d.mkdir(parents=True)
    (d / "lock.json").write_text(json.dumps({"owner": 42}))
    assert read_local_lock_owner("numowner", root=str(tmp_path)) is None


# --------------------------------------------------------------------------- #
# Task 2.2 — ref_is_ancestor() (fail-closed)
# --------------------------------------------------------------------------- #


def test_ref_is_ancestor_true(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    base_sha = _commit(repo, "a.txt", "a\n", "base")
    _commit(repo, "b.txt", "b\n", "second")
    assert ref_is_ancestor(base_sha, "HEAD", cwd=str(repo)) is True


def test_ref_is_ancestor_false_not_ancestor(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "a.txt", "a\n", "base")
    _run(["git", "checkout", "-q", "-b", "side"], repo)
    side_sha = _commit(repo, "side.txt", "side\n", "side commit")
    _run(["git", "checkout", "-q", "main"], repo)
    _commit(repo, "main2.txt", "main2\n", "main-only commit")
    # side_sha is not an ancestor of main's HEAD
    assert ref_is_ancestor(side_sha, "HEAD", cwd=str(repo)) is False


def test_ref_is_ancestor_false_absent_ref(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "a.txt", "a\n", "base")
    fake_sha = "0" * 40
    # exit 128 case: ref doesn't exist locally
    assert ref_is_ancestor(fake_sha, "HEAD", cwd=str(repo)) is False


def test_ref_is_ancestor_false_non_repo_cwd(tmp_path):
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    assert ref_is_ancestor("HEAD", "HEAD", cwd=str(not_a_repo)) is False


def test_ref_is_ancestor_false_git_missing_oserror(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("No such file or directory: 'git'")

    monkeypatch.setattr(inflight_registry.subprocess, "run", _boom)
    assert ref_is_ancestor("HEAD", "HEAD") is False


# --------------------------------------------------------------------------- #
# Task 2.3 — collision_verdict() identity-gated unreadable branch
# --------------------------------------------------------------------------- #


def _entry(design="mydesign", owner=None, readable=True, branch=None):
    """Build a synthetic RegistryEntry for testing — no git required."""
    return RegistryEntry(
        design=design,
        branch=branch or f"tp/{design}",
        owner=owner,
        phase="implement",
        last_touched="2026-06-14T00:00:00+00:00",
        sha="abc1234",
        age_days=0.0,
        stale=False,
        readable=readable,
    )


def test_collision_verdict_identity_holder_to_self():
    entry = _entry(readable=False)
    verdict, matched = collision_verdict(
        [entry], "mydesign", "me@x",
        local_lock_owner="me@x", origin_is_ancestor=True,
    )
    assert verdict == "self"
    assert matched is entry


def test_collision_verdict_identity_holder_to_self_orchestrator_prefixed():
    entry = _entry(readable=False)
    verdict, matched = collision_verdict(
        [entry], "mydesign", "me@x",
        local_lock_owner="orchestrator:me@x", origin_is_ancestor=True,
    )
    assert verdict == "self"
    assert matched is entry


def test_collision_verdict_identity_stranger_to_conflict_even_with_ancestor():
    entry = _entry(readable=False)
    # Safety-inversion case: ancestor=True but no matching identity signal.
    verdict, matched = collision_verdict(
        [entry], "mydesign", "me@x",
        local_lock_owner=None, origin_is_ancestor=True,
    )
    assert verdict == "conflict"
    assert matched is entry

    verdict2, _ = collision_verdict(
        [entry], "mydesign", "me@x",
        local_lock_owner="other@x", origin_is_ancestor=True,
    )
    assert verdict2 == "conflict"


def test_collision_verdict_identity_match_but_ancestor_false():
    entry = _entry(readable=False)
    verdict, matched = collision_verdict(
        [entry], "mydesign", "me@x",
        local_lock_owner="me@x", origin_is_ancestor=False,
    )
    assert verdict == "conflict"
    assert matched is entry


def test_collision_verdict_identity_backward_compat_legacy_call():
    entry = _entry(readable=False)
    # Legacy 3-arg call (no local_lock_owner/origin_is_ancestor) on an
    # unreadable match must still resolve conflict (defaults are safe).
    verdict, matched = collision_verdict([entry], "mydesign", "me@x")
    assert verdict == "conflict"
    assert matched is entry


def test_collision_verdict_identity_readable_paths_unchanged():
    released = _entry(design="released", owner=None)
    mine = _entry(design="mine", owner="me@x")
    theirs = _entry(design="theirs", owner="other@x")
    entries = [released, mine, theirs]

    v, ent = collision_verdict(entries, "released", "me@x")
    assert v == "clear" and ent is released

    v, ent = collision_verdict(entries, "mine", "me@x")
    assert v == "self" and ent is mine

    v, ent = collision_verdict(entries, "theirs", "me@x")
    assert v == "conflict" and ent is theirs


# --------------------------------------------------------------------------- #
# Task 2.4 — end-to-end stranger test (wiring, not just the pure function)
# --------------------------------------------------------------------------- #


def test_end_to_end_stranger_no_local_lock_resolves_conflict(tmp_path):
    """A design with NO on-disk lock file: read_local_lock_owner -> None,
    fed into collision_verdict on an unreadable match -> conflict. Pins that
    the composed wiring (not just the pure function) rejects a stranger who
    has no local lock at all — even if the origin ref happens to be an
    ancestor of local HEAD.
    """
    local_owner = read_local_lock_owner("neverclaimed", root=str(tmp_path))
    assert local_owner is None

    entry = _entry(design="neverclaimed", readable=False)
    verdict, matched = collision_verdict(
        [entry], "neverclaimed", "stranger@x",
        local_lock_owner=local_owner, origin_is_ancestor=True,
    )
    assert verdict == "conflict"
    assert matched is entry
