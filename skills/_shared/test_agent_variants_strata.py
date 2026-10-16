"""test_agent_variants_strata.py — the Strata `-medium` variants are generated, not copied.

design: strata-effort-every-call (Task 2.1). Every Strata-bound dispatch names a
`<base>-medium` agent, so the variants must come out of `agent_variants.render` (a
hand-copied persona file drifts the moment its base is edited), match their base byte
for byte below the frontmatter, and keep the drift check clean on the real repo. The
variant's description is the short Strata-only line: the agent listing stays small and
the variant names the base it copies instead of advertising itself standalone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import agent_variants as av  # noqa: E402
import weight_class  # noqa: E402

REPO = _SHARED.parents[1]
ADA = "council-ada"
CONFIRMER = "tp-review-confirmer"
DESC = ("Strata-only medium-effort copy of {base}; "
        "spawned via strata_effort.py spawn.")


def _agent(name: str) -> str:
    return (REPO / "agents" / f"{name}.md").read_text(encoding="utf-8")


def _fw_root(tmp_path: Path) -> Path:
    """A tmp framework root: one council base, its generated variant, and the manifest."""
    root = tmp_path / "fw"
    agents = root / "agents"
    agents.mkdir(parents=True)
    base = _agent(ADA)
    (agents / f"{ADA}.md").write_text(base, encoding="utf-8")
    (agents / f"{ADA}-medium.md").write_text(av.render(base, "medium", ADA), encoding="utf-8")
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "three-pillars",
                    "agents": [f"./agents/{p.name}" for p in sorted(agents.glob("*.md"))]}),
        encoding="utf-8")
    return root


# --- variants() knows the Strata family -------------------------------------


@pytest.mark.parametrize("name", [f"{ADA}-medium", "council-watts-medium",
                                  f"{CONFIRMER}-medium"])
def test_variants_include_the_strata_medium_copies(name):
    assert name in av.variants()


# --- render: the body is the base's, the frontmatter states medium ----------


def test_render_keeps_the_council_body_byte_identical():
    base_text = _agent(ADA)
    _, base_body = av._split_frontmatter(base_text)
    _, body = av._split_frontmatter(av.render(base_text, "medium", ADA))
    assert body == base_body


def test_render_sets_the_strata_variant_model_and_effort():
    fm = weight_class.parse_frontmatter(av.render(_agent(ADA), "medium", ADA))
    assert fm["name"] == f"{ADA}-medium"
    assert (fm["model"], fm["effort"]) == ("opus", "medium")


def test_render_gives_the_variant_the_short_strata_description():
    fm = weight_class.parse_frontmatter(av.render(_agent(ADA), "medium", ADA))
    assert fm["description"] == f'"{DESC.format(base=ADA)}"'
    assert ADA in fm["description"]
    assert "Use standalone" not in fm["description"]


def test_render_of_a_non_strata_variant_is_unchanged():
    """The `-deep` render keeps its base description plus its suffix label."""
    deep = av.render(_agent(CONFIRMER), "deep", CONFIRMER)
    fm = weight_class.parse_frontmatter(deep)
    assert fm["name"] == f"{CONFIRMER}-deep"
    assert fm["description"].endswith('(deep)"')
    assert "Strata-only" not in fm["description"]


# --- the real repo is generated and drift-free ------------------------------


def test_live_repo_has_no_variant_drift():
    assert av.check(REPO) == []


@pytest.mark.parametrize("base", [ADA, CONFIRMER])
def test_live_variant_equals_its_render_and_shares_its_base_body(base):
    base_text = _agent(base)
    _, base_body = av._split_frontmatter(base_text)
    rendered = av.render(base_text, "medium", base)
    assert _agent(f"{base}-medium") == rendered
    assert av._split_frontmatter(rendered)[1] == base_body


# --- a hand-edited variant body is drift ------------------------------------


def test_hand_edited_variant_body_is_reported(tmp_path):
    root = _fw_root(tmp_path)
    path = root / "agents" / f"{ADA}-medium.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nHand-copied extra paragraph.\n",
                    encoding="utf-8")
    assert any(line.startswith("variant drift:") and ADA in line
               for line in av.check(root))
