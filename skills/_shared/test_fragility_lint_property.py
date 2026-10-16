"""test_fragility_lint_property.py — the fragility lint's property test, and one example per rule.

design: fragile-test-prevention (detailed-design-lint §Rule registry, §Scoping and exit codes)

The property (Hypothesis, `importorskip`ped inside the test so everything else here always
runs): a module built from a small AST grammar and `ast.unparse`d never makes `lint_source`
raise, and the same text with a syntax error appended makes `scan` exit 2. The examples pin
the property to the spec: one fixed flagged snippet per rule, and the set of ids that have a
snippet is compared with the ids read from `fragility_registry.RULES`, never a count.
"""
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

from fragility_lint import lint_source, main, scan
from fragility_registry import RULES

TEST_PATH = "skills/_shared/test_sample.py"
PROD_PATH = "skills/_shared/sample.py"
ALL_IDS = [rule.id for rule in RULES]
UNPARSEABLE = "def broken(:\n    pass\n"

# One flagged snippet per rule id. The path a snippet is linted at follows the rule's side.
EXAMPLES = {
    "golden-hash": (
        "import hashlib\nfrom pathlib import Path\n\n\ndef test_pin():\n"
        '    body = Path("hooks/x.sh").read_bytes()\n'
        '    assert hashlib.sha256(body).hexdigest() == "abc123"\n'),
    "shape-pin": (
        "import inspect\n\n\ndef test_src():\n"
        "    src = inspect.getsource(mod.f)\n"
        '    assert "secrets" in src\n'),
    "deny-literal": 'DENYLIST = {"a", "b"}\n',
    "name-kill": 'import subprocess\n\nsubprocess.run(["pkill", "-x", "claude"])\n',
    "md-read-assert": (
        "from pathlib import Path\n\n\ndef test_doc():\n"
        '    text = Path("guide.md").read_text(encoding="utf-8")\n'
        '    assert "step" in text\n'),
    "line-literal": "def test_line(node):\n    assert node.lineno == 7\n",
    "doc-line-cap": (
        "from pathlib import Path\n\n\ndef test_doc():\n"
        '    text = Path("guide.md").read_text(encoding="utf-8")\n'
        "    assert len(text.splitlines()) == 120\n"),
    "prose-regex": (
        "import re\nfrom pathlib import Path\n\nDOC = Path(\"skills/x/SKILL.md\")\n\n\n"
        "def headings():\n"
        '    text = DOC.read_text(encoding="utf-8")\n'
        '    return re.findall(r"^## (.+)$", text)\n'),
    "wall-clock": "import time\n\n\ndef test_wait():\n    time.sleep(1)\n",
}


def _path_for(rule) -> str:
    return TEST_PATH if rule.side == "test" else PROD_PATH


# --- the examples: always run ------------------------------------------------------------

def test_the_ids_with_an_example_are_the_registry_ids():
    assert set(EXAMPLES) == {rule.id for rule in RULES}


@pytest.mark.parametrize("rule", RULES, ids=[rule.id for rule in RULES])
def test_each_rule_flags_its_example(rule):
    hits = [h for h in lint_source(_path_for(rule), EXAMPLES[rule.id], ALL_IDS)
            if h.rule_id == rule.id]
    assert hits, f"no {rule.id} hit on its example"
    rows = range(1, len(EXAMPLES[rule.id].splitlines()) + 1)
    assert all(h.line in rows for h in hits)


@pytest.mark.parametrize("rule", RULES, ids=[rule.id for rule in RULES])
def test_an_example_gates_exactly_when_the_registry_says_so(rule):
    hits = [h for h in lint_source(_path_for(rule), EXAMPLES[rule.id])
            if h.rule_id == rule.id]
    assert hits and {h.gating for h in hits} == {rule.gating}


_ONE_SIDED = [rule for rule in RULES if rule.side != "any"]


@pytest.mark.parametrize("rule", _ONE_SIDED, ids=[rule.id for rule in _ONE_SIDED])
def test_an_example_is_not_flagged_on_the_other_side(rule):
    other = PROD_PATH if rule.side == "test" else TEST_PATH
    assert not [h for h in lint_source(other, EXAMPLES[rule.id], ALL_IDS)
                if h.rule_id == rule.id]


def test_scan_exits_2_on_unparseable_python(tmp_path, capsys):
    bad = tmp_path / "test_bad.py"
    bad.write_text(UNPARSEABLE, encoding="utf-8")
    result = scan([str(bad)])
    assert (result.exit, result.hits) == (2, [])
    assert [line.startswith(f"{bad.as_posix()}: ") for line in result.could_not_evaluate] == [True]
    assert main(["scan", str(bad)]) == 2
    assert f"could-not-evaluate: {bad.as_posix()}: " in capsys.readouterr().out


def test_scan_exits_0_on_the_same_file_once_it_parses(tmp_path):
    good = tmp_path / "test_good.py"
    good.write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    assert scan([str(good)]).exit == 0


# --- the property: needs Hypothesis ------------------------------------------------------

NAMES = ("text", "body", "src", "node", "mod", "path", "start", "elapsed", "DENY", "BLOCKED",
         "REGISTRY")
CALLEES = ("Path", "open", "hashlib.sha256", "inspect.getsource", "ast.parse", "ast.dump",
           "re.search", "re.findall", "re.compile", "time.time", "time.sleep", "len", "int",
           "set", "frozenset", "tuple", "list", "plan_tasks", "subprocess.run", "str")
ATTRS = ("read_text", "read_bytes", "hexdigest", "splitlines", "count", "startswith",
         "lineno", "end_lineno", "parent", "__file__", "search")
