"""The hermeticity sweep's AST PREDICATES, and their own unit tests.

``test_resolve_script_hermeticity.py`` owns the two RUNTIME properties (the
autouse ``$CLAUDE_PLUGIN_ROOT`` fixture really strips the variable; omitting
``self_root=`` really does resolve the live checkout) and the structural
meta-test that applies these predicates to the whole suite. This module owns
the predicates themselves and pins them DIRECTLY against known evaders.

Split out at PR #144 R1 for two reasons. The sizing one: the hermeticity module
was at 415 lines against a 500-line hard cap and R1's fix plus its coverage did
not fit. The real one: "does every call site opt out of the ambient roots" and
"is the predicate that decides that evadable" are different questions, and the
second had NO direct coverage at all. ``_bare_references`` got three unit tests;
the ambient-env exemption shipped with zero, and duly grew a third recurrence of
the D3 failure inside itself.

Each predicate here is exercised against three shapes: a POSITIVE case (the
legitimate pattern that must keep working), a NEGATIVE CONTROL (the shape that
must be flagged, proving the predicate is not vacuous), and an EVADER (a
mutant-verified way a previous spelling was walked past in silence).

The ambient-env exemption is no longer INFERRED: four successive rules that
read the source for a ``setenv`` were each walked past, so it is now an
explicit ``(module, function)`` allowlist — see ``_ambient_env_exempt_calls``.

Run with: python -m pytest skills/_shared/test_resolve_script_sweep.py -q
"""
from __future__ import annotations

import ast

import pytest

#: The symbol the sweep tracks. Every AST reference to it must sit in a
#: ``Call.func`` position — see ``_bare_references``.
SYMBOL = "resolve_shared_script"

#: The AMBIENT roots, and the kwarg each call site must name to opt out of it.
#: Both default to the REAL machine and both really do carry the module under
#: test on a dogfood checkout, so an omission of EITHER makes a cache-fallback
#: case pass for the wrong reason. `self_root=` was swept from the start;
#: `plugin_root=` was not, which left 15 call sites leaning entirely on
#: conftest.py's autouse `_strip_ambient_plugin_root` — delete that fixture with
#: $CLAUDE_PLUGIN_ROOT set and they silently resolve the ambient root. Same D3
#: failure, other root.
#: ``cwd`` feeds probe 1; OMIT it and the PROCESS cwd = the dogfood repo (D3).
AMBIENT_KWARGS = ("self_root", "plugin_root", "cwd")

PLUGIN_ROOT_ENV = "CLAUDE_PLUGIN_ROOT"  #: read by `plugin-root` when `_UNSET`.

#: The EXPLICIT, ENUMERATED exemption: the `(module, function)` pairs whose
#: resolver calls may omit `plugin_root=`, because they exercise the ambient
#: env read itself. Nothing lands here by accident and widening it is a visible
#: reviewable edit — the shape `test_resolve_script_hermeticity.EXCLUDED`
#: already uses for its canary. See `_ambient_env_exempt_calls` for why the
#: INFERRED exemption this replaces was abandoned.
AMBIENT_ENV_ALLOWLIST = frozenset(
    {
        ("test_resolve_script_roots.py", "test_ambient_env_plugin_root_resolves"),
        (
            "test_resolve_script_roots.py",
            "test_ambient_env_plugin_root_without_sentinel_is_recorded_as_a_miss",
        ),
        # Same reason, different module: this one drives the env derivation
        # with a DOT-ANCHOR spelling, so it must reach the ambient read with
        # `plugin_root` omitted. Setting the variable IS the subject.
        (
            "test_resolve_script_root_inputs.py",
            "test_the_env_derivation_gets_the_same_guard",
        ),
    }
)

#: How many resolver calls the allowlist may exempt ACROSS THE WHOLE SUITE.
#: The allowlist is per-FUNCTION, so alone it would let an extra un-opted-out
#: call appended INSIDE an allowlisted function inherit the exemption — evader
#: E1's shape, moved indoors. NOT the "call COUNT is a maintenance trap" the
#: meta-test refuses: that count grows with every test added, this one changes
#: only when the exemption does — exactly the review event. Spent-vs-declared
#: is checked in test_resolve_script_hermeticity.py against the REAL sources
#: (which also catches a STALE entry: it spends nothing).
EXEMPT_CALL_BUDGET = 3


