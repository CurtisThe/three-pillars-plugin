"""`merge_back` hands the conflicted set to `resolve_generated`, so a generator whose declared
`inputs` are still conflicted is never run.

A lockfile declared `inputs: ["package.json"]` cannot be rebuilt from a `package.json` that still
holds conflict markers — the rebuild would start from broken sources and any output it produced
would be a guess. The deferral must therefore happen BEFORE the generator runs (no side effects,
no wasted minutes) and must name the input that is in the way.

The fixture's generator is deliberately noisy and side-effecting: it appends to a marker file and
writes to stdout. The marker file is the witness that it ran at all; the stdout is the witness that
nothing the generator prints can reach the driver's JSON (the driver's contract with `/tp-merge` is
one parseable document per run).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

PKG = "package.json"
LOCK = "package-lock.json"
MARKER = "ran.marker"
CONFIG = ".three-pillars/config.json"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

# Rebuilds the lockfile from `package.json`, noisily and with a side effect, so a run is visible.
GEN = '''
import json
from pathlib import Path
Path("ran.marker").open("a", encoding="utf-8").write("ran\\n")
print("generator stdout noise")
print("generator stderr noise", file=__import__("sys").stderr)
data = json.loads(Path("package.json").read_text(encoding="utf-8"))
lock = {"lock": [data["version"]]}
Path("package-lock.json").write_text(json.dumps(lock, indent=2, sort_keys=True) + "\\n",
                                     encoding="utf-8")
'''


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=clean_git_env(**IDENTITY))


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def pkg_text(version):
    return json.dumps({"name": "x", "version": version}, indent=2, sort_keys=True) + "\n"


def lock_text(stale):
    return json.dumps({"lock": [stale]}, indent=2, sort_keys=True) + "\n"


def declare():
    gens = [{"path": LOCK, "write": [sys.executable, "gen.py"], "inputs": [PKG]}]
    return json.dumps({"merge_from_main": {"generators": gens}})


def setup(tmp_path, *, ours_version="1.1", theirs_version="1.2"):
    """Both sides edit `package.json` and the lockfile, so both paths conflict on merge."""
    repo = tmp_path / "r"
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "master")
    for name, body in (("gen.py", GEN), (CONFIG, declare()),
                       (PKG, pkg_text("1.0")), (LOCK, lock_text("0.0"))):
        write(repo, name, body)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, PKG, pkg_text(ours_version))
    write(repo, LOCK, lock_text("ours-stale"))
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, PKG, pkg_text(theirs_version))
    write(repo, LOCK, lock_text("theirs-stale"))
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    return repo


def outcome(report, path):
    return next(o for o in report.outcomes if o["path"] == path)


def run_cli(repo):
    """The driver CLI over the whole merge: returns (stdout, returncode)."""
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "merge_driver.py"),
                           str(repo), "master"],
                          capture_output=True, text=True, env=clean_git_env(**IDENTITY))
    return proc.stdout, proc.returncode


def test_conflicted_input_defers_before_the_generator_runs(tmp_path):
    repo = setup(tmp_path)
    report = merge_back(str(repo), "master")
    o = outcome(report, LOCK)
    assert o["action"] == "deferred", report.to_json()
    assert "input package.json is still conflicted" in o["reason"], report.to_json()
    assert not (repo / MARKER).exists(), "the generator ran against a conflicted input"
    assert LOCK in report.deferred and report.needs_human


def test_driver_cli_stdout_stays_one_json_document(tmp_path):
    repo = setup(tmp_path)
    stdout, code = run_cli(repo)
    assert code == 2, stdout
    doc = json.loads(stdout)          # a chatty generator must not corrupt the report
    assert doc["base_ref"] == "master"
    lock = next(o for o in doc["outcomes"] if o["path"] == LOCK)
    assert lock["action"] == "deferred"
    assert "input package.json is still conflicted" in lock["reason"]
    assert not (repo / MARKER).exists()


def test_unconflicted_input_regenerates_the_generated_file(tmp_path):
    # Only theirs touches `package.json`, so it merges clean and the rebuild has usable sources.
    repo = setup(tmp_path, ours_version="1.0")
    report = merge_back(str(repo), "master")
    o = outcome(report, LOCK)
    assert o["action"] == "auto-resolved", report.to_json()
    assert o["resolved_classes"] == ["regenerate"]
    assert (repo / MARKER).exists(), "the generator never ran"
    assert json.loads((repo / LOCK).read_text(encoding="utf-8"))["lock"] == ["1.2"]
