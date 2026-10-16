"""test_fragility_rules_gating.py — the three day-one gating fragility rules.

design: fragile-test-prevention (detailed-design-lint §Rule registry, §Measured)

Every case is a source string parsed here: a line ending in `# HIT` must be
reported by the rule under test and no other line may be; a source with no marker
is a counter-example that passes. This repo's real idioms are rebuilt as strings,
never read from a live file. `golden-hash` and `shape-pin` fire only on test
files, `deny-literal` only on production files. The tables are checked against
the registry's gating family, never a hard-coded count.
"""
from __future__ import annotations

import ast

import pytest

from fragility_registry import RULES
from fragility_rules_gating import FILTER_NAME_TOKENS, VISITORS, name_tokens, visit

TEST_PATH = "skills/_shared/test_sample.py"
PROD_PATH = "skills/_shared/sample.py"

# --- golden-hash: (name, source). Imports are left out unless the case turns on them. ---
GOLDEN_HASH = [
    ("digest of a read vs a string constant", """\
def test_pin():
    body = Path("hooks/x.sh").read_bytes()
    assert hashlib.sha256(body).hexdigest() == "abc123"  # HIT
"""),
    ("the constant on the left", """\
def test_pin():
    assert "abc123" == hashlib.sha256(Path("a.bin").read_bytes()).hexdigest()  # HIT
"""),
    ("vs a name bound to a constant", """\
EXPECTED = "abc123"

def test_pin():
    text = Path("a.txt").read_text(encoding="utf-8")
    assert hashlib.md5(text.encode()).hexdigest() == EXPECTED  # HIT
"""),
    ("vs an attribute of an imported module", """\
import pinned

def test_pin():
    assert hashlib.sha256(Path("a").read_bytes()).hexdigest() == pinned.SHA  # HIT
"""),
    ("vs a name imported from another module", """\
from pinned import SHA

def test_pin():
    assert hashlib.sha256(Path("a").read_bytes()).digest() == SHA  # HIT
"""),
    ("open().read() traced through a with-bound name", """\
def test_pin():
    with open("a.bin", "rb") as fh:
        data = fh.read()
    assert hashlib.sha1(data).hexdigest() == "abc"  # HIT
"""),
    ("the digest held in a name", """\
PINNED = "abc"

def test_pin():
    digest = hashlib.sha256(Path("a").read_bytes()).hexdigest()
    assert digest == PINNED  # HIT
"""),
    ("a from-imported hash constructor", """\
from hashlib import sha256

def test_pin():
    assert sha256(Path("a").read_bytes()).hexdigest() == "abc"  # HIT
"""),
    ("a read at module level, the assert in a test", """\
BODY = Path("a").read_bytes()

def test_pin():
    assert hashlib.sha256(BODY).hexdigest() == "abc"  # HIT
"""),
    ("real idiom: test_commit_guard.py sha pin", """\
import hashlib
from pathlib import Path

def test_tp_commit_guard_sh_sha_pinned_to_body_sha256(tmp_path):
    from skills._shared import commit_guard
    import skills._shared.commit_guard_settings as settings
    body = (Path(__file__).resolve().parent / "hooks" / "tp-commit-guard.sh").read_bytes()
    assert hashlib.sha256(body).hexdigest() == commit_guard.BODY_SHA256  # HIT
    assert settings.DENY_RULES
"""),
    ("known-answer vector over bytes the test states", """\
def test_vector():
    assert hashlib.sha256(b"abc").hexdigest() == "ba7816bf8f01cfea"
"""),
    ("stated bytes held in a name", """\
def test_vector():
    data = b"abc"
    assert hashlib.sha256(data).hexdigest() == "ba7816bf8f01cfea"
"""),
    ("h(x) == h(x)", """\
def h(data):
    return hashlib.sha256(data).hexdigest()

def test_stable():
    x = b"stated"
    assert h(x) == h(x)
"""),
    ("both sides computed from reads", """\
def test_same(a, b):
    left = hashlib.sha256(Path(a).read_bytes()).hexdigest()
    assert left == hashlib.sha256(Path(b).read_bytes()).hexdigest()
"""),
    ("vs a value the test computes", """\
def test_pin():
    expected = hashlib.sha256(b"x").hexdigest()
    assert hashlib.sha256(Path("a").read_bytes()).hexdigest() == expected
"""),
    ("a read in another function does not leak", """\
def helper():
    body = Path("a").read_bytes()
    return body

def test_vector():
    body = b"abc"
    assert hashlib.sha256(body).hexdigest() == "ba7816bf8f01cfea"
"""),
    ("a parameter shadows a module-level read", """\
body = Path("a").read_bytes()

def test_vector(body):
    assert hashlib.sha256(body).hexdigest() == "ba7816bf8f01cfea"
"""),
]

