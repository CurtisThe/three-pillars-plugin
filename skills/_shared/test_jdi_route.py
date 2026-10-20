"""Hermetic tests for jdi_eligibility.route — Tier 1 routing behaviour.

Routing never goes lighter than declared; an eligible `just-do-it` design routes
`just-do-it`; an ineligible one (or bad input) routes `light` with the class
stamped into design.md and its siblings and the escalation line returned. A
failed stamp or a missing design dir is bad input: the CLI exits 2.

Fixture repos are tmp dirs with GIT_* removed (the `rig` pattern in
test_launch_design_run.py); identity goes through `-c`. The entry points are
`route` and the `route` subcommand of `main`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jdi_eligibility as je  # noqa: E402
import weight_class as wc  # noqa: E402

SCOPE_CLEAN = (
    "### In scope\n\n"
    "- `skills/foo/bar.py` (new)\n\n"
    "### Out of scope\n\n"
    "- nothing yet\n"
)
SCOPE_EXCLUDED = "### In scope\n\n- `skills/_shared/launch_design_run.py` (modify)\n"


def _git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(cwd), check=True, capture_output=True,
    )


def _rev(repo, ref):
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _commit(repo, paths: dict) -> str:
    for rel, body in paths.items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "head", cwd=repo)
    return _rev(repo, "HEAD")


def _design(tmp_path, klass="just-do-it", scope_body=SCOPE_CLEAN) -> Path:
    d = tmp_path / "design"
    d.mkdir(parents=True, exist_ok=True)
    head = f"---\nweight-class: {klass}\nslug: fixture\n---\n\n"
    (d / "design.md").write_text(
        head + "# fixture — design\n\n## Scope\n\n" + scope_body + "\n"
        "## Behaviors\n\n1. It works.\n",
        encoding="utf-8",
    )
    (d / "seed.md").write_text(head + "# fixture — seed\n", encoding="utf-8")
    return d


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-q", cwd=r)
    _git("commit", "-q", "--allow-empty", "-m", "base", cwd=r)
    return r


def _route(d, repo, base, head):
    return je.route(str(d), base, head, repo=str(repo))


def _snapshot(d):
    return {p.name: p.read_bytes() for p in (d / "design.md", d / "seed.md")}


# --- (a) eligible just-do-it routes just-do-it -------------------------------


def test_eligible_jdi_routes_jdi_with_no_stamp(tmp_path, repo):
    d = _design(tmp_path)
    before = _snapshot(d)
    base = head = _rev(repo, "HEAD")
    assert _route(d, repo, base, head) == ("just-do-it", None)
    assert _snapshot(d) == before


# --- (b) an excluded Scope surface routes light, stamped and logged ----------


def test_excluded_scope_routes_light_stamping_both_artifacts(tmp_path, repo):
    d = _design(tmp_path, scope_body=SCOPE_EXCLUDED)
    base = head = _rev(repo, "HEAD")
    klass, line = _route(d, repo, base, head)
    assert klass == "light"
    assert line is not None and "skills/_shared/launch_design_run.py" in line
    assert wc.read_class(d) == ("light", "frontmatter")
    seed_fm = wc.parse_frontmatter((d / "seed.md").read_text(encoding="utf-8"))
    assert seed_fm["weight-class"] == "light"
    assert wc.check_consistency(d) == []


# --- (c) the diff cap routes light ------------------------------------------


def test_diff_cap_over_150_routes_light_naming_the_cap(tmp_path, repo):
    d = _design(tmp_path)
    base = _rev(repo, "HEAD")
    head = _commit(repo, {"src/a.py": "".join(f"x = {i}\n" for i in range(151))})
    klass, line = _route(d, repo, base, head)
    assert klass == "light"
    assert "diff-cap" in line


# --- (d) bad input routes light ---------------------------------------------


def test_unresolvable_base_routes_light_naming_bad_input(tmp_path, repo):
    d = _design(tmp_path)
    head = _rev(repo, "HEAD")
    klass, line = _route(d, repo, "definitely-not-a-ref", head)
    assert klass == "light"
    assert "bad-input" in line


# --- (e) a heavier declared class is returned unchanged ---------------------


@pytest.mark.parametrize("klass", ["light", "full", "spike"])
def test_declared_class_heavier_than_jdi_is_returned_unchanged(tmp_path, repo, klass):
    d = _design(tmp_path, klass)
    before = _snapshot(d)
    base = _rev(repo, "HEAD")
    head = _commit(repo, {"skills/_shared/launch_design_run.py": "x = 1\n"})
    assert _route(d, repo, base, head) == (klass, None)
    assert _snapshot(d) == before


# --- (f) property: routing never goes lighter than declared -----------------


def test_routed_class_is_never_lighter_than_declared(tmp_path, repo):
    order = list(wc.VALID_CLASSES)
    base = _rev(repo, "HEAD")
    head_big = _commit(repo, {"src/a.py": "".join(f"x = {i}\n" for i in range(151))})
    for i, klass in enumerate(order):
        for scope_name, scope in (("clean", SCOPE_CLEAN), ("excl", SCOPE_EXCLUDED)):
            d = _design(tmp_path / f"design{i}-{scope_name}", klass, scope)
            for ref_name, ref in (("ok", base), ("big", head_big), ("bad", "nope-ref")):
                routed, _ = _route(d, repo, ref, head_big)
                assert order.index(routed) >= order.index(klass), (klass, ref_name)


# --- (g) a second route after an escalation is settled ----------------------


def test_second_route_after_an_escalation_returns_light_without_a_line(tmp_path, repo):
    d = _design(tmp_path, scope_body=SCOPE_EXCLUDED)
    base = head = _rev(repo, "HEAD")
    assert _route(d, repo, base, head)[0] == "light"
    assert _route(d, repo, base, head) == ("light", None)


# --- (h) a failed stamp is bad input, never a just-do-it route --------------


@pytest.mark.parametrize("exc", [OSError("disk"), ValueError("refused")])
def test_a_failing_escalate_exits_2_as_bad_input(tmp_path, repo, monkeypatch, capsys, exc):
    def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(wc, "escalate", boom)
    d = _design(tmp_path, scope_body=SCOPE_EXCLUDED)
    base = head = _rev(repo, "HEAD")
    rc = je.main(["route", "--design-dir", str(d), "--base", base,
                  "--head", head, "--repo", str(repo)])
    out = capsys.readouterr().out
    assert rc == 2
    assert out.startswith("ESCALATE bad-input")
    assert "route: just-do-it" not in out


# --- (i) a missing or moved design dir is bad input -------------------------


def test_missing_design_dir_exits_2_creating_nothing(tmp_path, repo, capsys):
    gone = tmp_path / "archived" / "design"
    base = head = _rev(repo, "HEAD")
    rc = je.main(["route", "--design-dir", str(gone), "--base", base,
                  "--head", head, "--repo", str(repo)])
    assert rc == 2
    assert capsys.readouterr().out.startswith("ESCALATE bad-input")
    assert not (tmp_path / "archived").exists()


# --- CLI: prints the route line, then the escalation line -------------------


def test_cli_route_prints_route_then_escalation_line_exit_0(tmp_path, repo, capsys):
    d = _design(tmp_path, scope_body=SCOPE_EXCLUDED)
    base = head = _rev(repo, "HEAD")
    rc = je.main(["route", "--design-dir", str(d), "--base", base,
                  "--head", head, "--repo", str(repo)])
    lines = capsys.readouterr().out.strip().splitlines()
    assert rc == 0
    assert lines[0] == "route: light"
    assert len(lines) == 2 and "skills/_shared/launch_design_run.py" in lines[1]


def test_cli_route_prints_only_the_route_line_when_eligible(tmp_path, repo, capsys):
    d = _design(tmp_path)
    base = head = _rev(repo, "HEAD")
    rc = je.main(["route", "--design-dir", str(d), "--base", base,
                  "--head", head, "--repo", str(repo)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "route: just-do-it"
