"""Pure-unit tests for `living_doc_carry.py` — the leaf helpers of the living-doc
hand-resolution carry (Phase 1).

No git here: `is_living_doc_carry_path` (the carry-set predicate + single-definition
guard, task 1.1), `carry_livingdoc_handres_enabled` (the default-ON config reader,
task 1.2), and the module cap + stdlib-only guards (task 1.4). The `## History`
preamble-date cases live in the sibling `test_living_doc_carry_preamble.py` (task 1.3),
a pre-decided split that keeps each test file under the 300-line cap.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import file_size_guard  # noqa: E402
from living_doc_carry import (  # noqa: E402
    _PROJECT_CONTEXT,
    _SPECS_PREFIX,
    carry_livingdoc_handres_enabled,
    is_living_doc_carry_path,
)

_KEY = "living_doc_handres_preserves_approval"

_MODULE_SRC = os.path.join(os.path.dirname(__file__), "living_doc_carry.py")
_MODULE_PATH = Path(_MODULE_SRC)


# ============================================================
# Task 1.1: is_living_doc_carry_path — carries
# ============================================================

_CARRY_TRUE = [
    "three-pillars-docs/known_issues.md",
    "three-pillars-docs/known_issues_resolved.md",
    "three-pillars-docs/product_roadmap.md",
    "three-pillars-docs/architecture.md",
    "three-pillars-docs/vision.md",
    "three-pillars-docs/tp-designs/x/design.md",
    "three-pillars-docs/tp-designs/x/detailed-design.md",
    "three-pillars-docs/tp-designs/x/plan.md",
    "three-pillars-docs/RELEASING.md",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
]


def test_is_living_doc_carry_path_carries():
    for path in _CARRY_TRUE:
        assert is_living_doc_carry_path(path) is True, path


# ---- exclusions (→ False): the two authority exclusions + root CLAUDE.md ----

_CARRY_FALSE_EXCLUSIONS = [
    "three-pillars-docs/specs/framework/x.md",
    "three-pillars-docs/specs/pipeline/y.md",
    "three-pillars-docs/project-context.md",
    "CLAUDE.md",
]


def test_is_living_doc_carry_path_exclusions():
    for path in _CARRY_FALSE_EXCLUSIONS:
        assert is_living_doc_carry_path(path) is False, path


# ---- masquerade (→ False): non-.md, wrong location, bad type ----

_CARRY_FALSE_MASQUERADE = [
    "three-pillars-docs/foo.py",
    "three-pillars-docs/foo.sh",
    "three-pillars-docs/foo.json",
    "three-pillars-docs/foo.yml",
    "three-pillars-docs/tp-designs/x/lock.json",
    "skills/x/SKILL.md",
    "agents/x.md",
    "three-pillars-docs/foo",  # no extension
    "",
]


def test_is_living_doc_carry_path_masquerade():
    for path in _CARRY_FALSE_MASQUERADE:
        assert is_living_doc_carry_path(path) is False, path


def test_is_living_doc_carry_path_non_str_is_false_never_raises():
    # Total: any non-str fails closed, never raises.
    for path in (None, 123, 4.5, ["three-pillars-docs/x.md"], {"a": 1}, object()):
        assert is_living_doc_carry_path(path) is False, repr(path)


# ============================================================
# Task 1.1: single-definition guard — the two authority exclusions
# ============================================================


def test_carry_set_single_definition_guard():
    # (1) The two exclusion constants carry exactly the expected literals.
    assert _SPECS_PREFIX == "three-pillars-docs/specs/"
    assert _PROJECT_CONTEXT == "three-pillars-docs/project-context.md"

    # (2) Each literal is defined EXACTLY ONCE in the module source — mirrors the
    # AUTO_SAFE_PATHS single-definition precedent, so a future engine-fed `.md`
    # cannot silently add a second, drifting copy of an authority exclusion.
    src = open(_MODULE_SRC, encoding="utf-8").read()
    assert src.count("three-pillars-docs/specs/") == 1
    assert src.count("three-pillars-docs/project-context.md") == 1


def test_specs_and_project_context_are_the_only_authority_exclusions():
    # Every `.md` under three-pillars-docs/ carries EXCEPT the two authority
    # exclusions — pins that no third, hidden exclusion has crept in.
    assert is_living_doc_carry_path("three-pillars-docs/anything.md") is True
    assert is_living_doc_carry_path("three-pillars-docs/tp-designs/deep/nest.md") is True
    # The two — and only the two — flip to False:
    assert is_living_doc_carry_path(_PROJECT_CONTEXT) is False
    assert is_living_doc_carry_path(_SPECS_PREFIX + "any.md") is False


# ============================================================
# Task 1.2: carry_livingdoc_handres_enabled — default-ON reader
# ============================================================
#
# The deliberate INVERSE of strict-OFF `base_sync_cert.carry_enabled`: returns False ONLY
# on a literal `False`; True on absence / non-dict / non-bool value / any exception
# (fail-toward-default). Safety rests on the predicate + code-unchanged guard + zero-drop
# + ci_local_stamp, NOT on this flag being off.


class _RaisingGet(dict):
    """A truthy dict subclass whose `.get` raises — exercises the except → True arm."""

    def get(self, *a, **k):
        raise RuntimeError("boom")


def test_carry_livingdoc_handres_enabled_default_on_matrix():
    for config in (
        None,
        {},
        {"review": {}},
        {"review": {_KEY: True}},
        {"review": {_KEY: "false"}},            # a STRING, not the bool
        {"review": {_KEY: 0}},                  # falsy non-bool → still not literal False
        "not-a-dict",                           # non-dict config
        123,
        {"review": "not-a-dict"},               # non-dict review
        _RaisingGet({"review": {_KEY: False}}),  # .get raises → fail-toward-default
    ):
        assert carry_livingdoc_handres_enabled(config) is True, repr(config)


def test_carry_livingdoc_handres_enabled_literal_false_only():
    assert carry_livingdoc_handres_enabled({"review": {_KEY: False}}) is False


# ============================================================
# Task 1.4: cap + stdlib-only guards (new file, NOT grandfathered)
# ============================================================
#
# The module grows in Phase 2 (`certify_link_carry` et al.) — these guards re-run and must
# stay green then too.


def test_living_doc_carry_under_cap():
    lines, chars, _text = file_size_guard.measure(_MODULE_PATH)
    assert lines <= 500, f"living_doc_carry.py is {lines} lines (> 500 hard cap)"
    assert chars <= 50_000, f"living_doc_carry.py is {chars} chars (> 50k hard cap)"


def _module_level_import_roots(src: str) -> set[str]:
    """Top-level import roots only — a function-local `import base_sync_cert` (Phase 2)
    lives inside a FunctionDef body, so it is deliberately NOT counted here."""
    roots: set[str] = set()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_living_doc_carry_stdlib_only():
    src = _MODULE_PATH.read_text(encoding="utf-8")
    roots = _module_level_import_roots(src)
    # Every module-level import must be stdlib OR `verify` (the zero-drop backstop, reached
    # via the Path(__file__)-relative sys.path shim in Phase 2). No third-party anywhere.
    allowed = set(sys.stdlib_module_names) | {"verify"}
    stray = roots - allowed
    assert not stray, f"non-stdlib module-level imports in living_doc_carry.py: {stray}"
    assert "anthropic" not in roots
    assert "requests" not in roots
