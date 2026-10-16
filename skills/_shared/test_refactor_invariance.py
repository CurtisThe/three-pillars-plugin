"""test_refactor_invariance.py — `refactor_invariance.run` (Behavior 5; design:
fragile-test-prevention, detailed-design-stages.md Part C3).

Each case builds a real temp git repo holding a doc, a module and a few tests, then runs the
check over it with a real pytest runner. The scenario is the spec's: a test that pins the
doc's wrapping or its section order is over-specified under the transform that moves it; a
behavioural test of the same doc passes under both; a test red at baseline is skipped.
"""
from __future__ import annotations

import ast
import shlex
import subprocess
import sys
import tempfile

import pytest

import refactor_invariance as rv
import task_scope  # the shipped env scrub; git_env is dev-only

RUNNER = f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider"
IDENTITY = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test"}
NOTES = "three-pillars-docs/tp-designs/demo/notes.md"

DOC_LINES = [
    "# Guide",
    "",
    "## Intro",
    "",
    "This opening paragraph is written across several deliberately short lines,",
    "so that re-wrapping it at another width moves every line break and",
    "changes which text sits on each line.",
    "",
    "## Steps",
    "",
    "1. Install the tool.",
    "2. Run the tool.",
]
DOC = "\n".join(DOC_LINES) + "\n"

_READ_DOC = ("from pathlib import Path\n\n"
             "TEXT = (Path(__file__).parent / 'docs' / 'guide.md').read_text(encoding='utf-8')\n\n")
WRAP_SRC = _READ_DOC + ("def test_wrapping():\n"
                        f"    assert TEXT.splitlines()[5] == {DOC_LINES[5]!r}\n")
ORDER_SRC = _READ_DOC + (
    "def test_section_order():\n"
    "    heads = [ln for ln in TEXT.splitlines() if ln.startswith('## ')]\n"
    "    assert heads == ['## Intro', '## Steps']\n")
BEHAVIOUR_SRC = _READ_DOC + (
    "def test_steps_heading():\n"
    "    heads = [ln.lstrip('# ') for ln in TEXT.splitlines() if ln.startswith('#')]\n"
    "    assert 'Steps' in heads\n")
LIB_SRC = ("#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\"\"\"lib\"\"\"\n\n\n"
           "def double(x):\n    return   x*2   # a comment\n")
FILES = {
    "docs/guide.md": DOC, "lib.py": LIB_SRC, NOTES: DOC, "README.txt": "readme\n",
    "test_wrap.py": WRAP_SRC, "test_order.py": ORDER_SRC, "test_behaviour.py": BEHAVIOUR_SRC,
    "test_lib.py": "import lib\n\n\ndef test_double():\n    assert lib.double(2) == 4\n",
    "test_red.py": "def test_broken():\n    assert False\n",
    "test_extra.py": "def test_extra():\n    assert True\n",
}
WRAP, ORDER = "test_wrap.py::test_wrapping", "test_order.py::test_section_order"
BEHAVIOUR, LIB = "test_behaviour.py::test_steps_heading", "test_lib.py::test_double"
RED = "test_red.py::test_broken"
CHANGED = ["docs/guide.md", "lib.py", "test_wrap.py", "test_extra.py", NOTES]


def _git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=task_scope._git_env(**IDENTITY))
    return done.stdout


def _make_repo(base):
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for rel, text in FILES.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def _pairs(result):
    return {(item["node"], item["transform"]) for item in result["over_specified"]}


def _boom(text):
    raise ValueError("kaput")


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    repo = _make_repo(tmp_path_factory.mktemp("scenario"))
    targets = [WRAP, ORDER, BEHAVIOUR, LIB, RED]
    return rv.run(repo, targets, CHANGED, runner=RUNNER)


def test_wrapping_pin_is_over_specified_under_reflow(scenario):
    assert (WRAP, "md-reflow") in _pairs(scenario)


def test_section_order_pin_is_over_specified_under_reorder(scenario):
    assert (ORDER, "md-reorder") in _pairs(scenario)


def test_behavioural_tests_survive_every_transform(scenario):
    flagged = {node for node, _transform in _pairs(scenario)}
    assert {BEHAVIOUR, LIB}.isdisjoint(flagged)
    assert scenario["baseline"][BEHAVIOUR] == "pass"


def test_scenario_verdict_is_over_specified(scenario):
    assert scenario["verdict"] == "over-specified"


def test_red_at_baseline_node_is_skipped_and_never_flagged(scenario):
    assert {"node": RED, "reason": "red at baseline"} in scenario["skipped"]
    assert RED not in {node for node, _transform in _pairs(scenario)}


