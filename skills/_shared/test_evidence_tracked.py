"""Unit tests for evidence_tracked.py — Demo Reference table path checker.

Covers the adversarial corpus that real Demo Reference tables use: brace-expansion
cells, glob cells, multi-fragment cells, trailing-slash dirs, header/separator rows,
URLs, and prose-only sections.

Run with: python -m pytest skills/_shared/test_evidence_tracked.py -q
"""

import subprocess
import sys
import tempfile
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_spike_repo(files_to_track: list[str], files_untracked: list[str]) -> Path:
    """Create a hermetic temp git repo with specific files tracked or untracked.

    Tracked files are `git add`ed and committed. Untracked files exist on disk
    but are never added.
    """
    tmpdir = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-b", "main", str(tmpdir)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(tmpdir), "config", "user.email", "test@example.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmpdir), "config", "user.name", "Test"],
                   check=True, capture_output=True)

    for rel in files_to_track:
        p = tmpdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {rel}")
    if files_to_track:
        subprocess.run(["git", "-C", str(tmpdir), "add"] + files_to_track,
                       check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmpdir), "commit", "-m", "initial"],
            check=True, capture_output=True,
        )

    for rel in files_untracked:
        p = tmpdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {rel}")

    return tmpdir


def _run(design_dir: Path) -> tuple[int, str]:
    """Run evidence_tracked.py against design_dir; return (returncode, stdout)."""
    shared = Path(__file__).parent
    script = shared / "evidence_tracked.py"
    result = subprocess.run(
        [sys.executable, str(script), str(design_dir)],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout + result.stderr


def _write_results(design_dir: Path, body: str) -> None:
    (design_dir / "spike-results.md").write_text(body)


# ── Demo Reference tables used in tests ──────────────────────────────────────

_TABLE_HEADER = """\
## Demo Reference
| File | Composition | Demonstrates |
|------|------------|--------------|
"""

# ── test cases ───────────────────────────────────────────────────────────────

def test_a_tracked_path_rc0():
    """(a) Table references a TRACKED demos/x.md → rc 0."""
    repo = _make_spike_repo(["demos/x.md"], [])
    _write_results(repo, _TABLE_HEADER + "| `demos/x.md` | desc | demonstrates |\n")
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (clean). rc={rc}\n{out}"


def test_b_untracked_path_rc1():
    """(b) References an UNTRACKED on-disk demos/y.md → rc 1, offender named."""
    repo = _make_spike_repo([], ["demos/y.md"])
    _write_results(repo, _TABLE_HEADER + "| `demos/y.md` | desc | demonstrates |\n")
    rc, out = _run(repo)
    assert rc == 1, f"Expected rc 1 (offender). rc={rc}\n{out}"
    assert "demos/y.md" in out, f"Expected offender path in output.\n{out}"


def test_c_nonexistent_path_rc1():
    """(c) References a path that does not exist → rc 1."""
    repo = _make_spike_repo([], [])
    _write_results(repo, _TABLE_HEADER + "| `demos/ghost.md` | desc | demonstrates |\n")
    rc, out = _run(repo)
    assert rc == 1, f"Expected rc 1 (nonexistent). rc={rc}\n{out}"
    assert "demos/ghost.md" in out, f"Expected offender path in output.\n{out}"


def test_d_no_spike_results_rc0():
    """(d) No spike-results.md → rc 0 (nothing to check)."""
    repo = _make_spike_repo([], [])
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (no file). rc={rc}\n{out}"


def test_d_prose_only_section_rc0():
    """(d) Prose-only Demo Reference section (no table) → rc 0."""
    repo = _make_spike_repo([], [])
    _write_results(repo, "## Demo Reference\nNo demo files — experiments were all in-memory.\n")
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (prose-only). rc={rc}\n{out}"


def test_d_no_demo_reference_section_rc0():
    """(d) No Demo Reference section at all → rc 0."""
    repo = _make_spike_repo([], [])
    _write_results(repo, "# Results\n\n## Findings\n| # | E | R | I |\n|---|---|---|---|\n")
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (no section). rc={rc}\n{out}"


def test_e_scratch_path_rc1():
    """(e) Untracked path under demos/scratch/ → rc 1 (verdict must not rest on scratch)."""
    repo = _make_spike_repo([], ["demos/scratch/note.txt"])
    _write_results(repo, _TABLE_HEADER + "| `demos/scratch/note.txt` | desc | demonstrates |\n")
    rc, out = _run(repo)
    assert rc == 1, f"Expected rc 1 (scratch untracked). rc={rc}\n{out}"


def test_f_brace_expansion_all_tracked_rc0():
    """(f) Brace-expansion cell run-{1,2,3}/agent.json ALL tracked → rc 0 (no false positive)."""
    tracked = [
        "demos/e1/run-1/agent.json",
        "demos/e1/run-2/agent.json",
        "demos/e1/run-3/agent.json",
    ]
    repo = _make_spike_repo(tracked, [])
    _write_results(
        repo,
        _TABLE_HEADER + "| `demos/e1/run-{1,2,3}/agent.json` | per-run | Agent return |\n",
    )
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (brace all tracked). rc={rc}\n{out}"


def test_f_brace_expansion_some_untracked_rc1():
    """(f) Brace-expansion cell where SOME expansions are untracked → rc 1."""
    repo = _make_spike_repo(["demos/e1/run-1/agent.json"], ["demos/e1/run-2/agent.json"])
    _write_results(
        repo,
        _TABLE_HEADER + "| `demos/e1/run-{1,2}/agent.json` | per-run | Agent return |\n",
    )
    rc, out = _run(repo)
    assert rc == 1, f"Expected rc 1 (some untracked). rc={rc}\n{out}"


def test_g_glob_cell_dir_has_tracked_files_rc0():
    """(g) Glob cell artifacts/* whose dir has tracked files → rc 0."""
    repo = _make_spike_repo(["demos/artifacts/run.json", "demos/artifacts/log.txt"], [])
    _write_results(repo, _TABLE_HEADER + "| `demos/artifacts/*` | all files | Evidence |\n")
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (glob dir tracked). rc={rc}\n{out}"


def test_h_multi_fragment_cell_rc0():
    """(h) Multi-fragment cell `a.yml` + `.txt` — drop bare-suffix .txt, check a.yml → rc 0."""
    repo = _make_spike_repo(["demos/a.yml"], [])
    _write_results(repo, _TABLE_HEADER + "| `demos/a.yml` + `.txt` | config + log | Evidence |\n")
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (multi-fragment, bare-suffix dropped). rc={rc}\n{out}"


def test_i_trailing_slash_dir_with_tracked_contents_rc0():
    """(i) Trailing-slash directory demos/fixtures/ with tracked contents → rc 0."""
    repo = _make_spike_repo(["demos/fixtures/fix1.md", "demos/fixtures/fix2.json"], [])
    _write_results(repo, _TABLE_HEADER + "| `demos/fixtures/` | all fixtures | Evidence |\n")
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (trailing-slash dir tracked). rc={rc}\n{out}"


def test_j_header_and_separator_rows_not_parsed_as_paths():
    """(j) Table header + |---| separator rows are never mis-parsed as paths."""
    repo = _make_spike_repo(["demos/real.md"], [])
    _write_results(repo, _TABLE_HEADER + "| `demos/real.md` | desc | demonstrates |\n")
    rc, out = _run(repo)
    # Should be clean — no false positives from header/separator rows
    assert rc == 0, f"Header/separator rows should not be flagged. rc={rc}\n{out}"
    # Also verify "File" and "---" aren't reported as offenders
    assert "| File |" not in out, "Header row leaked as offender"
    assert "|---|" not in out, "Separator row leaked as offender"


def test_k_url_and_na_dropped():
    """(k) File cell that is a URL or n/a is dropped (not flagged)."""
    repo = _make_spike_repo([], [])
    table = (
        _TABLE_HEADER
        + "| https://example.com/demo | external | Link |\n"
        + "| n/a | none | N/A |\n"
        + "| — | none | Dash |\n"
    )
    _write_results(repo, table)
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (URLs/n/a dropped). rc={rc}\n{out}"


def test_l_backticked_and_plain_path_resolve():
    """(l) Backticked vs un-backticked path both resolve correctly."""
    repo = _make_spike_repo(["demos/plain.md", "demos/ticked.md"], [])
    table = (
        _TABLE_HEADER
        + "| demos/plain.md | plain path | Evidence |\n"
        + "| `demos/ticked.md` | backticked | Evidence |\n"
    )
    _write_results(repo, table)
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (both resolve). rc={rc}\n{out}"


def test_repair_line_format():
    """Offender output uses 'repair: <path> referenced ...' format."""
    repo = _make_spike_repo([], [])
    _write_results(repo, _TABLE_HEADER + "| `demos/missing.md` | desc | demonstrates |\n")
    rc, out = _run(repo)
    assert rc == 1
    assert "repair:" in out, f"Expected 'repair:' prefix in output.\n{out}"
    assert "demos/missing.md" in out


# ── F1: non-demos evidence paths ─────────────────────────────────────────────

def test_f1a_untracked_non_demos_path_rc1():
    """(F1a) Untracked non-demos path artifacts/x.md on disk → rc 1, named in output."""
    repo = _make_spike_repo([], ["artifacts/x.md"])
    _write_results(repo, _TABLE_HEADER + "| `artifacts/x.md` | desc | demonstrates |\n")
    rc, out = _run(repo)
    assert rc == 1, f"Expected rc 1 (non-demos untracked). rc={rc}\n{out}"
    assert "artifacts/x.md" in out, f"Expected offender in output.\n{out}"


def test_f1b_untracked_toplevel_script_rc1():
    """(F1b) Untracked top-level build.sh → rc 1."""
    repo = _make_spike_repo([], ["build.sh"])
    _write_results(repo, _TABLE_HEADER + "| `build.sh` | script | demonstrates |\n")
    rc, out = _run(repo)
    assert rc == 1, f"Expected rc 1 (top-level untracked). rc={rc}\n{out}"
    assert "build.sh" in out, f"Expected offender in output.\n{out}"


def test_f1c_tracked_non_demos_path_rc0():
    """(F1c) Tracked non-demos path reports/r.md (git-added at repo root) → rc 0."""
    repo = _make_spike_repo(["reports/r.md"], [])
    # spike-results.md is inside a design subdir; reports/r.md is tracked at root
    design_dir = repo / "three-pillars-docs/tp-designs/my-spike"
    design_dir.mkdir(parents=True, exist_ok=True)
    (design_dir / "spike-results.md").write_text(
        _TABLE_HEADER + "| `reports/r.md` | report | demonstrates |\n"
    )
    rc, out = _run(design_dir)
    assert rc == 0, f"Expected rc 0 (non-demos tracked). rc={rc}\n{out}"


# ── F2: brace-of-dirs false positive ─────────────────────────────────────────

def test_f2a_brace_of_dirs_all_tracked_rc0():
    """(F2a) demos/run-{1,2}/ with BOTH dirs tracked (each has a file) → rc 0."""
    tracked = ["demos/run-1/output.json", "demos/run-2/output.json"]
    repo = _make_spike_repo(tracked, [])
    _write_results(repo, _TABLE_HEADER + "| `demos/run-{1,2}/` | runs | demonstrates |\n")
    rc, out = _run(repo)
    assert rc == 0, f"Expected rc 0 (brace-of-dirs all tracked). rc={rc}\n{out}"


# ── case-k de-tautologize: direct unit tests on _is_non_path ─────────────────

def test_k_unit_url_is_non_path():
    """URL fragment https://example.com/x is treated as non-path (dropped)."""
    import importlib, sys as _sys
    from pathlib import Path as _Path
    _shared = _Path(__file__).parent
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evidence_tracked", _shared / "evidence_tracked.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._is_non_path("https://example.com/x"), \
        "URL should be identified as non-path"


def test_k_unit_na_is_non_path():
    """'n/a' fragment is treated as non-path (dropped)."""
    import importlib.util
    from pathlib import Path as _Path
    spec = importlib.util.spec_from_file_location(
        "evidence_tracked", _Path(__file__).parent / "evidence_tracked.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._is_non_path("n/a"), "'n/a' should be identified as non-path"


def test_k_unit_em_dash_is_non_path():
    """Em-dash '—' fragment is treated as non-path (dropped)."""
    import importlib.util
    from pathlib import Path as _Path
    spec = importlib.util.spec_from_file_location(
        "evidence_tracked", _Path(__file__).parent / "evidence_tracked.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._is_non_path("—"), "'—' should be identified as non-path"


# ── T-collide: bare-leaf must not be resolved by an unrelated tracked file ────

def test_t_collide_leaf_untracked_despite_collision():
    """(T-collide-leaf) Untracked referenced 'build.sh' + tracked 'ci/build.sh' → rc 1.

    Tier-3 bare-leaf search is scoped to the design-dir subtree. When the referenced
    bare leaf 'build.sh' is untracked and the only tracked file ending with '/build.sh'
    is 'ci/build.sh' outside the design dir, tier-3 must NOT resolve it.

    The design dir is nested (three-pillars-docs/tp-designs/my-spike) so that
    ci/build.sh at repo root is clearly outside the design subtree.
    """
    repo = _make_spike_repo(["ci/build.sh"], [])
    # Place spike-results.md in a nested design dir, not at repo root
    design_dir = repo / "three-pillars-docs/tp-designs/my-spike"
    design_dir.mkdir(parents=True, exist_ok=True)
    # build.sh is untracked (not in the repo at all, or exists on disk untracked)
    (repo / "build.sh").write_text("# untracked build.sh")
    _write_results(design_dir, _TABLE_HEADER + "| `build.sh` | script | demonstrates |\n")
    rc, out = _run(design_dir)
    assert rc == 1, (
        f"Expected rc 1 (bare-leaf 'build.sh' untracked; 'ci/build.sh' outside "
        f"design dir must not collide). rc={rc}\n{out}"
    )
    assert "build.sh" in out, f"Expected offender in output.\n{out}"


def test_t_collide_substr_log_txt():
    """(T-collide-substr) Untracked referenced 'log.txt' + tracked 'd/catalog.txt' → rc 1.

    Old unanchored '*log.txt' pathspec would match 'd/catalog.txt' (substring).
    The anchored fix requires P == 'log.txt' or P.endswith('/log.txt') — neither
    holds for 'd/catalog.txt'.
    """
    repo = _make_spike_repo(["d/catalog.txt"], ["log.txt"])
    _write_results(repo, _TABLE_HEADER + "| `log.txt` | log | demonstrates |\n")
    rc, out = _run(repo)
    assert rc == 1, (
        f"Expected rc 1 (bare-leaf 'log.txt' untracked; 'd/catalog.txt' must NOT "
        f"collide). rc={rc}\n{out}"
    )
    assert "log.txt" in out, f"Expected offender in output.\n{out}"


def test_t_continuation_fragment_anchored_ok():
    """(T-continuation-ok) Tier-3 anchored suffix match for genuine continuation fragments.

    Case A: demos/e1/run-{1,2,3}/agent.json — all tracked under that exact path.
    Tier-1 (design-dir-relative) resolves these since the design_dir is the repo
    root in the hermetic test.

    Case B: orphaned fragment 'run-1/artifacts/x.json' (no design-dir prefix) where
    the file IS tracked as 'demos/e1/run-1/artifacts/x.json'. Tier-3 anchored suffix
    match catches it: 'demos/e1/run-1/artifacts/x.json'.endswith('/run-1/artifacts/x.json').
    """
    # Case A: full path in cell → tier-1 resolves directly
    tracked_a = [
        "demos/e1/run-1/agent.json",
        "demos/e1/run-2/agent.json",
        "demos/e1/run-3/agent.json",
    ]
    repo_a = _make_spike_repo(tracked_a, [])
    _write_results(
        repo_a,
        _TABLE_HEADER + "| `demos/e1/run-{1,2,3}/agent.json` | per-run | Evidence |\n",
    )
    rc_a, out_a = _run(repo_a)
    assert rc_a == 0, f"Case A expected rc 0 (full brace path tracked). rc={rc_a}\n{out_a}"

    # Case B: continuation fragment with '/' — tier-3 anchored suffix must resolve it
    tracked_b = [
        "demos/e1/run-1/artifacts/x.json",
        "demos/e1/run-2/artifacts/x.json",
    ]
    repo_b = _make_spike_repo(tracked_b, [])
    # The design dir is a sub-directory; the fragment is a continuation fragment
    # that lost its 'demos/e1/' prefix (the design-dir-relative resolution fails).
    design_dir_b = repo_b / "three-pillars-docs/tp-designs/my-spike"
    design_dir_b.mkdir(parents=True, exist_ok=True)
    (design_dir_b / "spike-results.md").write_text(
        _TABLE_HEADER
        + "| `run-{1,2}/artifacts/x.json` | per-run artifacts | Evidence |\n"
    )
    rc_b, out_b = _run(design_dir_b)
    assert rc_b == 0, (
        f"Case B expected rc 0 (continuation fragment with '/' resolved by anchored "
        f"tier-3). rc={rc_b}\n{out_b}"
    )
