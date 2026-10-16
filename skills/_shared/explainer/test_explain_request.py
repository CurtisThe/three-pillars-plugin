"""test_explain_request.py — build_request: the bundle, stable ids, the budget.

Covers explainer-agent plan Task 4.3 (detailed-design §Interfaces:
"build_request(root, *, kind, slug, subject=None, base=None,
review_digest=None, char_budget=12000) -> dict. Returns {schema:
"explain-request/v1", kind, slug, subject, evidence:[{ref, label, text}],
evidence_head}. kind must be in KINDS ... else ValueError. Ref ids are closed
and stable ... The budget trims decisions first, then tree items, and never
drops subject or design items."):
  - an unknown kind raises ValueError; every KINDS entry is accepted;
  - a valid call has the v1 shape, every ref in the closed grammar, and
    evidence_head = git rev-parse HEAD;
  - two calls give identical ref lists;
  - under a budget, decisions drop first (oldest first), then tree items;
    subject and design items stay even when still over budget, and the trim
    only removes items (the kept order is unchanged);
  - outside a repo evidence_head is "" and the file readers still work; a
    slug with no sources gives no evidence and nothing raises.

Every repo is built under tmp_path; git runs with the shipped
task_scope._git_env scrub (git_env is dev-only), so no repo docs are read
(skills/_shared/test-fragility.md).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_request as er  # noqa: E402
from task_scope import _git_env  # noqa: E402 — git_env is dev-only

_ENV = _git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
SLUG = "demo"
DESIGN_REFS = [
    "design:problem", "design:scope", "design:dependencies",
    "design:consumer-repo", "design:forge", "design:loci",
]
DECISION_REFS = ["decision:1", "decision:2", "decision:3"]
SUBJECT = {"question": "Ship the brief now?", "options": ["now", "later"]}
SUBJECT_REFS = ["subject:question", "subject:options"]
# The closed ref grammar of detailed-design §Interfaces.
CLOSED_REF = re.compile(
    r"^(design:(problem|scope|dependencies|consumer-repo|forge|loci)"
    r"|diffstat|tree:\S+|config:diff|audit:verdict|review:digest"
    r"|decision:[1-9][0-9]*|ruling:\S+|subject:\S+)$"
)
# Each decision body dwarfs every other item, so a budget a few thousand
# chars under the total forces a known number of decision drops.
DECISION_BODY = 2500

DESIGN_MD = """\
# demo — a design

## Problem
PROBLEM-BODY

## Scope
SCOPE-BODY

## Dependencies
DEPS-BODY

## Consumer-repo behaviour
CONSUMER-BODY

## Forge behaviour
FORGE-BODY

## State space
### Loci
LOCI-BODY
"""


def _decisions_md() -> str:
    parts = ["# Decisions log\n"]
    for n in (1, 2, 3):
        parts.append(f"\n### [tp-plan] Decision {n}\n"
                     f"**Decided**: D{n} {'x' * DECISION_BODY}\n")
    return "".join(parts)


def _git(root: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false",
         "-c", f"core.hooksPath={root}/.no-hooks", *argv],
        cwd=str(root), env=_ENV, check=True, capture_output=True, text=True,
    ).stdout


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _commit(root: Path, msg: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    return _git(root, "rev-parse", "HEAD").strip()


def _design_files(root: Path) -> None:
    d = f"three-pillars-docs/tp-designs/{SLUG}"
    _write(root, f"{d}/design.md", DESIGN_MD)
    _write(root, f"{d}/decisions.md", _decisions_md())
    _write(root, f"{d}/implementation-audit.md", "**Verdict**: pass\n")
    _write(root, f"{d}/rulings.ndjson",
           json.dumps({"id": "r1", "decided": "ship"}) + "\n")


@pytest.fixture
def repo(tmp_path):
    """Design sources committed at base; then a commit touching two dirs."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _design_files(root)
    _write(root, "pkg/keep.py", "k = 1\n")
    _write(root, "other/keep.py", "k = 1\n")
    base = _commit(root, "base")
    _write(root, "pkg/a.py", "a = 1\n")
    _write(root, "other/b.py", "b = 1\n")
    _commit(root, "change")
    digest = tmp_path / "review-digest.md"
    digest.write_text("REVIEW-BODY clean round\n", encoding="utf-8")
    return root, base, digest


def _build(repo, **kw):
    root, base, digest = repo
    args = dict(kind="pr-brief", slug=SLUG, subject=SUBJECT, base=base,
                review_digest=str(digest))
    args.update(kw)
    return er.build_request(root, **args)