def _calls(tree: ast.AST) -> list[ast.Call]:
    """Every ``resolve_shared_script(...)`` call node, bare or attribute-qualified.

    Keyed off ``SYMBOL``, never a repeated string literal: the two halves of
    this sweep (the call finder and ``_bare_references``) have to agree on WHICH
    symbol they track, and a hardcoded literal here could drift away from
    ``SYMBOL`` silently, leaving the alias guard watching a name nothing calls.
    """
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == SYMBOL:
            out.append(node)
        elif isinstance(func, ast.Attribute) and func.attr == SYMBOL:
            out.append(node)
    return out


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    """``id(Call)`` -> the name of the INNERMOST function lexically containing it.

    Innermost, never outermost: a call inside a helper defined within an
    allowlisted test belongs to the HELPER, and no allowlist entry names the
    helper. That closes evader E5 (a nested helper defined above a ``delenv``
    but invoked below it) BY CONSTRUCTION rather than by another rule. A
    ``lambda`` is an anonymous scope and gets a name no entry can spell.
    """
    out: dict[int, str] = {}

    def visit(node: ast.AST, current) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            current = node.name
        elif isinstance(node, ast.Lambda):
            current = "<lambda>"
        elif isinstance(node, ast.Call):
            out[id(node)] = current
        for child in ast.iter_child_nodes(node):
            visit(child, current)

    visit(tree, None)
    return out


def _ambient_env_exempt_calls(label: str, tree: ast.AST) -> set[int]:
    """``id()`` of the resolver calls in module ``label`` the allowlist exempts.

    The one legitimate reason to omit ``plugin_root=``: a case testing the
    AMBIENT ENV read itself must leave the parameter ``_UNSET``, because an
    explicit ``None`` suppresses the very read under test.

    Deciding that BY INFERENCE — "did this function SET the variable?" — was
    tried and walked past FOUR TIMES. Each round tightened the rule, each round
    grew the surface, because "was the variable actually set when this call
    ran?" is a RUNTIME question that static name-matching over ``ast.Call``
    spellings cannot answer:

    1. A mechanical sweep, no guard at all (author discipline only).
    2. FUNCTION granularity — a second call appended below a
       ``monkeypatch.delenv`` inherited the exemption (E1), and a ``setenv``
       parked in an ``if False:`` branch bought the function a pass (E2).
    3. LEXICAL scoping (direct body statement, before the call, not undone in
       between) — evaded four more ways: ``os.putenv`` is a setter that
       provably does NOT write ``os.environ``, arming the exemption while
       setting nothing (E3); ``del os.environ[...]`` / ``monkeypatch.undo()``
       revoke at runtime from outside the unsetter set (E4); a nested helper
       DEFINED above a ``delenv`` but INVOKED below it beat the ``lineno``
       comparison (E5); and a setter spelled with this module's own
       ``PLUGIN_ROOT_ENV`` constant matched nothing at all (E6).

    So the exemption is now an EXPLICIT ALLOWLIST of ``(module, function)``
    pairs, deliberately. It cannot be satisfied by WRITING anything, in any
    spelling, reachable or not — writing the variable is no longer an input to
    the decision, so that entire evasion class is gone rather than narrowed.
    Granting a new exemption means editing ``AMBIENT_ENV_ALLOWLIST``, which a
    reviewer sees; ``EXEMPT_CALL_BUDGET`` caps what the named functions may
    spend, so E1's shape cannot hide inside one.
    """
    functions = _enclosing_functions(tree)
    return {
        id(call)
        for call in _calls(tree)
        if (label, functions.get(id(call))) in AMBIENT_ENV_ALLOWLIST
    }


