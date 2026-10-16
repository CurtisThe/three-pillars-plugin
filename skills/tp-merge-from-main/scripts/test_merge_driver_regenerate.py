"""`merge_back` regenerates declared generated files (config `merge_from_main.generators`).

A `plugin.json`-style file whose merge conflicts only in the part its generator rebuilds is
auto-resolved and staged; any other difference defers with git's conflict markers put back. The
fake generator rebuilds the `agents` array from `agents/*.md` and keeps every other key.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

PLUGIN = "plugin.json"
CONFIG = ".three-pillars/config.json"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

GEN = '''
import json
from pathlib import Path
p = Path("plugin.json")
data = json.loads(p.read_text(encoding="utf-8"))
data["agents"] = sorted(x.stem for x in Path("agents").glob("*.md"))
p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
'''
# Same rebuild, but it also edits a tracked file outside the declared path.
GEN_TOUCH = GEN + 'Path("README.md").write_text("generator wrote this\\n", encoding="utf-8")\n'
# Rewrites a file that is already conflicted (and so already dirty) when the generator runs.
GEN_CLOBBER = GEN + 'Path("zzz.txt").write_text("generator wrote this\\n", encoding="utf-8")\n'


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


def plugin_text(agents, version="1.0"):
    return json.dumps({"agents": agents, "version": version}, indent=2, sort_keys=True) + "\n"


def declare(script="gen.py"):
    gens = [{"path": PLUGIN, "write": [sys.executable, script]}]
    return json.dumps({"merge_from_main": {"generators": gens}})


def setup(tmp_path, *, cfg=None, theirs_version="1.0", extra_conflict=False):
    """`design` and `master` each add one agent file and the matching array entry after `a`."""
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    for name, body in (("gen.py", GEN), ("gen_touch.py", GEN_TOUCH), ("gen_clobber.py", GEN_CLOBBER), ("README.md", "readme\n"),
                       (CONFIG, declare() if cfg is None else cfg), ("agents/a.md", "a\n"),
                       (PLUGIN, plugin_text(["a"])), ("zzz.txt", "base\n")):
        write(repo, name, body)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, "agents/b.md", "b\n")
    write(repo, PLUGIN, plugin_text(["a", "b"]))
    if extra_conflict:
        write(repo, "zzz.txt", "ours\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, "agents/c.md", "c\n")
    write(repo, PLUGIN, plugin_text(["a", "c"], theirs_version))
    if extra_conflict:
        write(repo, "zzz.txt", "theirs\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    return repo


def unmerged(repo):
    return git(repo, "diff", "--name-only", "--diff-filter=U").stdout.split()


def outcome(report, path):
    return next(o for o in report.outcomes if o["path"] == path)


def test_roster_conflict_is_regenerated_and_staged(tmp_path):
    repo = setup(tmp_path)
    report = merge_back(str(repo), "master")
    o = outcome(report, PLUGIN)
    assert o["action"] == "auto-resolved", report.to_json()
    assert o["resolved_classes"] == ["regenerate"]
    assert PLUGIN in report.auto_resolved and PLUGIN not in unmerged(repo)
    text = (repo / PLUGIN).read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert json.loads(text)["agents"] == ["a", "b", "c"]


def test_other_deferred_files_do_not_block_and_are_processed_first(tmp_path):
    # `zzz.txt` conflicts too: it sorts after plugin.json but is reported before it, and its
    # markers (dirty before and after the run, unchanged) are not "another file the generator
    # changed".
    repo = setup(tmp_path, extra_conflict=True)
    report = merge_back(str(repo), "master")
    assert [o["path"] for o in report.outcomes] == ["zzz.txt", PLUGIN], report.to_json()
    assert outcome(report, PLUGIN)["action"] == "auto-resolved"
    assert outcome(report, "zzz.txt")["reason"] == "non-living-doc conflict — always human"
    assert "<<<<<<<" in (repo / "zzz.txt").read_text(encoding="utf-8")


def test_version_bump_on_one_side_defers_with_markers_restored(tmp_path):
    repo = setup(tmp_path, theirs_version="1.1")
    report = merge_back(str(repo), "master")
    o = outcome(report, PLUGIN)
    assert o["action"] == "deferred", report.to_json()
    assert o["reason"].startswith("generated file could not be regenerated")
    assert PLUGIN in report.deferred and report.needs_human
    assert PLUGIN in unmerged(repo)
    assert "<<<<<<<" in (repo / PLUGIN).read_text(encoding="utf-8")


def test_generator_that_changes_another_file_defers_and_restores_it(tmp_path):
    repo = setup(tmp_path, cfg=declare("gen_touch.py"))
    report = merge_back(str(repo), "master")
    o = outcome(report, PLUGIN)
    assert o["action"] == "deferred", report.to_json()
    assert o["reason"].startswith("generated file could not be regenerated")
    assert "README.md" in o["reason"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "readme\n"
    assert set(git(repo, "diff", "--name-only").stdout.split()) == {PLUGIN}
    assert PLUGIN in unmerged(repo)
    assert "<<<<<<<" in (repo / PLUGIN).read_text(encoding="utf-8")


def test_generator_that_rewrites_a_conflicted_file_gets_its_markers_back(tmp_path):
    repo = setup(tmp_path, cfg=declare("gen_clobber.py"), extra_conflict=True)
    report = merge_back(str(repo), "master")
    assert outcome(report, PLUGIN)["action"] == "deferred", report.to_json()
    assert "zzz.txt" in outcome(report, PLUGIN)["reason"]
    assert "<<<<<<<" in (repo / "zzz.txt").read_text(encoding="utf-8")
    assert "<<<<<<<" in (repo / PLUGIN).read_text(encoding="utf-8")


def test_without_the_config_key_the_file_stays_human(tmp_path):
    repo = setup(tmp_path, cfg="{}")
    report = merge_back(str(repo), "master")
    o = outcome(report, PLUGIN)
    assert o["action"] == "deferred" and o["kind"] == "other"
    assert o["reason"] == "non-living-doc conflict — always human"


def test_unreadable_config_means_no_generators(tmp_path):
    repo = setup(tmp_path, cfg="{not json")
    report = merge_back(str(repo), "master")
    o = outcome(report, PLUGIN)
    assert o["action"] == "deferred" and o["kind"] == "other"
    assert o["reason"] == "non-living-doc conflict — always human"
