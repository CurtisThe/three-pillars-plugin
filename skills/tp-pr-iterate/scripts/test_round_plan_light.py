"""round_plan.plan under review_weight light / just-do-it: one confirmer + opus-check.

design: light-run-ceremony-diet (Task 1.3, B2)

Round 1 of a light (or just-do-it) run is exactly one `combined` finder plus the
Opus check, whatever the diff size; `security` only joins on a gate path, a trust
surface, or a detector failure. None / "full" keep today's plan.
Oracle: example - exact angle names on a real tmp git repo (test-fragility).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import finder_round  # noqa: E402
import finder_segments  # noqa: E402
import round_plan  # noqa: E402
import trust_boundary  # noqa: E402

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}
PR_URL = "https://github.com/o/r/pull/9"
RULINGS = "/x/rulings.md"
CHECK = finder_round.CHECK_NAME


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                         text=True, env=env, check=True)
    return out.stdout.strip()


def _write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _pr(tmp_path, name, *, gate=False):
    """A PR adding a 1,200-line non-gate file (and a gate file when asked)."""
    r = tmp_path / name
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "keep.py", "one = 1\n")
    base = _commit(r, "base")
    _write(r, "pkg/big.py", "".join(f"value_{i} = {i}\n" for i in range(1200)))
    if gate:
        _write(r, "skills/_shared/delete_fence_extra.py", "a = 1\nb = 2\n")
    return r, base, _commit(r, "pr work")


def _plan(tmp_path, pr, **kw):
    r, base, head = pr
    return round_plan.plan(None, root=tmp_path / "root", pr_url=PR_URL, pr_base=base,
                           head=head, repo=str(r), rulings_path=RULINGS, **kw)


def _names(got):
    return [a["name"] for a in got["angles"]]


def test_a_big_non_gate_diff_runs_one_finder_and_the_check(tmp_path):
    got = _plan(tmp_path, _pr(tmp_path, "a"), review_weight="light")
    assert _names(got) == ["combined", CHECK]
    assert got["security"] is False


def test_a_gate_path_adds_security(tmp_path):
    got = _plan(tmp_path, _pr(tmp_path, "b", gate=True), review_weight="light")
    assert _names(got) == ["combined", CHECK, angles.SECURITY_ANGLE]
    assert got["security"] is True


def test_a_detector_failure_keeps_security(tmp_path, monkeypatch):
    def boom(*_a, **_kw):
        raise trust_boundary.TrustBoundaryError("git diff failed")

    monkeypatch.setattr(trust_boundary, "surfaces_for_range", boom)
    got = _plan(tmp_path, _pr(tmp_path, "c"), review_weight="light")
    assert _names(got) == ["combined", CHECK, angles.SECURITY_ANGLE]
    assert got["security"] is True


def test_full_and_none_are_unchanged(tmp_path):
    pr = _pr(tmp_path, "d")
    full = _plan(tmp_path, pr, review_weight="full")
    none = _plan(tmp_path, pr, review_weight=None)
    assert full == none
    assert set(_names(none)) == {*(a["name"] for a in angles.DEFAULT_ANGLES), CHECK,
                                 angles.SECURITY_ANGLE}
    assert len(none["angles"]) == len(angles.DEFAULT_ANGLES) + 2
    assert none["security"] is True


def test_round_two_under_light_is_still_one_delta_check(tmp_path):
    r, base, head = _pr(tmp_path, "e")
    root = tmp_path / "root"
    rd = round_plan._rounds_dir(root, PR_URL) / "r1"
    (rd / "tail").mkdir(parents=True)
    (rd / "angles.json").write_text(json.dumps({"head": head}), encoding="utf-8")
    (rd / "tail" / "findings.json").write_text("[]", encoding="utf-8")
    (rd / "tail" / "envelope.json").write_text(
        json.dumps({"action": "fix", "head_reviewed": head, "head_after": head}),
        encoding="utf-8")
    _write(r, "pkg/more.py", "x = 1\n")
    head2 = _commit(r, "fix")
    got = round_plan.plan(None, root=root, pr_url=PR_URL, pr_base=base, head=head2,
                          repo=str(r), rulings_path=RULINGS, review_weight="light")
    assert got["round"] == 2
    assert [a["name"] for a in got["angles"]] == ["delta-check"]


def test_just_do_it_takes_the_light_round(tmp_path):
    got = _plan(tmp_path, _pr(tmp_path, "f"), review_weight="just-do-it")
    assert _names(got) == ["combined", CHECK]
    assert got["security"] is False


def test_strata_cut_of_combined_is_bounded(tmp_path):
    r, base, head = pr = _pr(tmp_path, "g")
    got = _plan(tmp_path, pr, review_weight="light")
    entries = []
    for a in got["angles"]:
        a = dict(a)
        if a["name"] == "combined":
            a.update(role="finder", model="local", advisory=True)
        entries.append(a)
    out = finder_segments.apply_to_round(entries, None, repo=str(r), base=base, head=head)
    for a in out:
        assert a["name"] == CHECK or re.fullmatch(r"combined-s\d+", a["name"]), a["name"]
    assert len([a for a in out if not a.get("skipped")]) <= 4