# --- shape-pin ---------------------------------------------------------------------
SHAPE_PIN = [
    ("inspect.getsource", """\
def test_src():
    src = inspect.getsource(mod.f)  # HIT
    assert "secrets" in src
"""),
    ("inspect.getsourcelines", """\
def test_src():
    lines, _ = inspect.getsourcelines(mod.f)  # HIT
    assert lines
"""),
    ("getsource imported by name and aliased", """\
from inspect import getsource as gs

def test_src():
    assert "x" in gs(mod.f)  # HIT
"""),
    ("real idiom: serve_write getsource then ast.parse", """\
import ast
import inspect

def test_mint_nonce_uses_secrets_not_random():
    src = inspect.getsource(serve_write.mint_nonce)  # HIT
    assert "secrets.token_urlsafe" in src
    tree = ast.parse(src)  # HIT
"""),
    ("ast.dump of a parse of getsource, through names", """\
def test_shape():
    src = textwrap.dedent(inspect.getsource(mod.f))  # HIT
    tree = ast.parse(src)  # HIT
    assert ast.dump(tree)  # HIT
"""),
    ("ast.parse of a .py read", """\
def test_shape():
    tree = ast.parse(Path("pkg/mod.py").read_text(encoding="utf-8"))  # HIT
"""),
    ("real idiom: a read of Path(mod.__file__)", """\
def _import_block_names():
    tree = ast.parse(Path(review_merge.__file__).read_text(encoding="utf-8"))  # HIT
    return tree
"""),
    ("real idiom: a module-level HERE / 'x.py'", """\
HERE = Path(__file__).resolve().parent

def test_no_import():
    tree = ast.parse((HERE / "attempt_watchdog.py").read_text(encoding="utf-8"))  # HIT
"""),
    ("ast.parse of open().read() of a .py path", """\
def test_shape():
    with open("pkg/mod.py", encoding="utf-8") as fh:
        text = fh.read()
    ast.parse(text)  # HIT
"""),
    ("ast.parse of a string constant and of fixture code the test writes", """\
CODE = "def f():\\n    return 1\\n"

def test_fixture():
    code = textwrap.dedent('''
        import os
        os.getcwd()
    ''')
    assert ast.parse(code) and ast.parse(CODE) and ast.dump(ast.parse("y = 2"))
"""),
    ("a read of a non-py sibling of a module file", """\
def test_shape():
    text = (Path(mod.__file__).parent / "data.txt").read_text(encoding="utf-8")
    ast.parse(text)
"""),
    ("import-boundary helper over a path parameter", """\
def _top_level_imports(source):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    return [n for n in tree.body if isinstance(n, ast.Import)]
"""),
]

# --- deny-literal (production files) ----------------------------------------------
DENY_LITERAL = [
    ("a set literal", 'DENYLIST = {"a", "b"}  # HIT\n'),
    ("a tuple literal", 'DENY = ("a",)  # HIT\n'),
    ("a list literal", 'BLOCKED = ["a", "b"]  # HIT\n'),
    ("frozenset of a literal", 'REJECT = frozenset({"a"})  # HIT\n'),
    ("tuple of a list literal", 'BLOCK_LIST = tuple(["a"])  # HIT\n'),
    ("set of a tuple literal", 'REJECTED = set(("a", "b"))  # HIT\n'),
    ("an annotated assignment", 'DENY: frozenset = frozenset({"a"})  # HIT\n'),
    ("an annotated list", 'BLOCKLIST: list[str] = ["x"]  # HIT\n'),
    ("a camelCase name", 'denyList = ["x"]  # HIT\nblockedNames = {"y"}  # HIT\n'),
    ("a class attribute", 'class C:\n    REJECTED_NAMES = ("a",)  # HIT\n'),
    ("a local in a function", 'def f():\n    deny = {"a"}  # HIT\n    return deny\n'),
    ("a literal whose first element is not a constant", 'DENY = [f(), "a"]  # HIT\n'),
    ("ALLOWED = frozenset(REGISTRY)", "ALLOWED = frozenset(REGISTRY)\n"),
    ("BLOCKING_CLASSES", 'BLOCKING_CLASSES = ("high", "critical")\n'),
    ("NON_BLOCKING", 'NON_BLOCKING = {"low"}\nBLOCKER = ["x"]\n'),
    ("a filter name derived from a registry", "DENYLIST = frozenset(REG)\nBLOCK = set(NAMES)\n"),
    ("a filter name bound to a comprehension", "BLOCK = {n for n in REGISTRY}\n"),
    ("an empty or all-computed collection", "DENY = ()\nREJECT = frozenset()\nDENIED = [f()]\n"),
    ("a non-filter name bound to a literal", 'ALLOWED = frozenset({"a"})\nNAMES = ("a",)\n'),
    ("a filter name bound to a plain string", 'DENY_MESSAGE = "no"\n'),
]

