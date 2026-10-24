"""Tests for scratch_leftovers: baseline, check, accept (design: run-scratch-in-fence 1.2)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_scratch  # noqa: E402
import scratch_leftovers as sl  # noqa: E402

SLUG = "demo"


class Fx:
    def __init__(self, root, capsys, monkeypatch):
        self.root, self.capsys = root, capsys
        self.home, self.wt = root / "home", root / "wt"
        self.tmp, self.vtmp, self.shm = root / "tmp", root / "vartmp", root / "shm"
        for d in (self.home, self.home / "t", self.tmp, self.vtmp, self.shm, self.wt):
            d.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.wt, check=True)
        self.areas = (str(self.tmp), str(self.vtmp), str(self.shm))
        self.env = {"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude")}
        monkeypatch.chdir(self.wt)

    def old(self, *paths):
        for p in paths:
            p.mkdir(parents=True, exist_ok=True)
        for p in sorted(self.root.rglob("*")):
            if p.is_dir() and self.wt not in p.parents and p != self.wt:
                os.utime(p, (1_000_000_000, 1_000_000_000))

    def run(self, cmd, *extra, env=None):
        argv = [cmd, "--slug", SLUG, "--worktree", str(self.wt), *extra]
        rc = sl.main(argv, env=env or self.env, areas=self.areas)
        return rc, self.capsys.readouterr().out

    @property
    def baseline(self):
        return self.wt / ".git" / "tp-scratch" / SLUG / "baseline.json"


@pytest.fixture
def fx(tmp_path, capsys, monkeypatch):
    return Fx(tmp_path, capsys, monkeypatch)


def test_provision_creates_then_exists_and_keeps_baseline(fx):
    rc, out = fx.run("provision")
    assert rc == 0 and run_scratch.run_dir(fx.wt) in out and "created" in out
    first = fx.baseline.read_bytes()
    (fx.home / "tmp").mkdir()
    rc, out = fx.run("provision")
    assert rc == 0 and "exists" in out
    assert fx.baseline.read_bytes() == first
    rc, out = fx.run("check")
    assert rc == 1 and f"scratch-leftover: {fx.home / 'tmp'}" in out


def test_clean_tree_exits_zero(fx):
    fx.run("provision")
    rc, out = fx.run("check")
    assert rc == 0 and "scratch-leftover" not in out


def _leak_home_file(fx):
    return fx.home / ".cache_tel11.json"


@pytest.mark.parametrize("rel", [
    "home:.cache_tel11.json", "home:tmp", "home:t/slot8-x", "tmp:x", "tmp:TAG",
])
def test_new_leftover_fails_with_recovery(fx, rel):
    fx.run("provision")
    where, name = rel.split(":")
    base = {"home": fx.home, "tmp": fx.tmp}[where]
    name = f"tpt-{run_scratch.tag(fx.wt)}-AAAA" if name == "TAG" else name
    target = base / name
    target.write_text("x") if "." in name else target.mkdir()
    rc, out = fx.run("check")
    assert rc == 1
    assert f"scratch-leftover: {target}" in out
    rec = [ln for ln in out.splitlines() if ln.startswith("if this is not the run's own path")]
    assert len(rec) == 1 and "accept" in rec[0] and "TP_SCRATCH_ALLOW" in rec[0]


@pytest.mark.parametrize("dirpath", ["home/t/old", "tmp/olddir", "tmp/a/b"])
def test_write_into_existing_dir_names_the_dir(fx, dirpath):
    d = fx.root / dirpath
    fx.old(d)
    fx.run("provision")
    (d / "f").write_text("x")
    rc, out = fx.run("check")
    assert rc == 1 and f"scratch-leftover: {d}" in out


def test_depth_four_containing_dir_not_reported(fx):
    d = fx.tmp / "a" / "b" / "c" / "d"
    fx.old(d)
    fx.run("provision")
    (d / "f").write_text("x")
    rc, out = fx.run("check")
    assert rc == 0, out


def test_scan_root_itself_never_reported(fx):
    (fx.tmp / "gone").mkdir()
    (fx.home / "t" / "gone").mkdir()
    fx.old()
    fx.run("provision")
    (fx.tmp / "gone").rmdir()
    (fx.home / "t" / "gone").rmdir()
    (fx.tmp / "tmpAbc").mkdir()
    rc, out = fx.run("check")
    assert rc == 0, out


def test_accept_flow(fx):
    fx.run("provision")
    (fx.wt / "three-pillars-docs" / "tp-designs" / SLUG).mkdir(parents=True)  # accept audits here
    p = fx.tmp / "sibling"
    p.mkdir()
    assert fx.run("accept", "--path", str(p))[0] == 2
    assert fx.run("accept", "--path", str(fx.root / "elsewhere"), "--reason", "r")[0] == 2
    assert fx.run("accept", "--path", str(fx.tmp / "nope"), "--reason", "r")[0] == 2
    assert fx.run("accept", "--path", str(p), "--reason", "inspected ok")[0] == 0
    rc, out = fx.run("check")
    assert rc == 0
    assert f"scratch-allowed: {p} (accepted " in out and "inspected ok)" in out


def test_allow_recorded_at_provision_only(fx):
    env = dict(fx.env, TP_SCRATCH_ALLOW="keepme:other*")
    fx.run("provision", env=env)
    (fx.tmp / "keepme").mkdir()
    (fx.tmp / "late").mkdir()
    rc, out = fx.run("check", env=dict(fx.env, TP_SCRATCH_ALLOW="late"))
    assert rc == 1
    assert f"scratch-allowed: {fx.tmp / 'keepme'} (allow)" in out
    assert f"scratch-leftover: {fx.tmp / 'late'}" in out


def test_baseline_worktree_and_all_leftovers(fx):
    (fx.tmp / "before").mkdir()
    fx.run("provision")
    (fx.tmp / "one").mkdir()
    (fx.home / "two").mkdir()
    rc, out = fx.run("check")
    assert rc == 1
    assert f"scratch-leftover: {fx.tmp / 'one'}" in out
    assert f"scratch-leftover: {fx.home / 'two'}" in out
    assert "before" not in out and str(fx.wt) not in out


def test_removed_worktree_checks_from_baseline(fx):
    main = fx.root / "main"
    main.mkdir()
    git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], cwd=main, check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "i"], cwd=main, check=True)
    subprocess.run([*git, "worktree", "add", "-q", "--detach", str(fx.root / "lw")], cwd=main, check=True)
    fx.wt = fx.root / "lw"
    os.chdir(main)
    rc, _ = fx.run("provision")
    assert rc == 0
    subprocess.run([*git, "worktree", "remove", "--force", str(fx.wt)], cwd=main, check=True)
    (fx.home / "stray").mkdir()
    rc, out = fx.run("check")
    want = f"scratch-leftover: {fx.home / 'stray'}"
    assert rc == 1 and want in out, f"expected rc 1 and {want!r} (fx.home / 'stray') in: rc={rc} out={out!r}"


def test_no_baseline_cases(fx, tmp_path):
    rc, out = fx.run("check")
    assert rc == 1 and "scratch-leftover: no baseline" in out
    dd = tmp_path / "design"
    dd.mkdir()
    (dd / "decisions.md").write_text("nothing here\n")
    rc, out = fx.run("check", "--design-dir", str(dd))
    assert rc == 0 and "scratch-leftover: skipped (no run scratch)" in out
    rc, out = fx.run("check", "--design-dir", str(dd), "--expect")
    assert rc == 1 and "scratch-leftover: no run scratch" in out


def test_p9_unhooked_writer_into_new_home_stray(fx):
    fx.run("provision")
    Path(fx.home, "stray").write_text("plain python write")
    rc, out = fx.run("check")
    want = f"scratch-leftover: {fx.home / 'stray'}"
    assert rc == 1 and want in out, f"expected rc 1 and {want!r} (fx.home / 'stray') in: rc={rc} out={out!r}"
