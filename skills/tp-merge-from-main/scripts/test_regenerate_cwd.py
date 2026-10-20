"""`regenerate.py`: a declared `cwd` that does not exist is refused as a missing `cwd`.

A generator whose `cwd` directory is absent cannot run anywhere sensible: the spawn fails and the
refusal today names the binary (`<tool> not found`), which sends whoever reads it hunting for a
tool that is actually installed. The honest refusal is the missing directory itself, and it has to
arrive before anything is written or run. The unit is `regenerate_file` with a recording `run`
stub - no real subprocess is spawned.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))
from regenerate import Generator, regenerate_file  # noqa: E402

TARGET = "web/pkg-lock.json"


def cwd_repo(tmp_path, name="repo"):
    """A fresh repo under `tmp_path/name` with the target's parent directory present but the
    target itself absent, so "not written" is observable."""
    repo = tmp_path / name
    (repo / "web").mkdir(parents=True, exist_ok=True)
    return repo


def recorder():
    """A fake `run` seam: records every call, answers every one with a successful exit 0."""
    calls = []

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return SimpleNamespace(returncode=0)
    return run, calls


def test_missing_cwd_is_named(tmp_path):
    """A generator whose declared `cwd` directory does not exist is refused as
    `cwd <path> does not exist` before any write or run: the stub is never called and the target
    is never created."""
    repo = cwd_repo(tmp_path, "missing")
    gen = Generator(path=TARGET, write=["true"], check=None, cwd="does-not-exist")
    run, calls = recorder()
    text, reason = regenerate_file(repo, gen, "ours\n", "ours\n", run=run)
    assert text is None
    assert reason == "cwd does-not-exist does not exist"
    assert calls == []
    assert not (repo / TARGET).exists()


def test_existing_cwd_is_unchanged(tmp_path):
    """The same generator pointed at a `cwd` that does exist still regenerates: `(text, "")` and
    every run happens in that directory."""
    repo = cwd_repo(tmp_path, "present")
    (repo / "web" / "build").mkdir(parents=True, exist_ok=True)
    gen = Generator(path=TARGET, write=["true"], check=None, cwd="web/build")
    run, calls = recorder()
    text, reason = regenerate_file(repo, gen, "ours\n", "ours\n", run=run)
    assert (text, reason) == ("ours\n", "")
    assert calls
    for _, kwargs in calls:
        assert str(kwargs["cwd"]) == str(repo / "web" / "build")


def test_undeclared_cwd_is_unchanged(tmp_path):
    """A generator with no `cwd` at all is untouched by the new check: it regenerates with every
    run in the repo root."""
    repo = cwd_repo(tmp_path, "undeclared")
    gen = Generator(path=TARGET, write=["true"], check=None)
    run, calls = recorder()
    text, reason = regenerate_file(repo, gen, "ours\n", "ours\n", run=run)
    assert (text, reason) == ("ours\n", "")
    assert calls
    for _, kwargs in calls:
        assert str(kwargs["cwd"]) == str(repo)
