"""Tests for weight_lighten.lighten and the `weight_class.py lighten` CLI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from weight_class import main  # noqa: E402
from weight_lighten import lighten  # noqa: E402

LIGHT = dict(risk="medium", blast_radius="low", reversibility="high", novelty="low")
HEAVY = dict(risk="high", blast_radius="low", reversibility="high", novelty="low")
SPIKE = dict(risk="low", blast_radius="low", reversibility="high", novelty="high")


def _design(tmp_path, klass=None, extra="", scope="`docs/x.md`"):
    fm = "---\n" + (f"weight-class: {klass}\n" if klass else "") + extra + "---\n"
    (tmp_path / "design.md").write_text(f"{fm}# D\n\n## Scope\n{scope}\n")
    return tmp_path


def _seed(tmp_path, klass=None, body="touches `docs/x.md`", extra=""):
    fm = "---\n" + (f"weight-class: {klass}\n" if klass else "") + extra + "---\n"
    (tmp_path / "seed.md").write_text(f"{fm}{body}\n")
    return tmp_path


def test_design_full_light_rubric_suggests_light(tmp_path):
    line, rc = lighten(_design(tmp_path, "full"), LIGHT)
    assert rc == 0 and line.startswith("suggest light because ")


def test_design_light_keeps(tmp_path):
    assert lighten(_design(tmp_path, "light"), LIGHT) == ("keep light", 0)


def test_heavier_rubric_never_raises_design(tmp_path):
    assert lighten(_design(tmp_path, "light"), HEAVY) == ("keep light", 0)


def test_seed_class_is_default_not_floor(tmp_path):
    line, rc = lighten(_seed(tmp_path, "light"), HEAVY)
    assert (line, rc) == ("suggest full because risk", 0)


def test_spike_rubric_keeps_declared(tmp_path):
    assert lighten(_design(tmp_path, "full"), SPIKE) == ("keep full", 0)


def test_declared_spike_kept(tmp_path):
    assert lighten(_design(tmp_path, "spike"), LIGHT) == ("keep spike", 0)


def test_pin_class_keeps(tmp_path):
    d = _design(tmp_path, "full", extra="pin-class: true\n")
    assert lighten(d, LIGHT) == ("keep full", 0)


def test_gate_path_in_seed_floors_at_light(tmp_path):
    low = dict(risk="low", blast_radius="low", reversibility="high", novelty="low")
    d = _seed(tmp_path, "full", body="edit `skills/_shared/merge_gate.py`")
    line, rc = lighten(d, low)
    assert rc == 0 and line.startswith("suggest light because ")


def test_no_gate_path_allows_just_do_it(tmp_path):
    low = dict(risk="low", blast_radius="low", reversibility="high", novelty="low")
    line, _ = lighten(_seed(tmp_path, "full"), low)
    assert line.startswith("suggest just-do-it")


def test_empty_dir_keeps_full(tmp_path):
    assert lighten(tmp_path, HEAVY) == ("keep full", 0)


def test_axes_from_frontmatter(tmp_path):
    d = _seed(tmp_path, "full", extra=(
        "risk: medium\nblast-radius: low\nreversibility: high\nnovelty: low\n"))
    line, rc = lighten(d, {})
    assert rc == 0 and line.startswith("suggest light")


def test_need_axes(tmp_path):
    assert lighten(tmp_path, {}) == ("need-axes", 2)


def test_bad_axis_flag_and_frontmatter(tmp_path):
    assert lighten(tmp_path, dict(LIGHT, risk="hgih")) == ("bad-axis risk", 2)
    d = _seed(tmp_path, "full", extra="risk: hgih\n")
    assert lighten(d, {"blast_radius": "low"}) == ("bad-axis risk", 2)


def test_cli(tmp_path, capsys):
    d = _design(tmp_path, "full")
    rc = main(["lighten", str(d), "--risk", "medium", "--blast-radius", "low",
               "--reversibility", "high", "--novelty", "low"])
    assert rc == 0 and capsys.readouterr().out.startswith("suggest light because")
    assert main(["lighten", str(d)]) == 2
    assert capsys.readouterr().out.strip() == "need-axes"
