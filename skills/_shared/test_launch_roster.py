"""launch_roster.register — the launcher's roster registration (fleet-watcher-reliability 1.5).

The launcher must register every run it opens and say so when ``adopt`` did not
confirm it, exit code or not (``adopt`` exits 0 on every refusal). The runner is
an injected seam and the skills tree is a tmp tree, so nothing here runs a
process. Assertions are on the returned line's prefix and the command run, per
skills/_shared/test-fragility.md.
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import launch_design_run as ldr  # noqa: E402
import launch_roster  # noqa: E402
from test_launch_design_run import _run, rig  # noqa: E402,F401


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A skills tree holding `_shared/launch_roster.py` and one fleet_roster.py."""
    shared = tmp_path / "skills" / "_shared"
    shared.mkdir(parents=True)
    cli = tmp_path / "skills" / "somepack" / "scripts" / "fleet_roster.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("# fake cli\n", encoding="utf-8")
    monkeypatch.setattr(launch_roster, "__file__", str(shared / "launch_roster.py"))
    return cli


class Run:
    def __init__(self, stdout="", returncode=0, exc=None):
        self.stdout, self.returncode, self.exc, self.calls = stdout, returncode, exc, []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if self.exc:
            raise self.exc
        return types.SimpleNamespace(stdout=self.stdout, returncode=self.returncode, stderr="")


def test_register_runs_adopt_update_for_the_slug(tree, tmp_path):
    run = Run("adopted: foo\n")
    assert launch_roster.register("foo", str(tmp_path), run=run) is None
    assert run.calls == [[sys.executable, str(tree.resolve()), "--root", str(tmp_path), "adopt", "--update", "foo"]]


@pytest.mark.parametrize("out", ["adopted: foo\n", "updated: foo\n", "foo: unchanged (live)\n"])
def test_register_is_silent_when_adopt_confirmed(tree, tmp_path, out):
    assert launch_roster.register("foo", str(tmp_path), run=Run(out)) is None


def test_register_confirms_from_any_line_of_the_output(tree, tmp_path):
    out = "roster: over capacity, 3 live, cap 2\nupdated: foo\n"
    assert launch_roster.register("foo", str(tmp_path), run=Run(out)) is None


def test_register_does_nothing_when_no_cli_exists(tmp_path, monkeypatch):
    shared = tmp_path / "skills" / "_shared"
    shared.mkdir(parents=True)
    monkeypatch.setattr(launch_roster, "__file__", str(shared / "launch_roster.py"))
    run = Run("adopted: foo\n")
    assert launch_roster.register("foo", str(tmp_path), run=run) is None
    assert run.calls == []


@pytest.mark.parametrize("out", [
    "foo: not live, not adopted\n",
    "foo: no tp/foo worktree, not adopted\n",
    "adopt: tmux unavailable; nothing adopted\n",
    "foo: not live, not updated\n",
])
def test_register_reports_an_exit_zero_refusal(tree, tmp_path, out):
    got = launch_roster.register("foo", str(tmp_path), run=Run(out, returncode=0))
    assert got.startswith("roster: foo not registered (")
    assert out.strip() in got


def test_register_reports_a_nonzero_exit(tree, tmp_path):
    got = launch_roster.register("foo", str(tmp_path), run=Run("", returncode=2))
    assert got.startswith("roster: foo not registered (")


def test_register_reports_a_nonzero_exit_even_when_stdout_confirms(tree, tmp_path):
    got = launch_roster.register("foo", str(tmp_path), run=Run("adopted: foo\n", returncode=1))
    assert got.startswith("roster: foo not registered (")


def test_register_reports_an_oserror(tree, tmp_path):
    got = launch_roster.register("foo", str(tmp_path), run=Run(exc=OSError("boom")))
    assert got.startswith("roster: foo not registered (")
    assert "boom" in got


def test_register_does_not_take_another_slugs_confirmation(tree, tmp_path):
    got = launch_roster.register("foo", str(tmp_path), run=Run("adopted: foobar\n"))
    assert got.startswith("roster: foo not registered (")


# --- launcher wiring: the fresh-launch path registers, no other path does ---------------------

@pytest.fixture
def opened(monkeypatch):
    """Every tmux-touching step injected, and `register` recorded."""
    seen = []
    monkeypatch.setattr(ldr.design_run_tmux, "live", lambda *a, **k: "")
    monkeypatch.setattr(ldr.design_run_tmux, "open", lambda *a, **k: ldr.design_run_tmux.OpenResult(
        True, "design run launched in tmux window seat:2", "foo:1", "seat"))
    monkeypatch.setattr(ldr.design_run_brief, "commit_brief", lambda *a, **k: "")
    monkeypatch.setattr(ldr.design_run_routing, "wait_for_run", lambda *a, **k: "77")
    monkeypatch.setattr(ldr.design_run_routing, "read_routing", lambda *a, **k: "routing: x")
    monkeypatch.setattr(ldr.design_run_send, "deliver", lambda *a, **k: "delivered")
    monkeypatch.setattr(ldr.launch_roster, "register", lambda slug, root, **k: seen.append((slug, root)))
    return seen


def test_a_fresh_launch_registers_the_run_once(rig, opened):
    assert _run(rig, ["foo", "--skip-design"]) == 0
    assert opened == [("foo", os.path.realpath(rig["repo"]))]


def test_a_fresh_launch_prints_the_unconfirmed_line_and_keeps_its_exit_code(rig, opened, capsys, monkeypatch):
    line = "roster: foo not registered (foo: not live, not adopted)"
    monkeypatch.setattr(ldr.launch_roster, "register", lambda slug, root, **k: line)
    assert _run(rig, ["foo", "--skip-design"]) == 0
    assert line in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize("flags", [["--dry-run"], ["--base-sync"]])
def test_dry_run_and_base_sync_do_not_register(rig, opened, flags):
    assert _run(rig, ["foo", "--skip-design", *flags]) == 0
    assert opened == []


def test_resume_does_not_register(rig, opened, monkeypatch):
    monkeypatch.setattr(ldr.drrc, "resume", lambda *a, **k: 0)
    assert _run(rig, ["foo", "--resume"]) == 0
    assert opened == []