def _refs(request) -> list[str]:
    return [item["ref"] for item in request["evidence"]]


def _total(request) -> int:
    return sum(len(item["text"]) for item in request["evidence"])


def test_unknown_kind_raises(tmp_path):
    with pytest.raises(ValueError):
        er.build_request(tmp_path, kind="bogus", slug=SLUG)


@pytest.mark.parametrize("kind", er.KINDS)
def test_every_known_kind_is_accepted(repo, kind):
    assert _build(repo, kind=kind)["kind"] == kind


def test_request_has_the_v1_shape(repo):
    root, _, _ = repo
    request = _build(repo)
    assert set(request) == {"schema", "kind", "slug", "subject", "evidence",
                            "evidence_head"}
    assert request["schema"] == "explain-request/v1"
    assert request["kind"] == "pr-brief"
    assert request["slug"] == SLUG
    assert request["subject"] == SUBJECT
    assert request["evidence_head"] == _git(root, "rev-parse", "HEAD").strip()
    for item in request["evidence"]:
        assert set(item) == {"ref", "label", "text"}
        assert all(isinstance(item[k], str) and item[k] for k in item)
        assert CLOSED_REF.match(item["ref"]), item["ref"]
    refs = _refs(request)
    assert len(refs) == len(set(refs))
    expected = {*DESIGN_REFS, *DECISION_REFS, *SUBJECT_REFS, "diffstat",
                "tree:pkg", "tree:other", "audit:verdict", "review:digest",
                "ruling:r1"}
    assert expected <= set(refs)


def test_ref_lists_are_identical_across_calls(repo):
    assert _refs(_build(repo)) == _refs(_build(repo))


def _kept_in_order(full: list[str], trimmed: list[str]) -> bool:
    """True when *trimmed* is *full* with some items removed, order kept."""
    kept = set(trimmed)
    return trimmed == [r for r in full if r in kept]


def test_budget_drops_the_oldest_decisions_first(repo):
    full = _build(repo, char_budget=10 ** 9)
    budget = _total(full) - (DECISION_BODY + DECISION_BODY // 5)
    trimmed = _build(repo, char_budget=budget)
    refs = _refs(trimmed)
    # Dropping decision:1 is not enough; dropping decision:2 as well is.
    assert [r for r in refs if r.startswith("decision:")] == ["decision:3"]
    assert {"tree:pkg", "tree:other"} <= set(refs)
    assert _kept_in_order(_refs(full), refs)
    assert _total(trimmed) <= budget


def test_budget_drops_tree_items_after_every_decision(repo):
    full = _build(repo, char_budget=10 ** 9)
    decisions = sum(len(i["text"]) for i in full["evidence"]
                    if i["ref"].startswith("decision:"))
    trimmed = _build(repo, char_budget=_total(full) - decisions - 1)
    refs = _refs(trimmed)
    assert not [r for r in refs if r.startswith("decision:")]
    trees = [r for r in refs if r.startswith("tree:")]
    assert len(trees) < len([r for r in _refs(full) if r.startswith("tree:")])
    assert set(DESIGN_REFS + SUBJECT_REFS) <= set(refs)
    assert _kept_in_order(_refs(full), refs)


def test_subject_and_design_items_survive_any_budget(repo):
    full = _build(repo, char_budget=10 ** 9)
    trimmed = _build(repo, char_budget=0)
    refs = _refs(trimmed)
    assert set(DESIGN_REFS + SUBJECT_REFS) <= set(refs)
    assert not [r for r in refs
                if r.startswith("decision:") or r.startswith("tree:")]
    assert _kept_in_order(_refs(full), refs)


def test_outside_a_repo_head_is_empty_and_files_still_read(tmp_path,
                                                           monkeypatch):
    # Stop git discovery at tmp_path, so an enclosing checkout never counts.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    plain = tmp_path / "plain"
    plain.mkdir()
    _design_files(plain)
    request = er.build_request(plain, kind="auto-ruling", slug=SLUG,
                               base="HEAD")
    assert request["evidence_head"] == ""
    refs = _refs(request)
    assert set(DESIGN_REFS) <= set(refs)
    assert not [r for r in refs if r == "diffstat" or r.startswith("tree:")]


def test_missing_sources_give_no_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    request = er.build_request(tmp_path / "missing", kind="human-escalation",
                               slug="no-such-design", base="HEAD",
                               review_digest=str(tmp_path / "absent.md"))
    assert request["evidence"] == []
    assert request["evidence_head"] == ""
