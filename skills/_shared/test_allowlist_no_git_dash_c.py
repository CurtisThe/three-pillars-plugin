"""Grep guard: skill/agent prose must not teach `git -C "$..."` or `git -C /...`.

Plain `git <verb>` in the run's own worktree is the matchable form; the two
waived files are shell libraries that legitimately use `git -C`.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERN = re.compile(r'git -C ("\$|/)')
WAIVERS = {
    "skills/_shared/seat_resolve_lib.sh",
    "skills/_shared/git_env.sh",
}


def scan(root):
    root = Path(root)
    hits = []
    for top in ("skills", "agents"):
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in (".md", ".sh") or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if path.name.startswith("test_") or "ci_local_tests" in rel.split("/"):
                continue
            if rel in WAIVERS:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if PATTERN.search(line):
                    hits.append(f"{rel}:{n}")
    return hits


def test_real_repo_has_no_git_dash_c_outside_waivers():
    assert scan(ROOT) == []


def test_planted_git_dash_c_is_flagged(tmp_path):
    skill = tmp_path / "skills" / "x" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("ok\nrun git -C /x status\n", encoding="utf-8")
    assert scan(tmp_path) == ["skills/x/SKILL.md:2"]


def test_waived_file_not_flagged(tmp_path):
    lib = tmp_path / "skills" / "_shared" / "git_env.sh"
    lib.parent.mkdir(parents=True)
    lib.write_text("git -C \"$X\" init\n", encoding="utf-8")
    assert scan(tmp_path) == []
