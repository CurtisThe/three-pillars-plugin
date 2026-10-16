"""round_plan.plan — round 1: the full-PR angle set, and the security lens always on.

design: review-convergence (Task 4.3, detailed-design-pr-loop §D3)

Review bar: round 1 reviews the WHOLE PR — `mode: full`, `base == pr_base`. A PR
diff under `SMALL_DIFF_LINES` counted lines collapses its finders to ONE `combined`
angle; at the cap the three `DEFAULT_ANGLES` run. The Opus check stays either way,
and the `security` angle is appended always: `config.review.angles` cannot drop it,
a config that declares one cannot duplicate it, and a detector failure leaves the
lens ON with no surfaces.
Oracle: example — exact angle names and counts on a real tmp git repo (test-fragility).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import finder_round  # noqa: E402
import role_engine  # noqa: E402
import round_plan  # noqa: E402
import trust_boundary  # noqa: E402

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}

PR_URL = "https://github.com/o/r/pull/9"
RULINGS = "/x/rulings.md"
LOCAL = {"role_engines": {"review_finder": "local"}}
ONE_ANGLE = {"review": {"angles": [{"name": "my-angle", "role": "confirmer",
                                    "model": "opus", "prompt": "look at mine"}]}}


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


def _pr(tmp_path, name, lines):
    """A repo whose PR adds `lines` counted lines: → (repo, pr_base, head)."""
    r = tmp_path / name
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "keep.py", "one = 1\n")
    base = _commit(r, "base")
    _write(r, "work.sh", "".join(f"# line {i}\n" for i in range(lines)))
    return r, base, _commit(r, "pr work")


def _plan(tmp_path, pr, config=None, *, root=None, local=False, **kw):
    """`plan` over `pr` with a fresh (empty) rounds dir unless `root` says otherwise."""
    r, base, head = pr
    return round_plan.plan(config, root=root if root is not None else tmp_path / "root",
                           pr_url=PR_URL, pr_base=base, head=head, repo=str(r),
                           rulings_path=RULINGS,
                           **({"available": lambda: True} if local else {}), **kw)


def _names(entries) -> list:
    return sorted(a["name"] for a in entries)


def _by_name(entries) -> dict:
    return {a["name"]: a for a in entries}


def _local(monkeypatch):
    """The `--local` fixture of test_finder_round_angles.py: finders on Strata."""
    monkeypatch.setattr(role_engine, "run_local",
                        lambda cfg: bool((cfg or {}).get("role_engines")))


# ---------- round 1 is the whole PR ----------


def test_round_one_is_the_full_pr(tmp_path):
    r, base, head = _pr(tmp_path, "small", 299)
    got = _plan(tmp_path, (r, base, head))
    assert got["round"] == 1
    assert got["mode"] == "full"
    assert got["base"] == got["pr_base"] == base
    assert got["diff_lines"] == 299
    assert got["security"] is True


def test_a_diff_at_the_cap_is_counted_at_the_cap(tmp_path):
    r, base, head = _pr(tmp_path, "atcap", 300)
    got = _plan(tmp_path, (r, base, head))
    assert got["diff_lines"] == 300
    assert got["mode"] == "full" and got["base"] == base


def test_a_small_diff_runs_one_combined_finder(tmp_path):
    r, base, head = _pr(tmp_path, "small", 299)
    entries = _plan(tmp_path, (r, base, head))["angles"]
    finders = [a for a in entries if a["name"] not in (finder_round.CHECK_NAME,
                                                       angles.SECURITY_ANGLE)]
    assert len(finders) == 1 and finders[0]["name"] == "combined"
    assert finders[0]["role"] == "finder" and finders[0]["advisory"] is True
    assert len(entries) == 3
    assert entries[-1]["name"] == angles.SECURITY_ANGLE  # appended last, once


def test_a_diff_at_the_cap_keeps_the_three_finders(tmp_path):
    r, base, head = _pr(tmp_path, "atcap", 300)
    entries = _plan(tmp_path, (r, base, head))["angles"]
    assert _names(entries) == sorted([a["name"] for a in angles.DEFAULT_ANGLES]
                                     + [finder_round.CHECK_NAME, angles.SECURITY_ANGLE])
    assert len(entries) == len(angles.DEFAULT_ANGLES) + 2


def test_the_opus_check_survives_the_collapse(tmp_path):
    for lines in (299, 300):
        r, base, head = _pr(tmp_path, f"chk{lines}", lines)
        check = _by_name(_plan(tmp_path, (r, base, head))["angles"])[finder_round.CHECK_NAME]
        assert check == finder_round.check_angle(RULINGS)
        assert (check["role"], check["model"]) == ("confirmer", "opus")


def test_the_combined_angle_carries_every_default_prompt(tmp_path):
    r, base, head = _pr(tmp_path, "small", 299)
    combined = _by_name(_plan(tmp_path, (r, base, head))["angles"])["combined"]
    assert combined["prompt"].startswith(angles.DEFAULT_ANGLES[0]["prompt"])
    for declared in angles.DEFAULT_ANGLES[1:]:
        assert declared["prompt"] in combined["prompt"]
    assert RULINGS in combined["prompt"]  # the cheap-round rulings suffix rides along


def test_combined_keeps_the_first_angles_role_model_and_advisory():
    out = round_plan.combined([
        {"name": "a", "prompt": "A", "role": "finder", "model": "local", "advisory": True},
        {"name": "b", "prompt": "B", "role": "confirmer", "model": "opus"},
    ])
    assert len(out) == 1
    one = out[0]
    assert one["name"] == "combined" and one["prompt"] == "A; B"
    assert (one["role"], one["model"], one["advisory"]) == ("finder", "local", True)
    plain = round_plan.combined([
        {"name": "a", "prompt": "A", "role": "confirmer", "model": "opus"},
        {"name": "b", "prompt": "B", "role": "finder", "model": "local", "advisory": True},
    ])[0]
    assert (plain["role"], plain["model"]) == ("confirmer", "opus")
    assert "advisory" not in plain


# ---------- the security lens, under both engines ----------


def test_the_security_angle_is_appended_whatever_the_detector_finds(tmp_path):
    r, base, head = _pr(tmp_path, "small", 299)
    sec = _by_name(_plan(tmp_path, (r, base, head))["angles"])[angles.SECURITY_ANGLE]
    assert (sec["role"], sec["model"]) == ("confirmer", "opus")
    assert sec["name"] == angles.SECURITY_ANGLE
    assert str(trust_boundary.brief_path(r)) in sec["prompt"]
    assert trust_boundary.SECURITY_BAR in sec["prompt"]


def test_plan_is_the_same_under_the_local_engine(tmp_path, monkeypatch):
    _local(monkeypatch)
    r, base, head = _pr(tmp_path, "small", 299)
    got = _plan(tmp_path, (r, base, head), LOCAL, local=True)
    entries = _by_name(got["angles"])
    assert set(entries) == {"combined", finder_round.CHECK_NAME, angles.SECURITY_ANGLE}
    assert entries["combined"]["model"] == "local"
    assert entries[finder_round.CHECK_NAME] == finder_round.check_angle(RULINGS)
    assert got["security"] is True and got["diff_lines"] == 299


def test_a_local_engine_round_at_the_cap_keeps_the_three_finders(tmp_path, monkeypatch):
    _local(monkeypatch)
    r, base, head = _pr(tmp_path, "atcap", 300)
    entries = _plan(tmp_path, (r, base, head), LOCAL, local=True)["angles"]
    assert _names(entries) == sorted([a["name"] for a in angles.DEFAULT_ANGLES]
                                     + [finder_round.CHECK_NAME, angles.SECURITY_ANGLE])


def test_a_cheap_round_without_rulings_propagates_the_valueerror(tmp_path):
    r, base, head = _pr(tmp_path, "small", 299)
    with pytest.raises(ValueError):
        round_plan.plan(None, root=tmp_path / "root", pr_url=PR_URL, pr_base=base,
                        head=head, repo=str(r))


# ---------- config cannot drop or duplicate the lens ----------


def test_declared_angles_cannot_drop_the_security_angle(tmp_path):
    r, base, head = _pr(tmp_path, "small", 299)
    entries = _plan(tmp_path, (r, base, head), ONE_ANGLE)["angles"]
    assert angles.SECURITY_ANGLE in _names(entries)
    assert _names(entries) == sorted(["combined", finder_round.CHECK_NAME,
                                      angles.SECURITY_ANGLE])


def test_a_declared_security_angle_is_replaced_not_duplicated(tmp_path):
    cfg = {"review": {"angles": [{"name": angles.SECURITY_ANGLE, "role": "confirmer",
                                  "model": "opus", "prompt": "my own security pass"}]}}
    r, base, head = _pr(tmp_path, "small", 299)
    entries = _plan(tmp_path, (r, base, head), cfg)["angles"]
    assert _names(entries).count(angles.SECURITY_ANGLE) == 1
    assert len(entries) == len(_names(entries))
    sec = _by_name(entries)[angles.SECURITY_ANGLE]
    assert "my own security pass" not in sec["prompt"]
    assert str(trust_boundary.brief_path(r)) in sec["prompt"]


def test_a_detector_failure_leaves_the_lens_on(tmp_path, monkeypatch):
    def boom(*_a, **_kw):
        raise trust_boundary.TrustBoundaryError("git diff failed")

    monkeypatch.setattr(trust_boundary, "surfaces_for_range", boom)
    r, base, head = _pr(tmp_path, "small", 299)
    got = _plan(tmp_path, (r, base, head))
    sec = _by_name(got["angles"])[angles.SECURITY_ANGLE]
    assert got["security"] is True
    assert "none — review the diff anyway" in sec["prompt"]


# ---------- the round number, and refusals ----------


def test_an_empty_rounds_dir_is_still_round_one(tmp_path):
    r, base, head = _pr(tmp_path, "small", 299)
    root = tmp_path / "root"
    (root / "rounds" / "9").mkdir(parents=True)  # dir exists, no round in it
    assert _plan(tmp_path, (r, base, head), root=root)["round"] == 1


def test_plan_refuses_a_url_that_is_not_a_pr(tmp_path):
    r, base, head = _pr(tmp_path, "small", 299)
    with pytest.raises(ValueError):
        round_plan.plan(None, root=tmp_path / "root", pr_url="https://github.com/o/r",
                        pr_base=base, head=head, repo=str(r), rulings_path=RULINGS)
