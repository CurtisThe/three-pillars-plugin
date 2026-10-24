"""Creation-side surfaces of the lean weight-class default (dev repo only).

design: weight-class-lean-default (task 1.6). The class is settled in `/tp-design` step 5b,
`/tp-promote` step 4b and `/tp-guide` step 7, and described in `weight-class.md`. These checks
read parsed structures only, as `test_weight_class_contracts.py` does: the command spans each step
shows (through `skill_spans`), the references (through `skill_refs`), and the behaviour of the
scripts those steps shell (`lighten`, `write_class`, `check_consistency`). No assert reads a
phrase out of the prose. The lean rubric itself is pinned by `test_weight_class_lean.py`; claims
that have only a wording to check (the printed class offered as the default answer, ties resolve
lighter, the pointer to the seed skill, `full` no longer called the default) are left to the prose.

Run with: pytest skills/_shared/test_weight_class_lean_prose.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parent
REPO_ROOT = SHARED.parents[1]
SKILLS = REPO_ROOT / "skills"
PROTOCOL_DOC = SHARED / "weight-class.md"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

# (skill, the number of the top-level step that settles the class)
STEPS = (("tp-design", "5b"), ("tp-promote", "4b"), ("tp-guide", "7"))
SEEDING_STEPS = (("tp-design", "5b"), ("tp-promote", "4b"))
_STEP_LINE = re.compile(r"^\d+[a-z]?\. ")


def _skill_md(skill: str) -> Path:
    return SKILLS / skill / "SKILL.md"


def _spans(path: Path, first: int = 0, last: int | None = None) -> list[tuple[str, bool]]:
    """`(span, shell)` for each code span of the file starting on a line in `[first, last)`."""
    skill_spans = pytest.importorskip("skill_spans")
    text = path.read_text(encoding="utf-8")
    return [(span, shell) for line, span, shell in skill_spans.code_spans(text)
            if line >= first and (last is None or line < last)]


def _step_spans(skill: str, label: str) -> list[tuple[str, bool]]:
    """The code spans of one top-level numbered step (from its line to the next step's)."""
    path = _skill_md(skill)
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    start = next(n for n, line in enumerate(lines, 1) if line.startswith(f"{label}. "))
    end = next((n for n, line in enumerate(lines, 1) if n > start and _STEP_LINE.match(line)),
               len(lines) + 1)
    return _spans(path, start, end)


def _tokens(spans: list[tuple[str, bool]]) -> list[list[str]]:
    skill_spans = pytest.importorskip("skill_spans")
    found = []
    for span, shell in spans:
        try:
            found.append(skill_spans.tokens_of(span, shell))
        except ValueError:  # a span that is not a shell command at all
            continue
    return found


def _weight_class_argvs(spans: list[tuple[str, bool]]) -> list[list[str]]:
    """The args of each `python3 <path>/weight_class.py args...` command among the spans."""
    return [t[2:] for t in _tokens(spans)
            if len(t) > 2 and t[0] == "python3" and t[1].endswith("/weight_class.py")]


def _assert_parse_with_own_argparse(argvs: list[list[str]], tmp_path) -> None:
    argparse_probe = pytest.importorskip("argparse_probe")
    for argv in argvs:
        # A value token is a placeholder (`…`, `{name}`) in the prose; argparse needs a value.
        filled = [tok if tok.startswith("--") or i == 0 else "low" for i, tok in enumerate(argv)]
        result = argparse_probe.probe(SHARED / "weight_class.py", filled, cache_dir=tmp_path)
        assert result["status"] == "parsed", (argv, result)


@pytest.mark.parametrize("skill,label", STEPS)
def test_class_step_shells_lighten_and_cost_with_the_script_own_flags(skill, label, tmp_path):
    """Each step that settles the class shows `weight_class.py lighten` and `weight_class.py
    cost`, and every `weight_class.py` command it shows parses with the script's own argparse."""
    argvs = _weight_class_argvs(_step_spans(skill, label))
    assert {"lighten", "cost"} <= {argv[0] for argv in argvs}
    _assert_parse_with_own_argparse(argvs, tmp_path)


@pytest.mark.parametrize("skill,label", SEEDING_STEPS)
def test_seeding_steps_stamp_the_settled_class_with_write_class(skill, label):
    """`/tp-design` 5b and `/tp-promote` 4b stamp the settled class onto seed.md through
    `write_class`: one of the step's code spans is that function."""
    names = {token for tokens in _tokens(_step_spans(skill, label)) for token in tokens}
    assert "write_class" in names


def test_protocol_doc_shows_lighten_and_cost_commands(tmp_path):
    argvs = _weight_class_argvs(_spans(PROTOCOL_DOC))
    assert {"lighten", "cost", "recommend"} <= {argv[0] for argv in argvs}
    _assert_parse_with_own_argparse(argvs, tmp_path)


def test_creation_side_references_resolve(tmp_path):
    """Every path, `/tp-*` skill and `python3` invocation the four edited files name resolves
    and parses (invariant 46's check, run in-suite)."""
    skill_refs = pytest.importorskip("skill_refs")
    files = [_skill_md(skill) for skill, _ in STEPS] + [PROTOCOL_DOC]
    assert skill_refs.check(REPO_ROOT, files, cache_dir=tmp_path).issues == []


# Axes the lean rubric maps to `light` (reversibility medium is a raised axis).
AXES = {"risk": "low", "blast_radius": "low", "reversibility": "medium", "novelty": "low"}
SEED_BODY = "# A seed\n\nProse with nothing in it for the scope scan to find.\n"


def _declared(path: Path) -> str | None:
    weight_class = pytest.importorskip("weight_class")
    return weight_class.parse_frontmatter(path.read_text(encoding="utf-8")).get("weight-class")


def _seed_dir(tmp_path, name: str, seed_class: str | None) -> Path:
    design_dir = tmp_path / name
    design_dir.mkdir()
    seed = design_dir / "seed.md"
    seed.write_text(SEED_BODY, encoding="utf-8")
    if seed_class is not None:
        pytest.importorskip("weight_class").write_class(seed, seed_class)
    return design_dir


def _settle(design_dir: Path, settled: str, *, stamp_seed: bool = True) -> None:
    """Steps 5b/4b then 7: stamp the settled class onto seed.md when it lacks one or differs,
    then write design.md with it."""
    weight_class = pytest.importorskip("weight_class")
    seed = design_dir / "seed.md"
    if stamp_seed and _declared(seed) != settled:
        weight_class.write_class(seed, settled)
    design = design_dir / "design.md"
    design.write_text("# A design\n", encoding="utf-8")
    weight_class.write_class(design, settled)


# (class on the seed, lighten's line, the operator's answer or None, the class settled)
SETTLE_CASES = [
    pytest.param("full", "suggest light", None, "light", id="accepted-suggestion"),
    pytest.param("light", "keep light", None, "light", id="kept-class"),
    pytest.param("light", "keep light", "full", "full", id="operator-override"),
    pytest.param(None, "suggest light", None, "light", id="seed-without-a-class"),
]


@pytest.mark.parametrize("seed_class,line_prefix,answer,settled", SETTLE_CASES)
def test_settled_class_stamped_on_seed_and_design_leaves_no_finding(
        tmp_path, seed_class, line_prefix, answer, settled):
    """A seed carrying a class is still scored (its class is a default, not a floor), and the
    class that is settled, whether the suggestion, the kept class or an override, is stamped on
    seed.md and design.md alike so `check_consistency` finds nothing."""
    weight_class = pytest.importorskip("weight_class")
    weight_lighten = pytest.importorskip("weight_lighten")
    design_dir = _seed_dir(tmp_path, "stamped", seed_class)
    line, rc = weight_lighten.lighten(design_dir, AXES)
    assert rc == 0 and line.startswith(line_prefix), line
    assert (answer or line.split()[1]) == settled
    _settle(design_dir, settled)
    assert _declared(design_dir / "seed.md") == _declared(design_dir / "design.md") == settled
    assert weight_class.check_consistency(design_dir) == []


@pytest.mark.parametrize("seed_class,line_prefix,answer,settled", SETTLE_CASES)
def test_skipping_the_seed_stamp_is_what_leaves_a_divergent_seed(
        tmp_path, seed_class, line_prefix, answer, settled):
    """The control: where the settled class differs from the seed's, only the seed stamp keeps
    `check_consistency` clean; without it seed.md is a finding."""
    weight_class = pytest.importorskip("weight_class")
    design_dir = _seed_dir(tmp_path, "unstamped", seed_class)
    _settle(design_dir, settled, stamp_seed=False)
    findings = weight_class.check_consistency(design_dir)
    if seed_class == settled:
        assert findings == []
    else:
        assert len(findings) == 1 and findings[0].startswith("seed.md:")
