"""The three CLI fixes in `generator_catalog.py` (basesync-generator-catalog task 6.5).

`test_generator_catalog_cli.py` covers the wiring as first built; this module pins the three
behaviours that build got wrong. Each is observable only from outside the process, so every
assertion is an exit code or the parsed `.three-pillars/config.json` - never prose, never the
bytes of a doc. The repos are real tmp git repos (a tracked `package.json` + `package-lock.json`,
and a nested `web/pyproject.toml` + `web/uv.lock`); the not-a-repo case patches the git call out,
because what real git prints there depends on which filesystem the tmp dir sits on (task 6.6).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

if shutil.which("git") is None:  # consumer-repo rule: skip cleanly, never fail, without git
    pytest.skip("git binary absent", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generator_catalog  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "generator_catalog.py"

EXISTING_GENERATOR = {"path": "gen/out.ts", "write": ["node", "gen.js"]}
CONFIG = {"schema_version": 1, "merge_from_main": {"generators": [EXISTING_GENERATOR]}}
# A root npm pair and a nested uv pair: `--only` has to carry both, one flag or two.
TRACKED = ["package.json", "package-lock.json", "web/pyproject.toml", "web/uv.lock"]
BOTH_LOCKS = ["package-lock.json", "web/uv.lock"]


def git(repo, *args) -> str:
    proc = subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def run_cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT)] + list(args),
                          capture_output=True, text=True, cwd=cwd)


def make_repo(tmp_path, config=CONFIG, tracked=TRACKED):
    """A tmp git repo with `tracked` in the index and `config` in
    `.three-pillars/config.json` - the fixture shape of `test_generator_catalog_cli.py`."""
    repo = tmp_path / "repo"
    for rel in tracked:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", "--", *tracked)
    if config is not None:
        cfg = repo / ".three-pillars" / "config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return repo


def read_config(repo):
    return json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))


def test_accept_after_decline_writes_the_generator(tmp_path):
    """The operator changes their mind: `accept --paths P` after `decline --paths P` of the same
    lockfile adds the generator entry and flips `generator_offer.declined` back to false. The
    earlier decline suppresses `detect`, so accepting has to re-detect past the offer record."""
    repo = make_repo(tmp_path)
    proc = run_cli("decline", "--repo", str(repo), "--paths", "package-lock.json", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    declined = read_config(repo)
    assert declined["merge_from_main"]["generators"] == [EXISTING_GENERATOR]
    assert declined["merge_from_main"]["generator_offer"]["declined"] is True

    proc = run_cli("accept", "--repo", str(repo), "--paths", "package-lock.json", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    data = read_config(repo)
    gens = data["merge_from_main"]["generators"]
    assert [g["path"] for g in gens] == ["gen/out.ts", "package-lock.json"]
    assert gens[1]["write"] == ["npm", "install", "--package-lock-only", "--ignore-scripts",
                                "--no-audit", "--no-fund"]
    assert gens[1]["inputs"] == ["package.json"]
    offer = data["merge_from_main"]["generator_offer"]
    assert offer["declined"] is False
    assert offer["offered_paths"] == ["package-lock.json"]


def test_detect_only_takes_several_values(tmp_path):
    """`--only A B` (several values after one flag) and `--only A --only B` (the repeatable form)
    both report the same two lockfiles; neither is a usage error."""
    repo = make_repo(tmp_path)
    one_flag = run_cli("detect", "--repo", str(repo), "--only", *BOTH_LOCKS, "--json", cwd=tmp_path)
    assert one_flag.returncode == 0, one_flag.stderr
    assert [i["path"] for i in json.loads(one_flag.stdout)] == BOTH_LOCKS

    per_flag = run_cli("detect", "--repo", str(repo), "--only", BOTH_LOCKS[0],
                       "--only", BOTH_LOCKS[1], "--json", cwd=tmp_path)
    assert per_flag.returncode == 0, per_flag.stderr
    assert [i["path"] for i in json.loads(per_flag.stdout)] == BOTH_LOCKS


def test_accept_outside_git_exits_2(tmp_path, monkeypatch, capsys):
    """Neither `accept` nor `decline` runs outside a git repository: exit 2, ONE stderr line (no
    traceback, however many lines git's own complaint has), and no config file written.

    The failing `git ls-files` is patched out rather than real: outside a repo git's stderr is
    one line when the tmp dir shares a filesystem with `/` and two when it does not ("Stopping at
    filesystem boundary AC..."), so the real call makes the line count depend on `TMPDIR`. The
    point under test is that `main` collapses whatever the exception carries into one line.
    """
    def refuse(repo):
        raise ValueError("git ls-files failed: fatal: not a git repository\n"
                         "Stopping at filesystem boundary (GIT_SEARCH_ROOT_DEPTH not set).")

    monkeypatch.setattr(generator_catalog, "_tracked_paths", refuse)
    for command in ("accept", "decline"):
        capsys.readouterr()
        rc = generator_catalog.main([command, "--repo", str(tmp_path),
                                     "--paths", "package-lock.json"])
        captured = capsys.readouterr()
        assert rc == 2, f"{command}: rc={rc}"
        lines = [ln for ln in captured.err.splitlines() if ln.strip()]
        assert len(lines) == 1, captured.err
        assert not (tmp_path / ".three-pillars" / "config.json").exists()
        assert captured.out == ""
