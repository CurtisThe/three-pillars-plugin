"""test_agent_ref.py — the one agent-reference resolver, on fixture framework roots.

design: run-throughput (seat ruling: PR #178 merge held — agent-name resolver fix, (a)/(d))

Behavior only: a fixture root whose plugin.json names ``three-pillars-pro`` resolves to
``three-pillars-pro:<agent>`` through the Python API and the ``agent_ref.py`` CLI; every broken manifest fails loudly (API raises, CLI
exits 1 with one stderr line), never a bare or hardcoded-prefix fallback.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import agent_ref

SHARED = Path(__file__).resolve().parent
AGENT = "tp-task-worker-local-medium"


def fixture_root(tmp_path: Path, name="three-pillars-pro", agents=(AGENT,), listed=True,
                 manifest: str | None = None) -> Path:
    root = tmp_path / "fw"
    (root / "agents").mkdir(parents=True)
    (root / ".claude-plugin").mkdir()
    for a in agents:
        (root / "agents" / f"{a}.md").write_text(f"---\nname: {a}\n---\n", encoding="utf-8")
    if manifest is None:
        data = {"name": name} if name is not None else {"version": "1.0.0"}
        if listed:
            data["agents"] = [f"./agents/{a}.md" for a in agents]
        manifest = json.dumps(data)
    (root / ".claude-plugin" / "plugin.json").write_text(manifest, encoding="utf-8")
    return root


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SHARED / "agent_ref.py"), *args],
                          capture_output=True, text=True, timeout=30)


def test_pro_fixture_resolves_through_api_and_cli(tmp_path):
    root = fixture_root(tmp_path)
    assert agent_ref.resolve(AGENT, root) == f"three-pillars-pro:{AGENT}"
    res = _cli(AGENT, "--root", str(root))
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == f"three-pillars-pro:{AGENT}"


def test_core_name_follows_the_manifest(tmp_path):
    root = fixture_root(tmp_path, name="three-pillars", agents=("tp-worker",))
    assert agent_ref.resolve("tp-worker", root) == "three-pillars:tp-worker"


def test_unlisted_manifest_still_needs_the_agent_file(tmp_path):
    root = fixture_root(tmp_path, listed=False)
    assert agent_ref.resolve(AGENT, root) == f"three-pillars-pro:{AGENT}"
    with pytest.raises(agent_ref.AgentRefError, match="no agents/tp-worker.md"):
        agent_ref.resolve("tp-worker", root)


@pytest.mark.parametrize("case", ["absent", "malformed", "not-object", "nameless", "blank-name"])
def test_broken_manifest_fails_loudly(tmp_path, case):
    manifest = {"malformed": "{not json", "not-object": "[1, 2]",
                "nameless": json.dumps({"agents": [f"./agents/{AGENT}.md"]}),
                "blank-name": json.dumps({"name": "  "})}.get(case)
    root = fixture_root(tmp_path, manifest=manifest)
    if case == "absent":
        (root / ".claude-plugin" / "plugin.json").unlink()
    with pytest.raises(agent_ref.AgentRefError) as exc:
        agent_ref.resolve(AGENT, root)
    assert str(exc.value).startswith(f"agent-unresolved: {AGENT}: ")
    res = _cli(AGENT, "--root", str(root))
    assert res.returncode == 1 and res.stdout == ""
    assert res.stderr.startswith(f"agent-ref: agent-unresolved: {AGENT}: ")
    assert "three-pillars" not in res.stdout


def test_unreadable_manifest_fails_loudly(tmp_path):
    root = fixture_root(tmp_path)
    manifest = root / ".claude-plugin" / "plugin.json"
    manifest.unlink()
    manifest.mkdir()  # a directory where the file should be: unreadable on every OS/user
    with pytest.raises(agent_ref.AgentRefError, match="unreadable"):
        agent_ref.resolve(AGENT, root)


@pytest.mark.parametrize("agent", ["tp-worker", "council-*", "council-{name}", "", "Tp-Worker"])
def test_unknown_or_non_concrete_agent_fails_loudly(tmp_path, agent):
    root = fixture_root(tmp_path)
    with pytest.raises(agent_ref.AgentRefError):
        agent_ref.resolve(agent, root)


def test_agent_file_present_but_not_in_manifest_list_fails(tmp_path):
    root = fixture_root(tmp_path)
    (root / "agents" / "tp-worker.md").write_text("---\nname: tp-worker\n---\n", encoding="utf-8")
    with pytest.raises(agent_ref.AgentRefError, match="does not list ./agents/tp-worker.md"):
        agent_ref.resolve("tp-worker", root)


def test_default_root_is_this_install():
    """No --root: the framework root the resolver is installed in (its own plugin.json)."""
    root = SHARED.parent.parent
    name = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["name"]
    assert agent_ref.resolve("tp-worker") == f"{name}:tp-worker"
