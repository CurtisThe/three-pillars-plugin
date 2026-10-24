"""lighten reads a legacy design.md's `## Scope` before the seed's spans."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from weight_lighten import lighten  # noqa: E402

LOW = dict(risk="low", blast_radius="low", reversibility="high", novelty="low")
GATE = "`skills/_shared/merge_gate.py`"
PLAIN = "`docs/x.md`"


def _write(tmp_path, design=None, seed=None):
    if design is not None:
        (tmp_path / "design.md").write_text(design)
    if seed is not None:
        (tmp_path / "seed.md").write_text(f"---\nweight-class: full\n---\n{seed}\n")
    return tmp_path


def _scope(path):
    return f"# D\n\n## Scope\n- {path}\n"


def test_design_scope_gate_path_beats_plain_seed(tmp_path):
    line, rc = lighten(_write(tmp_path, _scope(GATE), PLAIN), LOW)
    assert rc == 0 and line.startswith("suggest light because ")


def test_design_scope_plain_path_allows_just_do_it(tmp_path):
    line, rc = lighten(_write(tmp_path, _scope(PLAIN), PLAIN), LOW)
    assert rc == 0 and line.startswith("suggest just-do-it")


def test_scope_without_paths_falls_back_to_seed(tmp_path):
    design = "# D\n\n## Scope\nNothing named here.\n"
    line, rc = lighten(_write(tmp_path, design, GATE), LOW)
    assert rc == 0 and line.startswith("suggest light")


def test_no_scope_heading_falls_back_to_seed(tmp_path):
    line, rc = lighten(_write(tmp_path, "# D\n\nbody\n", GATE), LOW)
    assert rc == 0 and line.startswith("suggest light")


def test_seed_only_gate_path_suggests_light(tmp_path):
    line, rc = lighten(_write(tmp_path, seed=GATE), LOW)
    assert rc == 0 and line.startswith("suggest light")


def test_seed_only_plain_path_suggests_just_do_it(tmp_path):
    line, rc = lighten(_write(tmp_path, seed=PLAIN), LOW)
    assert rc == 0 and line.startswith("suggest just-do-it")


def test_plain_scope_path_does_not_hide_seed_gate_path(tmp_path):
    line, rc = lighten(_write(tmp_path, _scope(PLAIN), GATE), LOW)
    assert rc == 0 and line.startswith("suggest light")
