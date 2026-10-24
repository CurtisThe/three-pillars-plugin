"""`accept` is audited and a run is not told how to use it (run-scratch-in-fence B3).

Enforcement inside the run cannot rest on an env var (the finalizer runs in the same
session), so the audited form is: `accept` appends a `### [scratch_leftovers] accepted
<path>` entry (path, date, reason, who) to the design's decisions.md and exits 2 when it
cannot write that entry; a failing `check` under `TP_DESIGN_RUN=1` does not print the
accept command; every accepted path stays visible as a `scratch-allowed:` line (the
PR body lists them, pinned in test_run_scratch_gates_doc.py).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_scratch_leftovers import SLUG, fx  # noqa: E402,F401  (fixture)

STOP = "stop: the finalizer or the operator inspects the path and accepts it"


def design_dir(fx):
    d = fx.wt / "three-pillars-docs" / "tp-designs" / SLUG
    d.mkdir(parents=True)
    return d


def stray(fx):
    fx.run("provision")
    p = fx.tmp / "sibling"
    p.mkdir()
    return p


def accepted(fx):
    return json.loads(fx.baseline.read_text(encoding="utf-8"))["accepted"]


def test_accept_appends_a_decisions_entry_with_path_date_reason_and_who(fx):
    log = design_dir(fx) / "decisions.md"
    log.write_text("# decisions\n", encoding="utf-8")
    p = stray(fx)
    env = dict(fx.env, TP_DESIGN_RUN="1")
    assert fx.run("accept", "--path", str(p), "--reason", "sibling window", env=env)[0] == 0
    body = log.read_text(encoding="utf-8")
    assert body.startswith("# decisions\n")
    assert "### [scratch_leftovers] accepted %s" % p in body
    assert "sibling window" in body and "TP_DESIGN_RUN=1" in body
    import datetime
    assert datetime.date.today().isoformat() in body
    assert len(accepted(fx)) == 1


def test_accept_creates_decisions_md_when_the_design_dir_exists(fx):
    d = design_dir(fx)
    p = stray(fx)
    assert fx.run("accept", "--path", str(p), "--reason", "r")[0] == 0
    body = (d / "decisions.md").read_text(encoding="utf-8")
    assert "### [scratch_leftovers] accepted %s" % p in body and "TP_DESIGN_RUN=unset" in body


def test_accept_takes_an_explicit_design_dir(fx):
    d = fx.wt / "three-pillars-docs" / "completed-tp-designs" / SLUG
    d.mkdir(parents=True)
    p = stray(fx)
    assert fx.run("accept", "--path", str(p), "--reason", "r", "--design-dir", str(d))[0] == 0
    assert "accepted %s" % p in (d / "decisions.md").read_text(encoding="utf-8")


def test_accept_fails_with_2_and_accepts_nothing_when_it_cannot_write_the_entry(fx):
    p = stray(fx)  # no design dir at all
    rc, out = fx.run("accept", "--path", str(p), "--reason", "r")
    assert rc == 2 and accepted(fx) == []
    assert fx.run("check")[0] == 1
    (design_dir(fx) / "decisions.md").mkdir()  # a directory: the append fails
    assert fx.run("accept", "--path", str(p), "--reason", "r")[0] == 2
    assert accepted(fx) == [] and fx.run("check")[0] == 1


def test_check_under_a_design_run_does_not_hand_the_run_the_accept_command(fx):
    stray(fx)
    env = dict(fx.env, TP_DESIGN_RUN="1")
    rc, out = fx.run("check", env=env)
    assert rc == 1 and STOP in out
    assert "scratch_leftovers.py accept" not in out and "accept --path" not in out
    assert "TP_SCRATCH_ALLOW" not in out


def test_check_outside_a_design_run_still_prints_the_recovery_with_accept(fx):
    stray(fx)
    rc, out = fx.run("check")
    assert rc == 1 and STOP not in out and "accept --path P --reason R" in out


def test_an_accepted_path_is_still_listed_on_every_check(fx):
    design_dir(fx)
    p = stray(fx)
    assert fx.run("accept", "--path", str(p), "--reason", "inspected")[0] == 0
    for _ in range(2):
        rc, out = fx.run("check", env=dict(fx.env, TP_DESIGN_RUN="1"))
        assert rc == 0 and "scratch-allowed: %s (accepted " % p in out and "inspected)" in out
