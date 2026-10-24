"""Noise and durable-state rules of scratch_leftovers (design: run-scratch-in-fence 1.2)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scratch_leftovers as sl  # noqa: E402

AREA_NOISE = [
    "pytest-of-curtis", "tmpK3f9Qa", "hsperfdata_u", "pip-install-x", "vscode-x", "ssh-x",
    ".org.chromium.x", ".com.google.Chrome.x", ".X0-lock", "pulse-x", "snap.x", "dbus-x",
    "systemd-private-abc", ".X11-unix", ".ICE-unix", ".font-unix", ".Test-unix", "tmux-1000",
    "snap-private-tmp", "claude-%d" % os.getuid(), "tpt-ffffff-AAAA", "tpt-AAAA",
]
HOME_NOISE = [
    ".claude-x", ".mozilla", ".var", ".thumbnails", ".Trash", "Downloads", ".xsession-errors",
    ".xsession-errors.old", ".ICEauthority", ".Xauthority", ".dbus", ".bash_history",
    ".zsh_history", ".lesshst", ".viminfo", ".python_history",
]


class Fx:
    def __init__(self, root, capsys, monkeypatch):
        self.root, self.capsys = root, capsys
        self.home, self.wt = root / "home", root / "wt"
        self.tmp = root / "tmp"
        for d in (self.home, self.home / "t", self.tmp, self.wt):
            d.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.wt, check=True)
        self.areas = (str(self.tmp),)
        self.env = {"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude")}
        monkeypatch.chdir(self.wt)

    def run(self, cmd, env=None):
        argv = [cmd, "--slug", "n", "--worktree", str(self.wt)]
        rc = sl.main(argv, env=env or self.env, areas=self.areas)
        return rc, self.capsys.readouterr().out


@pytest.fixture
def fx(tmp_path, capsys, monkeypatch):
    return Fx(tmp_path, capsys, monkeypatch)


@pytest.mark.parametrize("name", AREA_NOISE)
def test_area_noise_name_not_reported(fx, name):
    fx.run("provision")
    (fx.tmp / name).mkdir()
    rc, out = fx.run("check")
    assert rc == 0, out


def test_pytest_of_under_home_t_not_reported(fx):
    fx.run("provision")
    (fx.home / "t" / "pytest-of-curtis").mkdir()
    (fx.home / "t" / "pytest-of-curtis" / "x").mkdir()
    assert fx.run("check")[0] == 0


@pytest.mark.parametrize("name", HOME_NOISE)
def test_home_noise_name_not_reported(fx, name):
    fx.run("provision")
    (fx.home / name).mkdir()
    rc, out = fx.run("check")
    assert rc == 0, out


@pytest.mark.parametrize("name", [".cache_tel11.json", "tmp"])
def test_home_lookalikes_still_reported(fx, name):
    fx.run("provision")
    (fx.home / name).mkdir()
    rc, out = fx.run("check")
    assert rc == 1 and str(fx.home / name) in out


def test_changed_chrome_cache_and_existing_home_dir_ignored(fx):
    (fx.home / ".cache" / "google-chrome").mkdir(parents=True)
    (fx.home / "olddir").mkdir()
    for p in (fx.home / ".cache", fx.home / ".cache" / "google-chrome", fx.home / "olddir"):
        os.utime(p, (1_000_000_000, 1_000_000_000))
    fx.run("provision")
    (fx.home / ".cache" / "google-chrome" / "f").write_text("x")
    (fx.home / "olddir" / "f").write_text("x")
    rc, out = fx.run("check")
    assert rc == 0, out


def test_new_downloads_entry_not_reported(fx):
    (fx.home / "Downloads").mkdir()
    fx.run("provision")
    (fx.home / "Downloads" / "x").write_text("x")
    assert fx.run("check")[0] == 0


@pytest.mark.parametrize("tmpdir_rel", ["", "/"])
def test_tmpdir_parent_home_or_root_is_not_an_area(fx, tmpdir_rel):
    tmpdir = str(fx.home / "run") if tmpdir_rel == "" else "/run-x"
    env = dict(fx.env, TMPDIR=tmpdir)
    areas = sl.watch_areas(env, fx.areas, fx.wt)
    assert str(fx.home) not in areas and "/" not in areas


def test_tmpdir_parent_elsewhere_is_an_area(fx):
    seat = fx.root / "seat"
    seat.mkdir()
    env = dict(fx.env, TMPDIR=str(seat / "tmp"))
    assert os.path.realpath(seat) in sl.watch_areas(env, fx.areas, fx.wt)


def test_durable_state_not_reported(fx):
    fx.run("provision")
    for rel in (".local/state/tp-local/x", ".three-pillars"):
        (fx.home / rel).mkdir(parents=True)
    (fx.wt / ".git" / "tp-children").mkdir()
    assert fx.run("check")[0] == 0


def test_durable_state_constant_is_the_seven_templates():
    assert list(sl.DURABLE_STATE) == [
        "<git common dir>/objects", "<git common dir>/tp-children",
        "<git common dir>/tp-ladder", "<git common dir>/tp-scratch",
        "~/.local/state/tp-local", "~/.three-pillars", "$CLAUDE_CONFIG_DIR/projects",
    ]
