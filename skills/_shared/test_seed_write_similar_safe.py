"""`seed_write.similar` lists only seeds whose directory is a safe slug (followups-1023 2.5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import seed_write as sw  # noqa: E402

QUERY = "watcher idle events"
SEED = "---\nstatus: seed\n---\n# T\n\n## Problem\n\nthe watcher misses idle events\n"


def make_repo(tmp_path) -> Path:
    for name in ("good-seed", "bad seed;rm", "Upper_Case"):
        seed = tmp_path / "three-pillars-docs" / "tp-designs" / name / "seed.md"
        seed.parent.mkdir(parents=True)
        seed.write_text(SEED, encoding="utf-8")
    return tmp_path


def test_similar_skips_a_directory_that_is_not_a_safe_slug(tmp_path):
    repo = make_repo(tmp_path)
    assert [slug for slug, _ in sw.similar(QUERY, repo=repo)] == ["good-seed"]


def test_similar_cli_prints_only_the_safe_slug(tmp_path, capsys):
    repo = make_repo(tmp_path)
    assert sw.main(["similar", QUERY, "--repo", str(repo)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and lines[0].startswith("good-seed ")