def _bare_references(tree: ast.AST) -> list[int]:
    """Line numbers where the symbol is referenced OUTSIDE a ``Call.func`` slot.

    This replaces the old textual-occurrence watchdog, which was evadable in
    exactly the case it existed to catch: a module doing
    ``_CALL = _rs.resolve_shared_script`` then ``_CALL(NAME, ...)`` has an AST
    call-count of 0 AND a textual ``resolve_shared_script(`` count of 0, so the
    two AGREED and the watchdog stayed silent while the aliased call resolved
    the live checkout — the D3 failure mode this sweep exists to prevent.
    ``functools.partial(resolve_shared_script, ...)`` evaded identically, and
    the textual pass additionally false-positived on the literal appearing in a
    comment or docstring.

    Binding the resolver to another name is the whole evasion class, so the rule
    is structural: a reference that is not itself being called has escaped the
    ``self_root=`` sweep.

    ``ImportFrom`` binds an ``ast.alias``, not an ``ast.Name``, so a PLAIN
    ``from resolve_script import resolve_shared_script`` does not trip the
    Name/Attribute pass — correctly, since it leaves the symbol callable under
    its own name. An ALIASED import is the opposite case and used to walk
    straight through: ``from resolve_script import resolve_shared_script as
    _rss`` binds the alias, so every later ``_rss(...)`` matches neither
    ``_calls`` (keyed on ``SYMBOL``) nor the Name pass here (also keyed on
    ``SYMBOL``) — both halves agreed at zero and the sweep stayed silent while
    the aliased call resolved the live checkout. Mutant-verified. So the alias
    itself is flagged: importing the symbol under another name IS the rebinding
    this function exists to reject, it just happens at the import statement.
    """
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    out: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            out.extend(
                node.lineno
                for alias in node.names
                if alias.name == SYMBOL and alias.asname is not None
            )
        elif isinstance(node, ast.Name) and node.id == SYMBOL and id(node) not in called:
            out.append(node.lineno)
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == SYMBOL
            and id(node) not in called
        ):
            out.append(node.lineno)
    return sorted(out)


def _offenders(label: str, tree: ast.AST) -> list[str]:
    """``<label>:<lineno> (<kwarg>=)`` per call site missing an ambient opt-out.

    The meta-test's predicate, factored out so the unit tests below judge the
    REAL rule rather than a transcription of it. A transcribed copy is how a
    guard and its own tests drift into agreeing about the wrong thing.
    """
    exempt = _ambient_env_exempt_calls(label, tree)
    out: list[str] = []
    for call in _calls(tree):
        named = {kw.arg for kw in call.keywords}
        for kwarg in AMBIENT_KWARGS:
            if kwarg in named:
                continue
            if kwarg == "plugin_root" and id(call) in exempt:
                continue  # allowlisted ambient-env case — see the allowlist
            out.append(f"{label}:{call.lineno} ({kwarg}=)")
    return out


# --------------------------------------------------------------------------- #
# PR #144 S4 — the rebinding rule must survive an ALIASED IMPORT
# --------------------------------------------------------------------------- #
#: An evader that used to leave the WHOLE suite green. The alias binds an
#: `ast.alias`, so `_rss(...)` is an `ast.Name` call whose `id` is "_rss" —
#: it matches neither `_calls` nor the Name/Attribute pass, and both halves
#: agree at zero while the call resolves the live checkout.
_ALIASED_EVADER = """
from resolve_script import resolve_shared_script as _rss

def test_thing(tmp_path):
    return _rss("github_pr_author.py", cwd=tmp_path)
"""

#: The negative control. A PLAIN import leaves the symbol callable under its own
#: name, so the sweep still sees every call site — it must NOT be flagged, or the
#: rule would reject every conforming module in the suite.
_PLAIN_IMPORT = """
from resolve_script import resolve_shared_script

def test_thing(tmp_path):
    return resolve_shared_script("x.py", cwd=None, self_root=None, plugin_root=None)
"""


def test_aliased_import_is_flagged():
    """`from resolve_script import resolve_shared_script as _rss` is a rebinding."""
    flagged = _bare_references(ast.parse(_ALIASED_EVADER))

    assert flagged, (
        "an aliased import of the resolver walked through the sweep — every "
        "later call is bound to the alias, so neither _calls nor the "
        "Name/Attribute pass can see it"
    )
    # It is the IMPORT line that is named, because that is where the rebinding
    # happens and where a reader has to fix it.
    assert flagged == [2], flagged


def test_aliased_evader_would_fail_the_meta_test():
    """The evader's call site is invisible to the `self_root=` sweep.

    The half that makes the alias dangerous: `_calls` finds ZERO calls in a
    module that plainly calls the resolver, so the `self_root=`/`plugin_root=`
    predicate has nothing to judge and the module passes vacuously. The alias
    guard is the only thing standing between that and a silent D3 failure.
    """
    assert _calls(ast.parse(_ALIASED_EVADER)) == []
    assert len(_calls(ast.parse(_PLAIN_IMPORT))) == 1


def test_plain_import_is_not_flagged():
    """Negative control: an ordinary import must not trip the alias rule."""
    assert _bare_references(ast.parse(_PLAIN_IMPORT)) == []


