"""Tests for review_prep.cache_* — the per-head cache (design D3, Task 3.2).

`cache_get` re-runs the slot oracle before handing back the stored artifact
(here the real `hunk_bytes` oracle over a real diff file); stale, corrupt,
mismatched or bumped entries are unlinked. The stored artifact is never
modified, and a recheck verdict is a `cheap_oracle.Verdict` dict — a truthy
`verdict["ok"]` passes, anything else (non-dict, raising) is a failed
recheck.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_prep  # noqa: E402 — also puts skills/_shared on sys.path
import cheap_oracle  # noqa: E402

BASE = "a" * 40
HEAD = "b" * 40
OTHER_HEAD = "c" * 40
SLOT = "review_slice"
UNIT = "correctness-leak"  # units may contain `-`

DIFF = ("diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n")
HUNK = "@@ -1 +1 @@\n-x\n+y\n"


def _artifact() -> dict:
    return {"hunks": [{"file": "a.py", "hunk": HUNK}]}


def _diff_file(tmp_path: Path, text: str = DIFF) -> Path:
    diff = tmp_path / "diff.patch"
    diff.write_text(text, encoding="utf-8")
    return diff


def _recheck(diff_file: Path):
    """The real oracle: hunk_bytes over the real diff text at diff_file."""
    return lambda a: cheap_oracle.check(SLOT, a, {"diff_path": str(diff_file)})


def test_cache_key_format():
    key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    assert key == f"{BASE}-{HEAD}-{SLOT}-{UNIT}-v{review_prep.SLICER_VERSION}.json"


def test_hit_returns_stored_artifact_unchanged(tmp_path):
    cache = tmp_path / "prep-cache"  # not created yet: cache_put makes it
    diff_file = _diff_file(tmp_path)
    artifact = _artifact()
    key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    review_prep.cache_put(cache, key, artifact)

    assert review_prep.cache_get(cache, key, _recheck(diff_file)) == artifact

    # Stored entry is exactly {slot, unit, base, head, version, artifact} and
    # the artifact carries no extra keys.
    entry = json.loads((cache / key).read_text(encoding="utf-8"))
    assert set(entry) == {"slot", "unit", "base", "head", "version", "artifact"}
    assert (entry["slot"], entry["unit"], entry["base"], entry["head"]) == (SLOT, UNIT, BASE, HEAD)
    assert entry["version"] == review_prep.SLICER_VERSION
    assert entry["artifact"] == artifact
    assert set(artifact) == {"hunks"}


def test_recheck_fail_unlinks_and_returns_none(tmp_path):
    cache = tmp_path
    diff_file = _diff_file(tmp_path)
    key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    review_prep.cache_put(cache, key, _artifact())
    assert (cache / key).is_file()

    # The diff changes so the stored hunk is no longer byte-for-byte one of its hunks.
    _diff_file(tmp_path, DIFF.replace("+y\n", "+z\n"))
    assert review_prep.cache_get(cache, key, _recheck(diff_file)) is None
    assert not (cache / key).exists()


def test_changed_head_is_a_miss_and_keeps_this_head_entry(tmp_path):
    cache = tmp_path
    diff_file = _diff_file(tmp_path)
    hit_key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    other_key = review_prep.cache_key(BASE, OTHER_HEAD, SLOT, UNIT)
    review_prep.cache_put(cache, hit_key, _artifact())

    assert review_prep.cache_get(cache, other_key, _recheck(diff_file)) is None
    assert (cache / hit_key).is_file()  # the miss must not unlink this head's entry


def test_stored_version_bump_misses(tmp_path):
    cache = tmp_path
    diff_file = _diff_file(tmp_path)
    key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    entry = {"slot": SLOT, "unit": UNIT, "base": BASE, "head": HEAD,
             "version": review_prep.SLICER_VERSION - 1, "artifact": _artifact()}
    (cache / key).write_text(json.dumps(entry), encoding="utf-8")

    assert review_prep.cache_get(cache, key, _recheck(diff_file)) is None
    assert not (cache / key).exists()


def test_corrupt_entry_misses(tmp_path):
    cache = tmp_path
    diff_file = _diff_file(tmp_path)
    key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    (cache / key).write_text("{not json", encoding="utf-8")

    assert review_prep.cache_get(cache, key, _recheck(diff_file)) is None
    assert not (cache / key).exists()


def test_field_mismatch_misses(tmp_path):
    cache = tmp_path
    diff_file = _diff_file(tmp_path)
    key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    entry = {"slot": SLOT, "unit": "edge-cases", "base": BASE, "head": HEAD,
             "version": review_prep.SLICER_VERSION, "artifact": _artifact()}
    (cache / key).write_text(json.dumps(entry), encoding="utf-8")

    assert review_prep.cache_get(cache, key, _recheck(diff_file)) is None
    assert not (cache / key).exists()


def test_recheck_that_raises_is_a_miss(tmp_path):
    cache = tmp_path
    key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    review_prep.cache_put(cache, key, _artifact())

    def boom(artifact):
        raise RuntimeError("no ctx")

    assert review_prep.cache_get(cache, key, boom) is None
    assert not (cache / key).exists()


def test_recheck_non_dict_verdict_is_a_miss(tmp_path):
    cache = tmp_path
    key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    review_prep.cache_put(cache, key, _artifact())

    assert review_prep.cache_get(cache, key, lambda a: "ok") is None
    assert review_prep.cache_get(cache, key, lambda a: {"reason": "no ok key"}) is None
    assert not (cache / key).exists()


def test_missing_entry_is_a_plain_miss(tmp_path):
    assert review_prep.cache_get(tmp_path, review_prep.cache_key(BASE, HEAD, SLOT, UNIT),
                                 _recheck(_diff_file(tmp_path))) is None


def test_put_rejects_keys_that_do_not_parse(tmp_path):
    for bad in ("junk.json",
                f"{BASE}-{HEAD}-not_a_slot-{UNIT}-v1.json",
                f"{BASE}-{HEAD}-{SLOT}-{UNIT}.json"):
        try:
            review_prep.cache_put(tmp_path, bad, _artifact())
        except ValueError:
            pass
        else:
            raise AssertionError(f"cache_put accepted {bad!r}")
        assert not (tmp_path / bad).exists()


def test_prune_drops_other_heads_only(tmp_path):
    cache = tmp_path
    keep_key = review_prep.cache_key(BASE, HEAD, SLOT, UNIT)
    drop_key = review_prep.cache_key(BASE, OTHER_HEAD, SLOT, UNIT)
    review_prep.cache_put(cache, keep_key, _artifact())
    review_prep.cache_put(cache, drop_key, _artifact())
    (cache / "junk.json").write_text("{not json", encoding="utf-8")

    assert review_prep.cache_prune(cache, HEAD) == 2  # other head + unparseable
    assert (cache / keep_key).is_file()
    assert not (cache / drop_key).exists()
    assert not (cache / "junk.json").exists()
    assert review_prep.cache_prune(cache, HEAD) == 0  # nothing left to drop


def test_prune_missing_dir_returns_zero(tmp_path):
    assert review_prep.cache_prune(tmp_path / "no-such-dir", HEAD) == 0