TABLES = {
    "golden-hash": (TEST_PATH, GOLDEN_HASH),
    "shape-pin": (TEST_PATH, SHAPE_PIN),
    "deny-literal": (PROD_PATH, DENY_LITERAL),
}
ROWS = [pytest.param(rule, path, src, id=f"{rule}: {name}")
        for rule, (path, cases) in TABLES.items() for name, src in cases]


def _marked(src: str) -> list[int]:
    return [n for n, line in enumerate(src.splitlines(), 1) if line.endswith("# HIT")]


def _hits(src: str, path: str, rule_id: str) -> list[int]:
    return [f.line for f in visit(ast.parse(src), path, None) if f.rule_id == rule_id]


@pytest.mark.parametrize("rule_id, path, src", ROWS)
def test_each_example_is_flagged_and_each_counter_example_passes(rule_id, path, src):
    assert _hits(src, path, rule_id) == _marked(src)


def test_the_tables_cover_exactly_the_gating_family_of_the_registry():
    gating_ids = {rule.id for rule in RULES if rule.family == "gating"}
    # side-`any` rules keep their table in their own module (test_fragility_name_kill.py)
    assert set(TABLES) == {rule.id for rule in RULES
                           if rule.family == "gating" and rule.side != "any"}
    assert set(VISITORS) == gating_ids
    for rule_id, (_, cases) in TABLES.items():
        assert any(_marked(src) for _, src in cases), f"{rule_id} has no flagged example"
        assert any(not _marked(src) for _, src in cases), f"{rule_id} has no counter-example"


@pytest.mark.parametrize("rule_id, path, src", [
    pytest.param(rule, other, src, id=f"{rule}: {name}")
    for rule, (path, cases) in TABLES.items()
    for name, src in cases if _marked(src)
    for other in ([PROD_PATH] if path == TEST_PATH else [TEST_PATH, "skills/_shared/conftest.py"])
])
def test_a_rule_fires_only_on_the_side_the_registry_gives_it(rule_id, path, src):
    assert _hits(src, path, rule_id) == []


def test_conftest_counts_as_a_test_file_for_the_test_side_rules():
    src = GOLDEN_HASH[0][1]
    assert _hits(src, "skills/_shared/conftest.py", "golden-hash") == _marked(src)


@pytest.mark.parametrize("name, tokens", [
    ("DENYLIST", ["DENYLIST"]), ("DENY_LIST", ["DENY", "LIST"]), ("denyList", ["DENY", "LIST"]),
    ("blockedNames", ["BLOCKED", "NAMES"]), ("NON_BLOCKING", ["NON", "BLOCKING"]),
    ("_deny_", ["DENY"]), ("BlockList", ["BLOCK", "LIST"]),
])
def test_names_split_on_underscores_and_lower_to_upper_changes(name, tokens):
    assert name_tokens(name) == tokens


def test_severity_names_are_not_filter_tokens():
    assert {"DENY", "BLOCK", "REJECT"} <= set(FILTER_NAME_TOKENS)
    assert not {"BLOCKING", "BLOCKER", "NON"} & set(FILTER_NAME_TOKENS)


def test_findings_are_sorted_by_line_and_carry_the_statement_span():
    src = 'BLOCK = [\n    "a",\n]\nDENY = ("b",)\n'
    found = visit(ast.parse(src), PROD_PATH, None)
    assert [(f.rule_id, f.line, f.end_line) for f in found] == [
        ("deny-literal", 1, 3), ("deny-literal", 4, 4)]