# --------------------------------------------------------------------------- #
# PR #144 R3 — the exemption is an ALLOWLIST, so pin what it does and does not
#              grant, and re-run every evader the INFERRED rule let through
# --------------------------------------------------------------------------- #
#: The allowlisted pair the cases below are written against, read OUT of the
#: allowlist rather than transcribed — a renamed entry moves these with it.
_ALLOWED_MODULE, _ALLOWED_FUNC = sorted(AMBIENT_ENV_ALLOWLIST)[0]

#: POSITIVE. The legitimate ambient-env shape: a call that deliberately omits
#: `plugin_root=` so the env read under test is not suppressed by an explicit
#: `None`. It is exempt because the allowlist NAMES it — the `setenv` is here
#: only because the real test has one; it grants nothing.
_OPTIN_REAL = f"""
def {_ALLOWED_FUNC}(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    return resolve_shared_script("x.py", cwd=None, self_root=None)
"""

#: NEGATIVE CONTROL. The same body under a name the allowlist does not carry.
#: Without this the positive case would be satisfied by a predicate that
#: exempts everything.
_OPTIN_UNNAMED = _OPTIN_REAL.replace(_ALLOWED_FUNC, "test_not_on_the_list")

#: Every shape that bought an exemption by WRITING the environment, from all
#: three rounds of the inferred rule. Under the allowlist none of them is a
#: question the predicate asks, so every one must be FLAGGED. Each is spelled
#: in a function the allowlist does not name — being named is now the only
#: thing that grants anything.
_EVADERS = {
    # R2/E1 — a second call below `delenv`, inheriting a function-wide grant.
    "E1-second-call-after-delenv": """
def test_ambient(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    first = resolve_shared_script("x.py", cwd=None, self_root=None)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT")
    second = resolve_shared_script("x.py", cwd=None, self_root=None)
    return first, second
""",
    # R2/E2 — the `setenv` is in a branch that CANNOT RUN.
    "E2-unreachable-setenv": """
def test_dead(tmp_path, monkeypatch):
    if False:
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    return resolve_shared_script("x.py", cwd=None, self_root=None)
""",
    # R3/E3 — `os.putenv` was in the setter set but does NOT write os.environ,
    # so it armed the exemption while setting nothing the resolver can read.
    "E3-putenv-sets-nothing": """
def test_putenv(tmp_path):
    os.putenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    return resolve_shared_script("x.py", cwd=None, self_root=None)
""",
    # R3/E4 — revocation from OUTSIDE the unsetter set: the variable is gone at
    # runtime, the `setenv` node is still there for the parse to find.
    "E4-revoked-outside-the-unsetter-set": """
def test_revoked(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    del os.environ["CLAUDE_PLUGIN_ROOT"]
    monkeypatch.undo()
    return resolve_shared_script("x.py", cwd=None, self_root=None)
""",
    # R3/E5 — the helper is DEFINED above the `delenv` and INVOKED below it, so
    # a lexical `lineno` comparison saw the definition, never the call.
    "E5-nested-helper-invoked-later": """
def test_nested(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

    def _helper():
        return resolve_shared_script("x.py", cwd=None, self_root=None)

    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT")
    return _helper()
""",
    # R3/E6 — spelled with the module's own constant instead of a string
    # literal, which the `ast.Constant` match could not see. Harmless on the
    # SETTER side (it just failed to grant); on the UNSETTER side it failed to
    # REVOKE, so the second call below stayed exempt with the variable gone.
    "E6-constant-not-literal": """
def test_constant(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    first = resolve_shared_script("x.py", cwd=None, self_root=None)
    monkeypatch.delenv(PLUGIN_ROOT_ENV)
    second = resolve_shared_script("x.py", cwd=None, self_root=None)
    return first, second
""",
}

#: EVADER E5 in its WORST form — the same helper, but inside the ALLOWLISTED
#: function, where a function-keyed exemption would otherwise reach it.
_NESTED_HELPER = _EVADERS["E5-nested-helper-invoked-later"].replace(
    "test_nested", _ALLOWED_FUNC
)


def _plugin_root_offenders(source: str, label: str = "m.py") -> list[str]:
    """The `plugin_root=` offenders `source` would contribute to the meta-test."""
    entries = _offenders(label, ast.parse(source))
    return [entry for entry in entries if entry.endswith("(plugin_root=)")]


