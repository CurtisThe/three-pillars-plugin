"""Tests for migrate.py — old-layout detection and migration plan generation.

Run with: pytest skills/_shared/test_migrate.py -q
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


_LEGACY_DOC_PATH_RE = re.compile(
    r"(?<![a-z-])docs/(?:tdd-designs|completed-tdd-designs|vision\.md|architecture\.md|product_roadmap\.md|known_issues\.md)"
)

import migrate
from migrate import detect, format_plan, main

FIXTURES = Path(__file__).parent / "fixtures"
OLD_LAYOUT_REPO = FIXTURES / "old_layout_repo"
EXPECTED_OLD_LAYOUT_PLAN = FIXTURES / "expected_old_layout_plan.json"
EXPECTED_OLD_LAYOUT_DRY_RUN = FIXTURES / "expected_old_layout_dry_run.txt"


def _hash_tree(root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if ".git" in rel.parts:
            continue
        digests[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _setup_git_repo(tmp_path: Path) -> Path:
    """Copy the fixture into a fresh git repo with one initial commit."""
    repo = tmp_path / "repo"
    shutil.copytree(OLD_LAYOUT_REPO, repo)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    return repo


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _git_status_porcelain(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture(scope="module")
def expected_old_layout_plan():
    return json.loads(EXPECTED_OLD_LAYOUT_PLAN.read_text())


def test_detect_returns_plan_matching_hardcoded_fixture(expected_old_layout_plan):
    """The fixture was hand-authored before migrate.py — this is NOT a self-snapshot."""
    plan = detect(OLD_LAYOUT_REPO)
    assert plan.to_dict() == expected_old_layout_plan


def test_detect_returns_empty_for_new_layout(tmp_path):
    (tmp_path / "three-pillars-docs").mkdir()
    (tmp_path / "three-pillars-docs" / "vision.md").write_text("# Vision\n")
    (tmp_path / "three-pillars-docs" / "tp-designs").mkdir()
    (tmp_path / "CLAUDE.md").write_text("Use /tp-setup to begin.\n")

    plan = detect(tmp_path)

    assert plan.is_empty(), f"expected empty plan, got {plan.to_dict()}"


def test_rewrite_content_does_not_corrupt_already_migrated_paths():
    """`text.replace("docs/vision.md", ...)` would otherwise match the suffix of
    `three-pillars-docs/vision.md` and produce `three-pillars-three-pillars-docs/`.
    The detector AND rewriter must both anchor on a word boundary that excludes
    the `three-pillars-` prefix.
    """
    import migrate
    cases = [
        "See three-pillars-docs/vision.md for the why.",
        "Old: docs/vision.md is legacy; New: three-pillars-docs/vision.md is current.",
        "Path under three-pillars-docs/tp-designs/foo/design.md stays put.",
        "Reference to three-pillars-docs/architecture.md is already correct.",
    ]
    for text in cases:
        result = migrate._rewrite_content(text)
        assert "three-pillars-three-pillars-" not in result, (
            f"rewrite corrupted an already-migrated path:\n  in:  {text!r}\n  out: {result!r}"
        )
    # Idempotency: rewriting twice should be identical to rewriting once.
    for text in cases:
        once = migrate._rewrite_content(text)
        twice = migrate._rewrite_content(once)
        assert once == twice, f"rewrite not idempotent on:\n  in: {text!r}\n  once: {once!r}\n  twice: {twice!r}"


def test_detect_excludes_fixtures_dir_from_rewrites(tmp_path):
    """Migration-tool fixtures intentionally embed legacy patterns as test
    input. _collect_rewrites must skip any path under a `fixtures/` directory
    so apply() doesn't destroy the test corpus.
    """
    (tmp_path / "three-pillars-docs").mkdir()
    (tmp_path / "three-pillars-docs" / "vision.md").write_text("# Vision\n")
    (tmp_path / "three-pillars-docs" / "tp-designs").mkdir()
    # Real rewrite target.
    (tmp_path / "CLAUDE.md").write_text("Run `/tdd-setup` first.\n")
    # Fixture-style file under a nested fixtures/ dir — must be excluded.
    (tmp_path / "skills" / "_shared" / "fixtures" / "old_layout_repo").mkdir(parents=True)
    (tmp_path / "skills" / "_shared" / "fixtures" / "old_layout_repo" / "CLAUDE.md").write_text(
        "Use `/tdd-setup` to begin.\n"
    )

    plan = detect(tmp_path)

    assert plan.rewrites == ["CLAUDE.md"], (
        f"expected only top-level CLAUDE.md in rewrites, got {plan.rewrites}"
    )


def test_detect_skips_first_run_md_self_documenting_legacy(tmp_path):
    """skills/_shared/first-run.md documents what migrate.py LOOKS FOR (the
    legacy `docs/tdd-designs/` markers). Rewriting it would invert the doc's
    meaning — the trigger description would point at the post-migration layout.
    """
    (tmp_path / "three-pillars-docs").mkdir()
    (tmp_path / "three-pillars-docs" / "vision.md").write_text("# Vision\n")
    (tmp_path / "three-pillars-docs" / "tp-designs").mkdir()
    (tmp_path / "CLAUDE.md").write_text("Use `/tdd-setup`.\n")
    (tmp_path / "skills" / "_shared").mkdir(parents=True)
    (tmp_path / "skills" / "_shared" / "first-run.md").write_text(
        "Triggers: presence of `docs/tdd-designs/` or `docs/vision.md`.\n"
    )

    plan = detect(tmp_path)

    assert "skills/_shared/first-run.md" not in plan.rewrites, (
        f"first-run.md must not be in rewrite plan; got {plan.rewrites}"
    )


def test_detect_does_not_flag_already_migrated_paths_for_rewrite(tmp_path):
    """A file containing only the new `three-pillars-docs/...` paths must not
    be picked up by _collect_rewrites. The detector regex must use the same
    word-boundary as the rewriter.
    """
    (tmp_path / "three-pillars-docs").mkdir()
    (tmp_path / "three-pillars-docs" / "vision.md").write_text("# Vision\n")
    (tmp_path / "three-pillars-docs" / "tp-designs").mkdir()
    # Stale-looking content but the path is already on the new layout.
    (tmp_path / "CLAUDE.md").write_text(
        "Read `three-pillars-docs/vision.md` first. Architecture is in `three-pillars-docs/architecture.md`.\n"
    )

    plan = detect(tmp_path)

    assert plan.is_empty(), (
        f"detect() flagged already-migrated paths for rewrite — false positive on "
        f"three-pillars-docs/* substring. Plan: {plan.to_dict()}"
    )


def test_detect_collects_rewrites_without_moves_for_partial_migration(tmp_path):
    """A repo whose filesystem was already migrated but whose text content still
    has stale skill-name references is a partial-migration state — detect()
    must return a plan with rewrites (and no moves) so apply() can clean it up.

    This case happens on a repo that was hand-migrated (e.g., `git mv docs ...`)
    before migrate.py existed: layout markers are gone, but CLAUDE.md /
    README.md still reference `/tdd-*` skill names.
    """
    (tmp_path / "three-pillars-docs").mkdir()
    (tmp_path / "three-pillars-docs" / "vision.md").write_text("# Vision\n")
    (tmp_path / "three-pillars-docs" / "tp-designs").mkdir()
    # No docs/ legacy markers — but stray refs in shipped root files.
    (tmp_path / "CLAUDE.md").write_text("Run `/tdd-setup` first.\n")
    (tmp_path / "README.md").write_text("See `/tdd-design` to begin.\n")

    plan = detect(tmp_path)

    assert not plan.is_empty(), "rewrites-only state must produce a non-empty plan"
    assert plan.moves == [], f"expected zero moves, got {plan.moves}"
    assert set(plan.rewrites) == {"CLAUDE.md", "README.md"}, (
        f"expected rewrites for CLAUDE.md and README.md, got {plan.rewrites}"
    )


def test_detect_includes_all_old_paths_no_extras(expected_old_layout_plan):
    """Every file under docs/ in the fixture must appear as a move src; nothing outside docs/ should."""
    plan = detect(OLD_LAYOUT_REPO)
    move_srcs = {src for src, _ in plan.moves}

    fixture_docs_files = {
        str(p.relative_to(OLD_LAYOUT_REPO).as_posix())
        for p in OLD_LAYOUT_REPO.rglob("*")
        if p.is_file() and p.relative_to(OLD_LAYOUT_REPO).parts[0] == "docs"
    }

    assert move_srcs == fixture_docs_files, (
        f"move sources diverge from fixture's docs/ contents.\n"
        f"missing: {fixture_docs_files - move_srcs}\n"
        f"extras: {move_srcs - fixture_docs_files}"
    )

    for src, _ in plan.moves:
        assert src.startswith("docs/"), f"move source {src!r} is outside docs/"


def test_dry_run_no_filesystem_change(tmp_path):
    """Running --dry-run on a copy of the fixture must leave every byte untouched."""
    work = tmp_path / "repo"
    shutil.copytree(OLD_LAYOUT_REPO, work)

    before = _hash_tree(work)
    exit_code = main(["--dry-run", "--repo", str(work)])
    after = _hash_tree(work)

    assert exit_code == 0
    assert before == after, "dry-run mutated the filesystem"


def test_dry_run_output_diff_against_hardcoded_fixture(capsys):
    """The stdout of --dry-run on the fixture must byte-match the hand-authored expected output."""
    exit_code = main(["--dry-run", "--repo", str(OLD_LAYOUT_REPO)])
    captured = capsys.readouterr()

    expected = EXPECTED_OLD_LAYOUT_DRY_RUN.read_text()
    assert exit_code == 0
    assert captured.out == expected, (
        "dry-run stdout diverged from hardcoded fixture:\n"
        f"---expected---\n{expected}\n---actual---\n{captured.out}"
    )


def test_apply_moves_files_via_git_mv(tmp_path):
    """--apply moves every file in plan.moves and creates a migration commit. git history follows."""
    repo = _setup_git_repo(tmp_path)
    pre_head = _git_head(repo)

    exit_code = main(["--apply", "--repo", str(repo)])

    assert exit_code == 0, "apply failed"

    # Old paths gone, new paths present.
    assert not (repo / "docs").exists() or not any((repo / "docs").iterdir()), (
        "old docs/ tree should be empty after migration"
    )
    assert (repo / "three-pillars-docs" / "vision.md").is_file()
    assert (repo / "three-pillars-docs" / "tp-designs" / "sample" / "design.md").is_file()
    assert (repo / "three-pillars-docs" / "tp-designs" / "sample" / "lock.json").is_file()
    assert (repo / "three-pillars-docs" / "completed-tp-designs" / "old-feature" / "design.md").is_file()

    # A migration commit landed.
    post_head = _git_head(repo)
    assert post_head != pre_head, "no migration commit was created"

    # git --follow tracks across the rename — vision.md history reaches the initial commit.
    log = subprocess.run(
        ["git", "log", "--follow", "--oneline", "three-pillars-docs/vision.md"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    assert len(log.stdout.strip().splitlines()) >= 2, "git --follow did not see the rename"


def test_apply_atomic_on_mid_failure_leaves_old_state(tmp_path, monkeypatch):
    """If a move fails mid-flight, rollback restores byte-exact pre-apply state and creates no commit."""
    repo = _setup_git_repo(tmp_path)
    pre_head = _git_head(repo)
    pre_status = _git_status_porcelain(repo)
    pre_hashes = _hash_tree(repo)

    original_git_mv = migrate._git_mv
    call_count = {"n": 0}

    def failing_git_mv(src: str, dst: str, repo_path: Path) -> None:
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["git", "mv", src, dst],
                stderr="injected failure",
            )
        return original_git_mv(src, dst, repo_path)

    monkeypatch.setattr(migrate, "_git_mv", failing_git_mv)

    exit_code = main(["--apply", "--repo", str(repo)])

    assert exit_code != 0, "apply should report failure"
    assert _git_head(repo) == pre_head, "rollback failed to prevent a commit"
    assert _git_status_porcelain(repo) == pre_status, (
        f"rollback left git status dirty:\n---pre---\n{pre_status}\n---post---\n{_git_status_porcelain(repo)}"
    )
    assert _hash_tree(repo) == pre_hashes, "rollback failed to restore byte-exact state"


def test_apply_rewrites_only_target_paths(tmp_path):
    """After --apply, target patterns are replaced in scoped files and only there."""
    repo = _setup_git_repo(tmp_path)
    exit_code = main(["--apply", "--repo", str(repo)])
    assert exit_code == 0

    claude = (repo / "CLAUDE.md").read_text()
    assert "/tdd-" not in claude, "CLAUDE.md still has /tdd- skill refs"
    assert "/tp-setup" in claude
    assert "/tp-design" in claude
    assert not _LEGACY_DOC_PATH_RE.search(claude), "CLAUDE.md still has legacy docs/ paths"
    assert "three-pillars-docs/tp-designs/" in claude
    assert "three-pillars-docs/vision.md" in claude

    moved_design = (repo / "three-pillars-docs" / "tp-designs" / "sample" / "design.md").read_text()
    assert "/tdd-design" not in moved_design
    assert "/tp-design" in moved_design
    assert not _LEGACY_DOC_PATH_RE.search(moved_design)
    assert "three-pillars-docs/tp-designs/sample/plan.md" in moved_design
    assert not re.search(r"\btdd/sample\b", moved_design)
    assert "tp/sample" in moved_design

    moved_plan = (repo / "three-pillars-docs" / "tp-designs" / "sample" / "plan.md").read_text()
    assert "/tdd-phase-implement" not in moved_plan
    assert "/tp-phase-implement" in moved_plan
    assert not _LEGACY_DOC_PATH_RE.search(moved_plan)
    assert "three-pillars-docs/vision.md" in moved_plan


def test_apply_skips_unrelated_docs_paths(tmp_path):
    """Files containing unrelated `docs/whatever/` mentions and bare `tdd` words must not be touched."""
    repo = _setup_git_repo(tmp_path)
    pre_unrelated = (repo / "unrelated.md").read_text()

    exit_code = main(["--apply", "--repo", str(repo)])
    assert exit_code == 0

    post_unrelated = (repo / "unrelated.md").read_text()
    assert post_unrelated == pre_unrelated, "unrelated.md was modified despite having no target patterns"


def test_apply_rewrites_claude_md_and_claude_plugin_md(tmp_path):
    """Both CLAUDE.md and CLAUDE.plugin.md are in rewrite scope."""
    repo = _setup_git_repo(tmp_path)
    exit_code = main(["--apply", "--repo", str(repo)])
    assert exit_code == 0

    for fname in ("CLAUDE.md", "CLAUDE.plugin.md"):
        content = (repo / fname).read_text()
        assert "/tdd-" not in content, f"{fname} still has /tdd- refs after migration"
        assert not _LEGACY_DOC_PATH_RE.search(content), f"{fname} still has legacy docs/ paths"


def test_apply_rewrites_readme_and_readme_plugin(tmp_path):
    """Both README.md and README.plugin.md are in rewrite scope."""
    repo = _setup_git_repo(tmp_path)
    exit_code = main(["--apply", "--repo", str(repo)])
    assert exit_code == 0

    for fname in ("README.md", "README.plugin.md"):
        content = (repo / fname).read_text()
        assert "/tdd-" not in content, f"{fname} still has /tdd- refs after migration"
        assert not _LEGACY_DOC_PATH_RE.search(content), f"{fname} still has legacy docs/ paths"


def test_apply_twice_is_no_op(tmp_path):
    """First --apply migrates and creates a commit. Second --apply is silently a no-op."""
    repo = _setup_git_repo(tmp_path)

    exit1 = main(["--apply", "--repo", str(repo)])
    assert exit1 == 0
    head_after_first = _git_head(repo)

    exit2 = main(["--apply", "--repo", str(repo)])
    assert exit2 == 0, "second --apply should exit 0"
    head_after_second = _git_head(repo)
    assert head_after_first == head_after_second, "second --apply created a new commit"


def test_apply_on_migrated_repo_exits_clean(tmp_path, capsys):
    """A repo whose config records completed_at is treated as already migrated even if stale legacy paths exist."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".three-pillars").mkdir()
    (repo / ".three-pillars" / "config.json").write_text(json.dumps({
        "schema_version": 1,
        "migration": {"completed_at": "2026-01-01T00:00:00Z", "from_layout": "docs+tdd"},
    }))
    (repo / "docs").mkdir()
    (repo / "docs" / "vision.md").write_text("# Stale legacy vision\n")

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    pre_head = _git_head(repo)

    exit_code = main(["--apply", "--repo", str(repo)])

    assert exit_code == 0
    assert _git_head(repo) == pre_head, "apply on migrated repo created a commit"
    assert (repo / "docs" / "vision.md").is_file(), "stale legacy file was incorrectly migrated"


