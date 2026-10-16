"""Tests for agent_variants.py — render the generated agent variants, drift check.

design: run-throughput (Task 3.2). Synthetic trees only (`--framework-root` /
`fw_root` argument); never touches the real `agents/` or `.claude-plugin/`.
Run with: python3 -m pytest skills/_shared/test_agent_variants.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_variants as av  # noqa: E402
import ladder_rungs  # noqa: E402
import local_implement_config  # noqa: E402
import weight_class  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "agent_variants.py"

BASE_TEXT = (
    "---\n"
    "name: tp-task-worker\n"
    'description: "One-task implement worker for `--local` dispatch."\n'
    "model: opus\n"
    "effort: xhigh\n"
    "color: cyan\n"
    'tools: ["Read", "Edit", "Write", "Grep", "Glob", "Bash"]\n'
    "---\n"
    "\n"
    "## Identity\n"
    "\n"
    "You are the one-task worker spawned by a `--local` dispatcher.\n"
)

CERTIFIER_TEXT = (
    "---\n"
    "name: tp-certifier\n"
    'description: "Gate certifier."\n'
    "model: opus\n"
    "effort: xhigh\n"
    "color: red\n"
    "---\n"
    "\n"
    "Body.\n"
)

RUNG_EXPECT = {
    "local-medium": ("haiku", "medium"),
    "local-xhigh": ("haiku", "xhigh"),
    "sonnet-medium": ("sonnet", "medium"),
    "sonnet-xhigh": ("sonnet", "xhigh"),
}


def _plugin_dict(agents_dir: Path) -> dict:
    names = sorted(p.name for p in agents_dir.glob("*.md"))
    return {
        "name": "three-pillars",
        "keywords": ["tdd"],
        "agents": [f"./agents/{n}" for n in names],
    }


def _clean_tree(tmp_path: Path) -> Path:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "tp-task-worker.md").write_text(BASE_TEXT, encoding="utf-8")
    (agents_dir / "tp-certifier.md").write_text(CERTIFIER_TEXT, encoding="utf-8")
    for rung in ladder_rungs.SPAWN_RUNGS:
        name = f"tp-task-worker-{rung}"
        (agents_dir / f"{name}.md").write_text(av.render(BASE_TEXT, rung), encoding="utf-8")
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(_plugin_dict(agents_dir), indent=2), encoding="utf-8"
    )
    return tmp_path


# --- expected / variants ------------------------------------------------------


def test_expected_uses_local_implement_defaults():
    spec = av.expected("tp-task-worker-local-medium")
    assert spec == {"role": "task", "model": "haiku", "effort": "medium"}
    assert local_implement_config.DEFAULTS["model"] == "haiku"


def _strata_medium_bases() -> set[str]:
    """Every `council-*.md` base in the real repo (a generated `-medium` is not a base)."""
    agents = Path(__file__).resolve().parents[2] / "agents"
    return {p.stem for p in agents.glob("council-*.md") if not p.stem.endswith("-medium")}


def test_variants_cover_every_family():
    names = av.variants()
    # Q4: opus-medium / opus-xhigh are real variants; Q2: the round-1 review agent;
    # strata-effort-every-call 2.1: the confirmer and every council persona get a
    # Strata-only `-medium` copy, so the expected set is derived, never counted.
    expected = {f"tp-task-worker-{r}" for r in ladder_rungs.SPAWN_RUNGS} | {
        "tp-review-confirmer-deep", "tp-review-confirmer-medium"} | {
        f"{base}-medium" for base in _strata_medium_bases()}
    assert set(names) == expected
    assert len(names) == len(expected)


# --- render --------------------------------------------------------------------


def test_render_keeps_base_body_byte_identical():
    _, base_body = av._split_frontmatter(BASE_TEXT)
    for rung in ladder_rungs.SPAWN_RUNGS:
        rendered = av.render(BASE_TEXT, rung)
        _, body = av._split_frontmatter(rendered)
        assert body == base_body


def test_render_sets_frontmatter_from_expected():
    for rung, (model, effort) in RUNG_EXPECT.items():
        rendered = av.render(BASE_TEXT, rung)
        fm = weight_class.parse_frontmatter(rendered)
        assert fm["name"] == f"tp-task-worker-{rung}"
        assert fm["model"] == model
        assert fm["effort"] == effort
        assert fm["description"].startswith('"One-task implement worker')
        assert fm["description"].endswith(f'(rung {rung})"')


# --- check: clean tree ----------------------------------------------------------


def test_check_clean_tree_has_no_drift(tmp_path):
    fw_root = _clean_tree(tmp_path)
    assert av.check(fw_root) == []


# --- check: hand-edited effort ---------------------------------------------------


def test_check_reports_hand_edited_effort(tmp_path):
    fw_root = _clean_tree(tmp_path)
    path = fw_root / "agents" / "tp-certifier.md"
    path.write_text(CERTIFIER_TEXT.replace("effort: xhigh", "effort: medium"), encoding="utf-8")
    drift = av.check(fw_root)
    assert any("tp-certifier" in line and "effort" in line for line in drift)


# --- check: agent with no policy entry -------------------------------------------


def test_check_reports_agent_with_no_policy_entry(tmp_path):
    fw_root = _clean_tree(tmp_path)
    agents_dir = fw_root / "agents"
    mystery = (
        "---\n"
        "name: general-purpose\n"
        'description: "Not in the policy table."\n'
        "model: sonnet\n"
        "---\n"
        "\nBody.\n"
    )
    (agents_dir / "general-purpose.md").write_text(mystery, encoding="utf-8")
    # keep plugin.json in sync so this scenario isolates the "no policy" drift
    plugin_path = fw_root / ".claude-plugin" / "plugin.json"
    plugin_path.write_text(json.dumps(_plugin_dict(agents_dir), indent=2), encoding="utf-8")

    drift = av.check(fw_root)
    assert drift == ["no policy: general-purpose.md has no model_policy.AGENTS entry "
                      "and matches no variant rung"]

    # write() cannot invent a policy for it — it is reported, not fixed
    fixed = av.write(fw_root)
    assert fixed == drift
    assert av.check(fw_root) == drift


# --- check: stale plugin.json agents array ---------------------------------------


def test_check_reports_stale_plugin_agents(tmp_path):
    fw_root = _clean_tree(tmp_path)
    plugin_path = fw_root / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    data["agents"].pop()
    plugin_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    drift = av.check(fw_root)
    assert any("plugin.json" in line for line in drift)


# --- write: fixes each and re-check is clean -------------------------------------


def test_write_fixes_hand_edited_effort_and_stale_plugin(tmp_path):
    fw_root = _clean_tree(tmp_path)
    agents_dir = fw_root / "agents"
    plugin_path = fw_root / ".claude-plugin" / "plugin.json"

    # hand-edit an agent's effort
    (agents_dir / "tp-certifier.md").write_text(
        CERTIFIER_TEXT.replace("effort: xhigh", "effort: medium"), encoding="utf-8"
    )
    # hand-edit a variant file's model line (variant drift)
    variant_path = agents_dir / "tp-task-worker-local-medium.md"
    variant_path.write_text(
        variant_path.read_text(encoding="utf-8").replace("model: haiku", "model: sonnet"),
        encoding="utf-8",
    )
    # stale plugin.json agents array
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    data["agents"].pop()
    plugin_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    assert av.check(fw_root) != []
    fixed = av.write(fw_root)
    assert fixed != []
    assert av.check(fw_root) == []

    # the certifier effort is restored
    fm = weight_class.parse_frontmatter(
        (agents_dir / "tp-certifier.md").read_text(encoding="utf-8")
    )
    assert fm["model"] == "opus" and fm["effort"] == "xhigh"
    # the plugin.json agents array is restored, and the rest of the file survives
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    assert data["agents"] == _plugin_dict(agents_dir)["agents"]
    assert data["keywords"] == ["tdd"]


# --- CLI -------------------------------------------------------------------------


def _run(fw_root, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--framework-root", str(fw_root), *args],
        capture_output=True, text=True,
    )


def test_cli_check_exit_1_on_drift_0_clean(tmp_path):
    fw_root = _clean_tree(tmp_path)
    assert _run(fw_root, "--check").returncode == 0

    (fw_root / "agents" / "tp-certifier.md").write_text(
        CERTIFIER_TEXT.replace("effort: xhigh", "effort: medium"), encoding="utf-8"
    )
    result = _run(fw_root, "--check")
    assert result.returncode == 1
    assert "tp-certifier" in result.stdout


def test_cli_write_then_check_is_clean(tmp_path):
    fw_root = _clean_tree(tmp_path)
    (fw_root / "agents" / "tp-certifier.md").write_text(
        CERTIFIER_TEXT.replace("effort: xhigh", "effort: medium"), encoding="utf-8"
    )
    assert _run(fw_root, "--check").returncode == 1
    assert _run(fw_root, "--write").returncode == 0
    assert _run(fw_root, "--check").returncode == 0
