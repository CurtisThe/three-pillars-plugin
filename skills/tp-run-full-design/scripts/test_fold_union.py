"""fold_union: resolve a decisions.md-only fold conflict by append-only union."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fold_union  # noqa: E402

DEC = "three-pillars-docs/tp-designs/demo/decisions.md"
BASE = "# D\n\n### [x] one\nbody\n"


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def write(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


def make_repo(tmp_path, tp_edit, cand_edit, path=DEC, base=BASE, extra=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, path, base)
    if extra:
        write(repo, "a.txt", "base\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "cand")
    write(repo, path, cand_edit)
    if extra:
        write(repo, "a.txt", "cand\n")
    commit(repo, "cand")
    git(repo, "checkout", "-q", "-b", "tp/demo", "main")
    write(repo, path, tp_edit)
    if extra:
        write(repo, "a.txt", "tp\n")
    commit(repo, "tp")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "merge", "--no-ff", "cand", check=False)
    return repo


@pytest.fixture
def appended(tmp_path):
    return make_repo(tmp_path, BASE + "\n### [tp] two\nt\n", BASE + "\n### [cand] three\nc\n")


def test_resolved(appended, capsys):
    res = fold_union.resolve_fold(str(appended), "demo")
    assert res["status"] == "resolved"
    text = (appended / DEC).read_text(encoding="utf-8")
    assert text.startswith(BASE)
    i, j, k = text.index("[tp] two"), text.index("[cand] three"), text.index(
        "### [tp-run-full-design/tier-5.6] fold-decisions-union")
    assert i < j < k
    assert git(appended, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""
    assert (appended / ".git" / "MERGE_HEAD").exists()
    assert fold_union.main(["--slug", "demo", "--repo", str(appended)]) in (0, 1)


def test_main_prints_json_and_zero(appended, capsys):
    assert fold_union.main(["--slug", "demo", "--repo", str(appended)]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["status"] == "resolved"


def test_other_path_also_conflicting(tmp_path):
    repo = make_repo(tmp_path, BASE + "\n### [tp] two\nt\n", BASE + "\n### [cand] three\nc\n", extra=True)
    before = (repo / DEC).read_bytes()
    assert fold_union.resolve_fold(str(repo), "demo")["status"] == "not-applicable"
    assert (repo / DEC).read_bytes() == before
    assert b"<<<<<<<" in before
    assert fold_union.main(["--slug", "demo", "--repo", str(repo)]) == 1


def test_not_pure_append(tmp_path):
    repo = make_repo(tmp_path, "# D\n\n### [x] ONE\nbody\n", "# D\n\n### [x] uno\nbody\n")
    before = (repo / DEC).read_bytes()
    assert fold_union.resolve_fold(str(repo), "demo")["status"] == "not-applicable"
    assert (repo / DEC).read_bytes() == before


def test_slug_mismatch(tmp_path):
    other = "three-pillars-docs/tp-designs/other/decisions.md"
    repo = make_repo(tmp_path, BASE + "\n### [tp] two\nt\n", BASE + "\n### [cand] three\nc\n", path=other)
    assert fold_union.resolve_fold(str(repo), "demo")["status"] == "not-applicable"


def test_dropped_line(appended, monkeypatch):
    monkeypatch.setattr(fold_union, "union_decisions", lambda b, o, t: o)
    before = (appended / DEC).read_bytes()
    res = fold_union.resolve_fold(str(appended), "demo")
    assert res["status"] == "not-applicable" and res["reason"] == "dropped-line"
    assert (appended / DEC).read_bytes() == before


def test_no_merge(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    assert fold_union.resolve_fold(str(repo), "demo")["status"] == "not-applicable"
    assert fold_union.main(["--slug", "demo", "--repo", str(repo)]) == 1


def test_bad_slug(tmp_path):
    assert fold_union.main(["--slug", "../x", "--repo", str(tmp_path)]) == 2