def test_targets_files_and_design_dir_are_never_transformed(scenario):
    assert scenario["transformed"] == {
        "md-reflow": ["docs/guide.md"], "md-reorder": ["docs/guide.md"],
        "py-unparse": ["lib.py"]}


def test_behavioural_test_alone_is_clean(tmp_path):
    result = rv.run(_make_repo(tmp_path), [BEHAVIOUR], ["docs/guide.md"], runner=RUNNER)
    assert (result["verdict"], result["over_specified"]) == ("clean", [])


@pytest.mark.parametrize("changed", [["test_behaviour.py"], [NOTES], ["README.txt"]],
                         ids=["targets-file", "design-dir", "wrong-suffix"])
def test_transform_with_no_eligible_file_is_skipped(tmp_path, changed):
    result = rv.run(_make_repo(tmp_path), [BEHAVIOUR], changed, runner=RUNNER)
    assert result["verdict"] == "clean"
    assert {s["transform"] for s in result["skipped"]} == set(rv.REGISTRY)
    assert result["transformed"] == {}


def test_transform_that_changes_nothing_is_skipped(tmp_path):
    noop = {"noop": rv.Transform(".md", lambda text: text)}
    result = rv.run(_make_repo(tmp_path), [BEHAVIOUR], ["docs/guide.md"], runner=RUNNER,
                    transforms=noop)
    assert result["verdict"] == "clean"
    assert [s["transform"] for s in result["skipped"]] == ["noop"]


def test_no_targets_is_clean_with_nothing_judged(tmp_path):
    result = rv.run(_make_repo(tmp_path), [], ["docs/guide.md"], runner=RUNNER)
    assert (result["verdict"], result["baseline"]) == ("clean", {})


def test_transform_that_raises_is_could_not_evaluate_naming_the_file(tmp_path):
    result = rv.run(_make_repo(tmp_path), [BEHAVIOUR], ["docs/guide.md"], runner=RUNNER,
                    transforms={"boom": rv.Transform(".md", _boom)})
    assert result["verdict"] == "could-not-evaluate"
    assert [(e["transform"], e["file"]) for e in result["errors"]] == [("boom", "docs/guide.md")]
    assert "docs/guide.md" in result["reason"]


@pytest.mark.parametrize("runner", [None, "", "  "], ids=["none", "empty", "blank"])
def test_no_runner_is_could_not_evaluate(tmp_path, runner):
    result = rv.run(_make_repo(tmp_path), [BEHAVIOUR], ["docs/guide.md"], runner=runner)
    assert result["verdict"] == "could-not-evaluate"


def test_a_root_that_is_not_a_repo_is_could_not_evaluate(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = rv.run(plain, [BEHAVIOUR], ["docs/guide.md"], runner=RUNNER)
    assert result["verdict"] == "could-not-evaluate"


# (targets, runner, transforms, expected verdict): one row per way out of `run`.
_EXITS = [
    ([BEHAVIOUR], RUNNER, None, "clean"),
    ([WRAP], RUNNER, None, "over-specified"),
    ([BEHAVIOUR], RUNNER, {"boom": rv.Transform(".md", _boom)}, "could-not-evaluate"),
    ([BEHAVIOUR], "no-such-runner-binary-xyz", None, "could-not-evaluate"),
]


@pytest.mark.parametrize("targets,runner,transforms,verdict", _EXITS,
                         ids=["clean", "over-specified", "transform-raised", "runner-broken"])
def test_scratch_worktree_is_gone_on_every_path(tmp_path, monkeypatch, targets, runner,
                                                transforms, verdict):
    repo = _make_repo(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    kwargs = {} if transforms is None else {"transforms": transforms}
    result = rv.run(repo, targets, ["docs/guide.md"], runner=runner, **kwargs)
    assert result["verdict"] == verdict
    listing = _git(repo, "worktree", "list", "--porcelain").splitlines()
    assert len([line for line in listing if line.startswith("worktree ")]) == 1
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("src,kept", [
    ("#!/usr/bin/env python3\n# -*- coding: latin-1 -*-\nx  =  1  # note\n", 2),
    ("# -*- coding: latin-1 -*-\nx  =  1\n", 1),
    ("x  =  1  # note\n", 0),
], ids=["shebang-and-coding", "coding-only", "neither"])
def test_py_unparse_keeps_shebang_and_encoding_lines(src, kept):
    out = rv.REGISTRY["py-unparse"].apply(src)
    assert out.splitlines()[:kept] == src.splitlines()[:kept]
    assert ast.dump(ast.parse(out)) == ast.dump(ast.parse(src))