STRINGS = ("guide.md", "SKILL.md", "hooks/x.sh", "abc", "\n", "line", "# tp-allow-fragile: r")
COMPARES = (ast.Eq, ast.NotEq, ast.Lt, ast.GtE, ast.In, ast.NotIn, ast.Is)
IMPORTS = ("import hashlib", "import inspect", "import ast, re", "import time",
           "import subprocess", "from pathlib import Path", "from inspect import getsource as gs")
FUNC_TEMPLATES = ("def test_a():\n    pass", "def helper(text, body):\n    pass",
                  "def f(path, *, node=None):\n    pass", "async def test_b():\n    pass")
BREAKS = ("def (:", "x = (", "class :", "if x\n    pass", "return return", "a b c")


def _grammar(st):
    """A strategy for a Module node: assignments, asserts, calls, defs, ifs and classes over a
    small pool of names, callees and attributes that the rules look at."""
    load, store = ast.Load(), ast.Store()
    name = st.builds(ast.Name, st.sampled_from(NAMES), st.just(load))
    constant = st.builds(ast.Constant, st.one_of(
        st.integers(-3, 200), st.sampled_from(STRINGS), st.booleans(), st.floats(0, 5)))
    callee = st.sampled_from(CALLEES).map(lambda s: ast.parse(s, mode="eval").body)
    capture = st.just([ast.keyword("capture_output", ast.Constant(True))])

    def extend(inner):
        return st.one_of(
            st.builds(ast.Call, callee, st.lists(inner, max_size=2), st.just([])),
            st.builds(ast.Call, callee, st.lists(inner, max_size=1), capture),
            st.builds(ast.Attribute, inner, st.sampled_from(ATTRS), st.just(load)),
            st.builds(ast.Subscript, inner, st.builds(ast.Constant, st.sampled_from(STRINGS)),
                      st.just(load)),
            st.builds(lambda a, op, b: ast.Compare(a, [op()], [b]), inner,
                      st.sampled_from(COMPARES), inner),
            st.builds(lambda a, op, b: ast.BinOp(a, op(), b), inner,
                      st.sampled_from((ast.Sub, ast.Add, ast.Div)), inner),
            st.builds(ast.List, st.lists(inner, max_size=3), st.just(load)),
            st.builds(ast.Tuple, st.lists(inner, max_size=3), st.just(load)),
            st.builds(ast.Set, st.lists(inner, min_size=1, max_size=3)))

    expr = st.recursive(st.one_of(name, constant), extend, max_leaves=8)
    target = st.builds(ast.Name, st.sampled_from(NAMES), st.just(store))
    simple = st.one_of(
        st.builds(lambda t, e: ast.Assign([t], e), target, expr),
        st.builds(lambda t, e: ast.AnnAssign(t, ast.Name("object", load), e, 1), target, expr),
        st.builds(ast.Assert, expr),
        st.builds(ast.Expr, expr),
        st.sampled_from(IMPORTS).map(lambda s: ast.parse(s).body[0]))

    def compound(inner):
        body = st.lists(inner, min_size=1, max_size=3)

        def with_body(template, stmts):
            node = ast.parse(template).body[0]
            node.body = stmts
            return node

        return st.one_of(
            st.builds(with_body, st.sampled_from(FUNC_TEMPLATES), body),
            st.builds(with_body, st.just("class C:\n    pass"), body),
            st.builds(lambda t, b: ast.If(t, b, []), expr, body))

    stmts = st.recursive(simple, compound, max_leaves=10)
    return st.lists(stmts, max_size=6).map(lambda body: ast.Module(body, []))


def _source(module: ast.Module) -> str:
    return ast.unparse(ast.fix_missing_locations(module)) + "\n"


def test_lint_source_never_raises_on_generated_modules():
    hypothesis = pytest.importorskip("hypothesis")
    st = hypothesis.strategies
    known = set(ALL_IDS)

    @hypothesis.settings(
        max_examples=150, deadline=None, derandomize=True,
        suppress_health_check=[hypothesis.HealthCheck.too_slow,
                               hypothesis.HealthCheck.data_too_large])
    @hypothesis.given(_grammar(st))
    def check(module):
        text = _source(module)
        ast.parse(text)  # the grammar builds parseable modules; a failure here is its bug
        rows = range(1, len(text.splitlines()) + 1)
        for path in (TEST_PATH, PROD_PATH):
            for hit in lint_source(path, text, ALL_IDS):
                assert hit.rule_id in known and hit.line in rows
            assert lint_source(path, text) == lint_source(path, text)

    check()


def test_scan_exits_2_on_generated_modules_with_a_syntax_error():
    hypothesis = pytest.importorskip("hypothesis")
    st = hypothesis.strategies

    @hypothesis.settings(
        max_examples=40, deadline=None, derandomize=True,
        suppress_health_check=[hypothesis.HealthCheck.too_slow,
                               hypothesis.HealthCheck.data_too_large])
    @hypothesis.given(_grammar(st), st.sampled_from(BREAKS))
    def check(module, broken):
        text = _source(module) + broken + "\n"
        with pytest.raises((SyntaxError, ValueError)):
            ast.parse(text)  # the appended fragment is what makes it unparseable
        with tempfile.TemporaryDirectory() as root:
            bad = Path(root, "test_generated.py")
            bad.write_text(text, encoding="utf-8")
            result = scan([str(bad)])
        assert (result.exit, result.hits) == (2, [])
        assert len(result.could_not_evaluate) == 1

    check()