def test_apply_owns_completed_at_write_atomically_at_end(tmp_path):
    """--apply itself writes config.migration.completed_at; the write lands in the same commit as moves."""
    repo = _setup_git_repo(tmp_path)
    exit_code = main(["--apply", "--repo", str(repo)])
    assert exit_code == 0

    config_path = repo / ".three-pillars" / "config.json"
    assert config_path.is_file(), "migrate did not create .three-pillars/config.json"
    config = json.loads(config_path.read_text())
    assert config.get("schema_version") == 1
    assert config["migration"]["completed_at"] is not None, "completed_at not written"
    assert config["migration"]["from_layout"] == "docs+tdd"

    log = subprocess.run(
        ["git", "log", "-1", "--name-only", "--pretty=format:"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    assert ".three-pillars/config.json" in log.stdout, (
        f"config.json was not in the migration commit:\n{log.stdout}"
    )


def test_apply_does_not_rewrite_lock_json_branch_field(tmp_path):
    """lock.json files are JSON, not markdown — their branch field must be grandfathered through migration."""
    repo = _setup_git_repo(tmp_path)
    pre_lock = json.loads((repo / "docs" / "tdd-designs" / "sample" / "lock.json").read_text())
    assert pre_lock["branch"] == "tdd/sample"

    exit_code = main(["--apply", "--repo", str(repo)])
    assert exit_code == 0

    post_lock = json.loads(
        (repo / "three-pillars-docs" / "tp-designs" / "sample" / "lock.json").read_text()
    )
    assert post_lock["branch"] == "tdd/sample", f"lock.json branch was rewritten: {post_lock['branch']!r}"
    assert post_lock == pre_lock, "lock.json content was modified during migration"


def test_apply_does_not_run_git_branch_m(tmp_path, monkeypatch):
    """migrate.py must never invoke git branch -m — in-flight branches are grandfathered."""
    repo = _setup_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "tdd/sample"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)

    branch_rename_call = {"args": None}
    original_run = subprocess.run

    def spy_run(args, *rest, **kwargs):
        if (
            isinstance(args, (list, tuple))
            and len(args) >= 3
            and args[0] == "git"
            and args[1] == "branch"
            and args[2] in ("-m", "-M", "--move")
        ):
            branch_rename_call["args"] = list(args)
        return original_run(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy_run)

    exit_code = main(["--apply", "--repo", str(repo)])
    assert exit_code == 0
    assert branch_rename_call["args"] is None, (
        f"migrate.py invoked a branch rename: {branch_rename_call['args']!r}"
    )


def test_apply_prints_memory_md_advisory_to_stdout(tmp_path, capsys):
    """After successful --apply, stdout must contain the MEMORY.md advisory line."""
    repo = _setup_git_repo(tmp_path)
    exit_code = main(["--apply", "--repo", str(repo)])
    captured = capsys.readouterr()

    assert exit_code == 0
    advisory = "MEMORY.md and user-level CLAUDE.md may reference old tdd-* skill names — review manually."
    assert advisory in captured.out, f"advisory missing from stdout:\n{captured.out}"


def test_apply_handles_claude_last_design_when_present(tmp_path, capsys):
    """When .claude/last-design exists, --apply prints an advisory but does NOT
    rewrite the file. MRU entries are design names (leaf folder names), which
    remain valid post-migration — only the parent dir was renamed.
    """
    repo = _setup_git_repo(tmp_path)
    last_design = repo / ".claude" / "last-design"
    last_design.parent.mkdir(parents=True, exist_ok=True)
    last_design.write_text("my-active-design\nolder-design\n")
    before_content = last_design.read_text()
    # Commit so _ensure_clean_repo passes; the apply test still gets to
    # observe the file's pre/post content because the migration won't touch it.
    subprocess.run(["git", "add", ".claude/last-design"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add last-design"], cwd=repo, check=True)

    exit_code = main(["--apply", "--repo", str(repo)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert (
        ".claude/last-design references active designs at the old path — "
        "re-check via /tp-session-restore"
    ) in captured.out, f"last-design advisory missing from stdout:\n{captured.out}"
    assert last_design.read_text() == before_content, (
        ".claude/last-design content must be preserved verbatim — it's an MRU "
        "of design names, not paths, and remains valid post-migration"
    )


def test_apply_silent_when_claude_last_design_absent(tmp_path, capsys):
    """When .claude/last-design is absent, the last-design advisory line must
    not appear. Other advisory lines (MEMORY.md, etc.) are unaffected.
    """
    repo = _setup_git_repo(tmp_path)
    assert not (repo / ".claude" / "last-design").exists()

    exit_code = main(["--apply", "--repo", str(repo)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "references active designs at the old path" not in captured.out, (
        f"unexpected last-design advisory in stdout:\n{captured.out}"
    )


def test_git_branch_list_unchanged_before_and_after_apply(tmp_path):
    """git branch --list output is byte-identical before and after --apply."""
    repo = _setup_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "tdd/sample"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)

    pre = subprocess.run(
        ["git", "branch", "--list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout

    exit_code = main(["--apply", "--repo", str(repo)])
    assert exit_code == 0

    post = subprocess.run(
        ["git", "branch", "--list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert pre == post, (
        f"git branch --list changed across --apply:\n---pre---\n{pre}\n---post---\n{post}"
    )
