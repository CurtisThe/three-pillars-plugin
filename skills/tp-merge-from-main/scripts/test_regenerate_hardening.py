"""`regenerate.py` hardening: the optional `timeout` / `inputs` / `cwd` generator keys.

`load_generators` reads three new optional keys on a declared item and defaults them when absent,
so an item written before the keys existed still loads. Each key is validated at load time - an
item whose `timeout` is not a positive int, whose `inputs` is not a list of non-empty strings, or
whose `cwd` is empty, absolute or escapes the repo through a `..` segment is skipped as malformed,
exactly like the existing `path`/`write`/`check` refusals. No subprocess runs here: the unit is the
config read alone.
"""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))
from regenerate import DEFAULT_TIMEOUT, Generator, load_generators, regenerate_file  # noqa: E402

WRITE = ["python3", "tools/gen.py"]
CHECK = ["python3", "tools/check.py"]


def item(**extra):
    """A well-formed declared item `{path, write}` plus the optional keys under test."""
    base = {"path": "web/package-lock.json", "write": WRITE}
    base.update(extra)
    return base


def config(*items):
    return {"merge_from_main": {"generators": list(items)}}


def one(**extra):
    """The single `Generator` loaded from an item carrying `extra`."""
    gens = load_generators(config(item(**extra)))
    assert len(gens) == 1
    return gens[0]


def test_old_item_loads_with_the_new_keys_defaulted():
    """A `{path, write, check}` item written before the new keys existed still loads, with
    `timeout=None`, `inputs=()` and `cwd=None`."""
    g = one(check=CHECK)
    assert g.path == "web/package-lock.json"
    assert g.write == WRITE
    assert g.check == CHECK
    assert g.timeout is None
    assert g.inputs == ()
    assert g.cwd is None


def test_default_timeout_is_ten_minutes():
    """The fallback every undeclared generator run gets is 600 seconds."""
    assert DEFAULT_TIMEOUT == 600


def test_new_keys_load_as_declared():
    """`timeout: 300`, `inputs: ["package.json"]` and `cwd: "web"` load as given; `inputs` is
    stored as a tuple so the frozen record stays value-comparable."""
    g = one(check=CHECK, timeout=300, inputs=["package.json"], cwd="web")
    assert g.timeout == 300
    assert g.inputs == ("package.json",)
    assert g.cwd == "web"


def test_timeout_must_be_a_positive_int():
    """`0`, `-1`, `True` and `"300"` are all malformed timeouts: the item is skipped."""
    for bad in (0, -1, True, "300"):
        assert load_generators(config(item(timeout=bad))) == [], bad


def test_inputs_must_be_a_list_of_non_empty_strings():
    """A bare string, an empty entry, a non-string entry or a mapping is a malformed `inputs`:
    the item is skipped."""
    for bad in ("package.json", ["package.json", ""], ["package.json", 5], {}):
        assert load_generators(config(item(inputs=bad))) == [], bad


def test_cwd_must_be_a_relative_path_inside_the_repo():
    """An empty `cwd`, an absolute one, or one holding a `..` segment escapes or ignores the
    repo: the item is skipped."""
    for bad in ("", "/abs", "a/../b"):
        assert load_generators(config(item(cwd=bad))) == [], bad


def test_malformed_new_key_does_not_skip_the_valid_neighbours():
    """One item with a bad `cwd` is dropped on its own; the well-formed items around it keep
    loading in order."""
    gens = load_generators(config(
        item(cwd="web"),
        item(path="uv.lock", cwd="../outside"),
        item(path="generated.json", timeout=90, inputs=["pyproject.toml"]),
    ))
    assert [g.path for g in gens] == ["web/package-lock.json", "generated.json"]
    assert gens[0].cwd == "web"
    assert gens[1].timeout == 90
    assert gens[1].inputs == ("pyproject.toml",)


# --- the run seam: timeout / cwd / capture_output, the timeout + missing-binary reasons,
#     and the conflicted-input precondition --------------------------------------------

LOCK = "web/package-lock.json"


def hard_repo(tmp_path, name="repo"):
    """A fresh repo under `tmp_path/name`, created idempotently, with the lockfile target and
    its declared input already on disk."""
    repo = tmp_path / name
    (repo / "web").mkdir(parents=True, exist_ok=True)
    (repo / LOCK).write_text("ours\n", encoding="utf-8")
    (repo / "web" / "package.json").write_text("{}\n", encoding="utf-8")
    return repo


