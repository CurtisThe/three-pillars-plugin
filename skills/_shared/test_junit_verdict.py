"""test_junit_verdict.py — the strict junit parser and the per-node target verdict.

design: local-implement-and-review (PR #165 rulings, amendments A29, A30)

Synthetic reports over a real tmp tree pin the parser's strictness, the rootdir
resolution and the file-attribute matching rules; one real pytest run (plain and under
xdist) pins that `report_args` yields that shape. Real repo layouts (a re-collecting
module, a package-level ``pytest.ini``, an addopts deselect) are in
`test_junit_verdict_layouts.py`.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import junit_verdict as jv


def _report(tmp_path, body: str, root: str = "testsuites"):
    path = tmp_path / "r.xml"
    path.write_text(f'<?xml version="1.0"?><{root}><testsuite>{body}</testsuite></{root}>')
    return path


def _case(classname, name, file="t/test_a.py", outcome=""):
    attrs = f'classname="{classname}" name="{name}"' + (f' file="{file}"' if file else "")
    return f"<testcase {attrs}>{outcome}</testcase>"


def _tree(root, *files):
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("")
    return root


def _nodes(tmp_path, body, targets=("t/test_a.py",)):
    nodes, why = jv.resolve(jv.parse(_report(tmp_path, body)), list(targets), tmp_path)
    assert why == "", why
    return nodes


FAIL, ERR, SKIP = '<failure message="x"/>', '<error message="x"/>', '<skipped message="s"/>'
FILES = ("t/test_a.py", "t/test_b.py", "t/test_c.py", "t/test_d.py", "t/test_e.py",
         "t/base.py")


@pytest.mark.parametrize("text", [None, "", "not <xml", "<html/>",
                                  '<!DOCTYPE x [<!ENTITY a "b">]><testsuites/>',
                                  '<testsuites><testcase name="t"/></testsuites>'])
def test_missing_or_malformed_report_is_none(tmp_path, text):
    path = tmp_path / "r.xml"
    if text is not None:
        path.write_text(text)
    _tree(tmp_path, "t/test_a.py")
    assert jv.parse(path) is None
    assert jv.verdict(jv.parse(path), ["t/test_a.py::test_x"], tmp_path) == (
        "unverified", "no-report")


def test_node_ids_from_file_and_classname_within_it(tmp_path):
    _tree(tmp_path, *FILES)
    nodes = _nodes(tmp_path, "".join([
        _case("t.test_a", "test_x[1-2]"), _case("t.test_a.TestK.TestIn", "test_m"),
        _case("", "t.test_a", outcome=ERR),  # the module's collection error
        _case("t.base", "test_inh"),  # classname is not its file's module: foreign
        _case("t.test_b", "test_imp"),  # collected from test_b, defined in test_a
        _case("t.test_a", "test_y", file=None)]))
    assert nodes == [("t/test_a.py::test_x[1-2]", "passed"),
                     ("t/test_a.py::TestK::TestIn::test_m", "passed"),
                     ("t/test_a.py", "failed"), (None, "passed"), (None, "passed"),
                     (None, "passed")]


def test_a_module_segment_is_never_a_class_segment(tmp_path):
    """``t/test_a.py`` beside a ``t/test_a/`` package: ``t.test_a.test_b`` names the
    module ``t/test_a/test_b.py``, so a case it re-collects from test_a is foreign."""
    _tree(tmp_path, "t/test_a.py", "t/test_a/test_b.py")
    nodes = _nodes(tmp_path, _case("t.test_a.test_b", "test_shared")
                   + _case("t.test_a.TestK", "test_m"))
    assert nodes == [(None, "passed"), ("t/test_a.py::TestK::test_m", "passed")]


@pytest.mark.parametrize("target, want", [
    ("t/test_a.py::test_x", ("red", "red")),  # holds every parametrization
    ("t/test_a.py::test_x[2]", ("red", "red")),  # a param id matches exactly
    ("t/test_a.py::test_x[1]", ("pass", "")),
    ("t/test_a.py::test_xy", ("unverified", "node-absent")),  # never a name prefix
    ("t/test_a.py::TestK", ("unverified", "skipped")),  # a class holds its methods
    ("t/test_a.py::TestK::test_m", ("pass", "")),
    ("./t//test_a.py::TestK::test_m", ("pass", "")),  # a target path is normalised
    ("t/test_a.py", ("red", "red")),
    ("t/test_b.py", ("pass", "")),  # a pass beside a skip
    ("t/test_c.py", ("unverified", "skipped")),  # skips only: never a pass
    ("t/test_d.py", ("unverified", "file-no-tests")),  # maybe deselected: never case f
    ("t/test_e.py::test_q", ("red", "collection-error")),  # only its collector failed
    ("t/test_e.py", ("red", "collection-error")),
])
def test_judge(tmp_path, target, want):
    _tree(tmp_path, *FILES)
    nodes = _nodes(tmp_path, "".join([
        _case("t.test_a", "test_x[1]"), _case("t.test_a", "test_x[2]", outcome=FAIL),
        _case("t.test_a.TestK", "test_m"), _case("t.test_a.TestK", "test_n", outcome=SKIP),
        _case("t.test_b", "test_p", "t/test_b.py"),
        _case("t.test_b", "test_s", "t/test_b.py", SKIP),
        _case("t.test_c", "test_s", "t/test_c.py", SKIP),
        _case("", "t.test_e", "t/test_e.py", ERR)]))
    assert jv.judge(nodes, target) == want
    assert jv.judge(nodes, target, exists=False) == ("missing", "file-missing")


def test_verdict_order_and_foreign_failure(tmp_path):
    _tree(tmp_path, *FILES)
    cases = jv.parse(_report(tmp_path, "".join([
        _case("t.test_a", "test_ok"), _case("t.test_a", "test_red", outcome=FAIL),
        _case("t.base", "test_inh", outcome=FAIL)])))
    # an absent node never hides a red target beside it, in either order
    for targets in (["t/test_a.py::test_gone", "t/test_a.py::test_red"],
                    ["t/test_a.py::test_red", "t/test_a.py::test_gone"]):
        assert jv.verdict(cases, targets, tmp_path) == ("red", "red")
    assert jv.verdict(cases[:1], ["t/test_a.py::test_ok", "t/test_a.py::test_gone"],
                      tmp_path) == ("unverified", "node-absent")
    # a declared file missing from the tree is the one case-f "missing"
    assert jv.verdict(cases, ["t/test_a.py::test_red", "t/test_zz.py"], tmp_path) == (
        "missing", "file-missing")
    assert jv.verdict(None, ["t/test_zz.py::test_q"], tmp_path) == (
        "missing", "file-missing")
    # a failure no declared target owns (defined in another file) blocks the pass
    assert jv.verdict(cases, ["t/test_a.py::test_ok"], tmp_path) == (
        "unverified", "foreign-failure")
    assert jv.verdict(cases, [], tmp_path) == ("unverified", "no-targets")


def test_rootdir_is_the_one_the_report_fits(tmp_path):
    """``file`` is relative to pytest's rootdir: a package rootdir resolves; a report
    no candidate fits, or that two candidates place differently, is unverified."""
    _tree(tmp_path, "pkg/tests/test_a.py")
    body = _case("tests.test_a", "test_ok", "tests/test_a.py")
    cases = jv.parse(_report(tmp_path, body))
    assert jv.verdict(cases, ["pkg/tests/test_a.py::test_ok"], tmp_path) == ("pass", "")
    stray = jv.parse(_report(tmp_path, body + _case("x.test_q", "test_q", "x/test_q.py")))
    assert jv.verdict(stray, ["pkg/tests/test_a.py::test_ok"], tmp_path) == (
        "unverified", "rootdir-unknown")
    _tree(tmp_path, "tests/test_a.py")  # now the repo root fits the report too
    assert jv.verdict(cases, ["pkg/tests/test_a.py::test_ok"], tmp_path) == (
        "unverified", "rootdir-ambiguous")


@pytest.mark.parametrize("extra", [[], ["-n", "2"]])
def test_real_report_shape(tmp_path, extra):
    """`report_args` after the targets yields ``file`` + module classnames under the
    rootdir pytest picks (no ini here), plain and under xdist."""
    if extra:
        pytest.importorskip("xdist")
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "test_a.py").write_text(
        "import pytest\n\n@pytest.mark.parametrize('v', [1, 2])\ndef test_x(v):\n"
        "    assert v == 1\n\nclass TestK:\n    def test_m(self):\n        pass\n")
    report = tmp_path / "out" / "r.xml"
    targets = ["t/test_a.py::test_x", "t/test_a.py::TestK::test_m"]
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *extra,
                    *targets, *jv.report_args(str(report))], cwd=tmp_path,
                   capture_output=True, check=False)
    nodes, why = jv.resolve(jv.parse(report), targets, tmp_path)
    assert why == ""
    assert jv.judge(nodes, targets[0]) == ("red", "red")
    assert jv.judge(nodes, "t/test_a.py::test_x[1]") == ("pass", "")
    assert jv.judge(nodes, targets[1]) == ("pass", "")