def test_the_sweep_constants_are_exactly_the_expected_set():
    """Pin what the sweep EXEMPTS *and* what it SWEEPS — both, transcribed.

    Enumeration only pays if changing it is a visible, reviewable edit: add a
    pair, raise the budget, or drop a root from `AMBIENT_KWARGS` and this fails
    until the change is stated here too. NARROWING is the worse direction — an
    allowlist entry exempts ONE function, a dropped root exempts EVERY call
    site — and unpinned it is how a missing `cwd` survived five review rounds.
    """
    assert AMBIENT_ENV_ALLOWLIST == frozenset(
        {
            ("test_resolve_script_roots.py", "test_ambient_env_plugin_root_resolves"),
            (
                "test_resolve_script_roots.py",
                "test_ambient_env_plugin_root_without_sentinel_is_recorded_as_a_miss",
            ),
            (
                "test_resolve_script_root_inputs.py",
                "test_the_env_derivation_gets_the_same_guard",
            ),
        }
    ), AMBIENT_ENV_ALLOWLIST
    assert EXEMPT_CALL_BUDGET == 3
    assert AMBIENT_KWARGS == ("self_root", "plugin_root", "cwd"), AMBIENT_KWARGS


def test_an_allowlisted_case_is_exempt():
    """POSITIVE: the named `(module, function)` may omit `plugin_root=`."""
    assert _plugin_root_offenders(_OPTIN_REAL, _ALLOWED_MODULE) == [], (
        "the allowlisted ambient-env case must keep its exemption — an explicit "
        "`plugin_root=None` would suppress the very env read under test"
    )


def test_a_function_the_allowlist_does_not_name_is_not_exempt():
    """NEGATIVE CONTROL: the same body, unnamed → flagged.

    Without this, the positive case would be satisfied by a predicate that
    exempts every call in the repo.
    """
    assert _ambient_env_exempt_calls(_ALLOWED_MODULE, ast.parse(_OPTIN_UNNAMED)) == set()
    assert _plugin_root_offenders(_OPTIN_UNNAMED, _ALLOWED_MODULE) == [
        f"{_ALLOWED_MODULE}:4 (plugin_root=)"
    ]


def test_the_key_is_the_module_as_well_as_the_function():
    """The SAME function name in ANOTHER module is not exempt.

    The pair is the key: copying an allowlisted test's name into a different
    module must not carry the exemption across with it.
    """
    assert _plugin_root_offenders(_OPTIN_REAL, "other_module.py") == [
        "other_module.py:4 (plugin_root=)"
    ]


@pytest.mark.parametrize("shape", sorted(_EVADERS))
def test_writing_the_environment_never_buys_an_exemption(shape):
    """Every evader of the INFERRED rule, re-run against the allowlist.

    All six are flagged, and flagged for the same reason: none of them is
    named. The predicate no longer reads setters, unsetters, reachability or
    line numbers, so these are not six rules being satisfied — they are one
    question that is no longer asked.
    """
    source = _EVADERS[shape]
    tree = ast.parse(source)

    assert _ambient_env_exempt_calls("m.py", tree) == set(), (
        f"{shape}: writing the environment still granted an exemption"
    )
    # EVERY resolver call in the shape is flagged, not merely one of them —
    # E1's evasion was a SECOND call inheriting the first one's grant.
    assert len(_plugin_root_offenders(source)) == len(_calls(tree)) >= 1


def test_a_nested_helper_does_not_inherit_the_allowlist():
    """E5's worst form: the helper sits INSIDE the allowlisted function.

    This is the residual E1/E5 surface an allowlist keyed on a function name
    would otherwise have. Attribution is innermost, so `_helper` owns its call
    and `_helper` is not named.
    """
    offenders = _plugin_root_offenders(_NESTED_HELPER, _ALLOWED_MODULE)

    assert offenders == [f"{_ALLOWED_MODULE}:6 (plugin_root=)"], offenders


def test_self_root_is_never_exempt():
    """The exemption covers `plugin_root=` ONLY — `self_root=` has no env read.

    `self_root` is derived from `__file__`, not from the environment, so no
    allowlist entry can ever justify omitting it. A predicate that exempted
    both would silently re-open the original D3 hole on the root it was written
    for.
    """
    assert _offenders(_ALLOWED_MODULE, ast.parse(_OPTIN_REAL)) == []
    stripped = _OPTIN_REAL.replace(", self_root=None", "")

    assert _offenders(_ALLOWED_MODULE, ast.parse(stripped)) == [
        f"{_ALLOWED_MODULE}:4 (self_root=)"
    ]
