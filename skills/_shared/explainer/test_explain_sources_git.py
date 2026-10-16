"""test_explain_sources_git.py — the git evidence readers.

Covers explainer-agent plan Task 4.2 (detailed-design §Interfaces: "Ref ids
are closed and stable: ... diffstat, tree:<dir> (sibling names in each touched
dir, capped), config:diff ... Every reader is best-effort: a missing source
adds no item and never raises."):
  - git_items(root, base) gives diffstat naming each changed path;
  - tree:<dir> per touched dir lists the sibling names in that dir, capped at
    TREE_CAP names;
  - config:diff holds the added "+" lines of .three-pillars/config.json, and
    is absent when the config did not change;
  - the ref list is deterministic across calls;
  - base=None, a bad base, or a root outside a git repo give [] and nothing
    raises.

Every repo is built under tmp_path; git runs with the shipped
task_scope._git_env scrub (git_env is dev-only), so no repo docs are read
(skills/_shared/test-fragility.md).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_sources as es  # noqa: E402
from task_scope import _git_env  # noqa: E402 — git_env is dev-only

_ENV = _git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
# The git ref ids of the closed grammar (detailed-design §Interfaces).
GIT_REF = re.compile(r"^(diffstat|config:diff|tree:\S+)$")
CONFIG = ".three-pillars/config.json"
ADDED_KEY = "explainer_added_key"


def _git(root: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false",
         "-c", f"core.hooksPath={root}/.no-hooks", *argv],
        cwd=str(root), env=_ENV, check=True, capture_output=True, text=True,
    ).stdout


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _commit(root: Path, msg: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    return _git(root, "rev-parse", "HEAD").strip()


def _sibling_names(count: int) -> list[str]:
    # Fixed width, so no name is a substring of another.
    return [f"m{i:03d}.py" for i in range(count)]


@pytest.fixture
def repo(tmp_path):
    """A repo with a base commit, then a commit adding pkg/a.py and a config
    key. pkg/ holds more siblings than TREE_CAP."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root, "README.md", "readme\n")
    _write(root, CONFIG, json.dumps({"keep": 1}, indent=2) + "\n")
    for name in _sibling_names(es.TREE_CAP + 5):
        _write(root, f"pkg/{name}", "x = 1\n")
    base = _commit(root, "base")
    _write(root, "pkg/a.py", "a = 1\n")
    _write(root, CONFIG,
           json.dumps({"keep": 1, ADDED_KEY: True}, indent=2) + "\n")
    _commit(root, "change")
    return root, base


def _by_ref(items: list[dict]) -> dict:
    return {i["ref"]: i for i in items}


def test_git_items_give_diffstat_tree_and_config_diff(repo):
    root, base = repo
    items = es.git_items(root, base)
    by_ref = _by_ref(items)
    assert {"diffstat", "tree:pkg", "config:diff"} <= set(by_ref)
    for item in items:
        assert GIT_REF.match(item["ref"]), item["ref"]
        assert set(item) == {"ref", "label", "text"}
        assert isinstance(item["label"], str) and item["label"]
        assert isinstance(item["text"], str) and item["text"]
    assert "pkg/a.py" in by_ref["diffstat"]["text"]


def test_tree_item_lists_sibling_names_capped(repo):
    root, base = repo
    text = _by_ref(es.git_items(root, base))["tree:pkg"]["text"]
    names = ["a.py", *_sibling_names(es.TREE_CAP + 5)]
    listed = [n for n in names if n in text]
    assert len(listed) == es.TREE_CAP
    assert "pkg/" not in text  # names, not paths


def test_tree_item_lists_every_name_of_a_small_dir(repo):
    root, base = repo
    by_ref = _by_ref(es.git_items(root, base))
    assert "config.json" in by_ref["tree:.three-pillars"]["text"]


def test_config_diff_holds_only_the_added_lines(repo):
    root, base = repo
    text = _by_ref(es.git_items(root, base))["config:diff"]["text"]
    assert ADDED_KEY in text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines and all(ln.startswith("+") for ln in lines)
    assert not any(ln.startswith("+++") for ln in lines)


def test_no_config_change_gives_no_config_diff(repo):
    root, _ = repo
    head = _git(root, "rev-parse", "HEAD").strip()
    _write(root, "pkg/b.py", "b = 1\n")
    _commit(root, "no config change")
    refs = [i["ref"] for i in es.git_items(root, head)]
    assert "diffstat" in refs and "tree:pkg" in refs
    assert "config:diff" not in refs


def test_ref_list_is_stable_across_calls(repo):
    root, base = repo
    first = [i["ref"] for i in es.git_items(root, base)]
    second = [i["ref"] for i in es.git_items(root, base)]
    assert first == second
    trees = [r for r in first if r.startswith("tree:")]
    assert trees == sorted(trees)


def test_no_base_gives_nothing(repo):
    root, _ = repo
    assert es.git_items(root, None) == []


def test_unknown_base_gives_nothing(repo):
    root, _ = repo
    assert es.git_items(root, "no-such-ref-anywhere") == []


def test_outside_a_git_repo_gives_nothing(tmp_path, monkeypatch):
    # Stop git discovery at tmp_path, so an enclosing checkout never counts.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    plain = tmp_path / "plain"
    plain.mkdir()
    assert es.git_items(plain, "HEAD") == []
    assert es.git_items(tmp_path / "missing", "HEAD") == []
