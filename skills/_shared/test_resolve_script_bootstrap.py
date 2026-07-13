"""End-to-end bootstrap seam test — plan Task 2.3 (audit F4).

Reproduces the exact #126 topology and proves the DOCUMENTED first-run.md
snippet closes it: a framework checkout whose repo copy is authoritative, with
``$TP_ROOT`` pointed at a pro-cache-shaped dir that LACKS both ``resolve_script.py``
AND the FREE chokepoint. The snippet is EXTRACTED from the shipped first-run.md
(never transcribed) and executed verbatim via ``bash -c``; it must resolve
``$RS`` / the target to the REPO copies (not ``$TP_ROOT``) and invoke the stub
chokepoint. This exercises the self-referential seam where #126 hid — the
resolver itself is absent from the cache ``$TP_ROOT``.

Run with: python -m pytest skills/_shared/test_resolve_script_bootstrap.py -q
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SHIPPED_RESOLVER = HERE / "resolve_script.py"

SENTINEL = "BOOTSTRAP_SENTINEL_OK"


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


SHIPPED_FIRST_RUN = _repo_root() / "skills" / "_shared" / "first-run.md"


def _extract_snippet() -> str:
    """Extract the first ```bash block under the §Resolve a FREE _shared script.

    Reads the SHIPPED first-run.md so the test guards the real prose — a
    regression that reverts the snippet to a bare-$TP_ROOT reach fails HERE.
    """
    text = SHIPPED_FIRST_RUN.read_text(encoding="utf-8")
    marker = "Resolve a FREE _shared script"
    idx = text.index(marker)
    match = re.search(r"```bash\n(.*?)```", text[idx:], re.DOTALL)
    assert match, "no ```bash snippet found under §Resolve a FREE _shared script"
    return match.group(1)


def _git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def sharp_126_topology(tmp_path):
    """Return (repo, tp_root) reproducing the #126 shape.

    ``repo`` is a framework checkout carrying the sentinel, the shipped
    resolve_script.py, and a stub chokepoint that prints SENTINEL + its path.
    ``tp_root`` is a pro-cache-shaped dir that carries NEITHER file.
    """
    repo = tmp_path / "framework_repo"
    repo.mkdir()
    _git_init(repo)
    # .claude-plugin/ marker (corroborating #126 shape).
    _write(repo / ".claude-plugin" / "plugin.json", '{"name": "three-pillars"}\n')
    # resolve_root.sh's framework sentinel.
    _write(repo / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    # The shipped resolver, copied in (self-referential: it's the module under test).
    shutil.copy(SHIPPED_RESOLVER, repo / "skills" / "_shared" / "resolve_script.py")
    # Stub FREE chokepoint that proves WHICH copy ran.
    _write(
        repo / "skills" / "_shared" / "github_pr_author.py",
        f'import sys\nprint("{SENTINEL}", __file__)\n',
    )

    # A pro-cache-shaped $TP_ROOT that LACKS both files (the #126 trap).
    tp_root = tmp_path / "pro_cache" / "three-pillars-pro" / "1.2.0"
    tp_root.mkdir(parents=True)
    (tp_root / "skills" / "_shared").mkdir(parents=True)  # dir exists, files do NOT

    return repo, tp_root


def test_tp_root_genuinely_lacks_the_free_files(sharp_126_topology):
    """Negative control: the trap $TP_ROOT carries neither file (else the test is vacuous)."""
    _repo, tp_root = sharp_126_topology
    assert not (tp_root / "skills" / "_shared" / "resolve_script.py").exists()
    assert not (tp_root / "skills" / "_shared" / "github_pr_author.py").exists()


def test_documented_snippet_resolves_repo_copy_and_invokes_chokepoint(sharp_126_topology):
    """The verbatim snippet resolves the REPO copies and runs the stub chokepoint."""
    repo, tp_root = sharp_126_topology
    snippet = _extract_snippet()

    env = dict(os.environ)
    env["TP_ROOT"] = str(tp_root)
    env["HOME"] = str(repo.parent / "empty_home")  # hermetic: no real cache
    (repo.parent / "empty_home").mkdir(exist_ok=True)

    proc = subprocess.run(
        ["bash", "-c", snippet],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"snippet failed: {proc.stderr}"
    # The chokepoint ran (sentinel on stdout) ...
    assert SENTINEL in proc.stdout
    # ... from the REPO copy, NOT the pro-cache $TP_ROOT.
    assert str(repo) in proc.stdout
    assert str(tp_root) not in proc.stdout


# --------------------------------------------------------------------------- #
# Audit A4 — the CONSUMER $TP_ROOT fallback branch of the same snippet
# --------------------------------------------------------------------------- #
@pytest.fixture()
def consumer_tp_root_topology(tmp_path):
    """Return (consumer, tp_root, home) exercising the ``else "$TP_ROOT"`` branch.

    ``consumer`` is a plain (non-framework) git repo — OUTSIDE any framework
    checkout, so the snippet's ``if`` dogfood test (``-f "$TOP"/…/resolve_script.py``)
    fails and the ``else "$TP_ROOT"/…`` fallback line is taken. ``tp_root`` is a
    cache-shaped dir carrying the shipped resolve_script.py AND a stub chokepoint;
    it lives UNDER the default ``$HOME`` plugin cache so the resolver's own cache
    branch finds the stub. Distinct from sharp_126_topology, which exercises the
    dogfood ``if`` branch (cwd inside a framework checkout).
    """
    consumer = tmp_path / "consumer_repo"
    consumer.mkdir()
    _git_init(consumer)  # plain repo: NO framework sentinel

    home = tmp_path / "home"
    tp_root = home / ".claude" / "plugins" / "cache" / "marketplace" / "three-pillars" / "1.2.0"
    shared = tp_root / "skills" / "_shared"
    shared.mkdir(parents=True)
    shutil.copy(SHIPPED_RESOLVER, shared / "resolve_script.py")
    _write(
        shared / "github_pr_author.py",
        f'import sys\nprint("{SENTINEL}", __file__)\n',
    )
    return consumer, tp_root, home


def test_consumer_tp_root_fallback_resolves_and_invokes_stub(consumer_tp_root_topology):
    """The snippet's ``else "$TP_ROOT"`` branch resolves the stub chokepoint.

    Negative control inline: the consumer repo carries NO resolve_script.py, so
    the ``if`` dogfood branch genuinely cannot fire — the else fallback is real.
    """
    consumer, tp_root, home = consumer_tp_root_topology
    # The dogfood branch cannot fire here (repo lacks the resolver).
    assert not (consumer / "skills" / "_shared" / "resolve_script.py").exists()

    snippet = _extract_snippet()
    env = dict(os.environ)
    env["TP_ROOT"] = str(tp_root)
    env["HOME"] = str(home)  # hermetic cache root that carries the stub

    proc = subprocess.run(
        ["bash", "-c", snippet],
        cwd=str(consumer),
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"snippet failed: {proc.stderr}"
    # The stub chokepoint ran (sentinel on stdout) ...
    assert SENTINEL in proc.stdout
    # ... resolved through the $TP_ROOT cache-shaped tree (the else fallback).
    assert str(tp_root) in proc.stdout