def hard_gen(repo, **extra):
    """A `Generator` for the repo's lockfile, with `extra` overriding the declared keys."""
    base = {"path": LOCK, "write": ["npm", "install"], "check": None}
    base.update(extra)
    return Generator(**base)


def recorder(answers=None):
    """A fake `run` seam: records every call and answers with `answers` (a list of exceptions
    or CompletedProcess-like results, reused once exhausted with a successful exit 0)."""
    calls = []
    answers = list(answers or [])

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if answers:
            answer = answers.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        return SimpleNamespace(returncode=0)
    return run, calls


def test_run_kwargs_default_and_declared(tmp_path):
    """Every generator run gets `timeout` (the declared one, else `DEFAULT_TIMEOUT`), `cwd`
    (the declared directory, else the repo root) and `capture_output=True`."""
    repo = hard_repo(tmp_path, "undeclared")
    run, calls = recorder()
    text, reason = regenerate_file(repo, hard_gen(repo), "ours\n", "ours\n", run=run)
    assert (text, reason) == ("ours\n", "")
    assert calls, "no run was recorded"
    for argv, kwargs in calls:
        assert kwargs["timeout"] == DEFAULT_TIMEOUT, argv
        assert kwargs["capture_output"] is True, argv
        assert Path(kwargs["cwd"]) == repo, argv

    repo2 = hard_repo(tmp_path, "declared")
    run2, calls2 = recorder()
    gen2 = hard_gen(repo2, timeout=300, cwd="web")
    text, reason = regenerate_file(repo2, gen2, "ours\n", "ours\n", run=run2)
    assert (text, reason) == ("ours\n", "")
    assert calls2
    for argv, kwargs in calls2:
        assert kwargs["timeout"] == 300, argv
        assert kwargs["capture_output"] is True, argv
        assert Path(kwargs["cwd"]) == repo2 / "web", argv


def test_timeout_reason_names_run_and_seconds(tmp_path):
    """A `TimeoutExpired` is a refusal naming which run timed out and after how many seconds:
    the write run at the default 600, the check run at the declared 300."""
    repo = hard_repo(tmp_path, "write-timeout")
    gen = hard_gen(repo)
    expired = subprocess.TimeoutExpired(gen.write, DEFAULT_TIMEOUT)
    run, _ = recorder([expired])
    text, reason = regenerate_file(repo, gen, "ours\n", "ours\n", run=run)
    assert text is None
    assert reason == "write command timed out after 600s"

    repo2 = hard_repo(tmp_path, "check-timeout")
    gen2 = hard_gen(repo2, check=["npm", "ci"], timeout=300)
    expired2 = subprocess.TimeoutExpired(gen2.check, 300)
    run2, _ = recorder([None, None, None, expired2])
    text, reason = regenerate_file(repo2, gen2, "ours\n", "ours\n", run=run2)
    assert text is None
    assert reason == "check command timed out after 300s"


def test_missing_binary_reason(tmp_path):
    """A `FileNotFoundError` from the spawn is a refusal naming the missing binary - the
    argv's first element - not a generic generator failure."""
    repo = hard_repo(tmp_path)
    gen = hard_gen(repo)
    run, _ = recorder([FileNotFoundError(2, "No such file or directory", "npm")])
    text, reason = regenerate_file(repo, gen, "ours\n", "ours\n", run=run)
    assert text is None
    assert reason == "npm not found"


def test_input_conflict_returns_before_any_write(tmp_path):
    """With a conflicted declared input, the refusal comes before anything runs or is written:
    `run` is never called and the target bytes on disk are untouched."""
    repo = hard_repo(tmp_path)
    target = repo / LOCK
    before = target.read_bytes()
    gen = hard_gen(repo, inputs=("web/package.json",))
    run, calls = recorder()
    text, reason = regenerate_file(repo, gen, "ours\n", "theirs\n", run=run,
                                   conflicted=["web/package.json"])
    assert text is None
    assert reason == "input web/package.json is still conflicted"
    assert calls == []
    assert target.read_bytes() == before
    from regenerate import input_conflict
    assert input_conflict(gen, ["web/package.json"]) == \
        "input web/package.json is still conflicted"
    assert input_conflict(gen, ["other/file.md"]) is None
