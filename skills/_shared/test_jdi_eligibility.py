"""Hermetic tests for jdi_eligibility.check — diff cap, surfaces, Scope paths, bad input.

Fixture repos are tmp dirs with GIT_* removed (the `rig` pattern in
test_launch_design_run.py); the identity/property arms read the shipped
hot_patch_check constants so the cap and surfaces are never duplicated here either.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hot_patch_check as hpc  # noqa: E402
import jdi_eligibility as je  # noqa: E402

# A Scope section naming only ordinary paths: every arm but (e)/(f) needs a real,
# well-formed design dir so it can be ELIGIBLE.
SCOPE_CLEAN = (
    "### In scope\n\n"
    "- `skills/foo/bar.py` (new)\n"
    "- `skills/foo/test_bar.py` (new)\n\n"
    "### Out of scope\n\n"
    "- nothing yet\n"
)


def _git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(cwd), check=True, capture_output=True,
    )


def _rev(repo, ref):
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _commit(repo, paths: dict) -> str:
    """Write {relpath: text-or-bytes}, add them, commit; return the new SHA."""
    for rel, body in paths.items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "head", cwd=repo)
    return _rev(repo, "HEAD")


def _design(tmp_path, scope_body=SCOPE_CLEAN) -> Path:
    d = tmp_path / "design"
    d.mkdir(exist_ok=True)
    (d / "design.md").write_text(
        "---\nweight-class: just-do-it\nslug: fixture\n---\n\n"
        "# fixture — design\n\n## Scope\n\n" + scope_body + "\n"
        "## Behaviors\n\n1. It works.\n\n## Done when\n\nTests pass.\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-q", cwd=r)
    _git("commit", "-q", "--allow-empty", "-m", "base", cwd=r)
    return r


def _check(tmp_path, repo, base, head, design_dir=None):
    return je.check(
        str(design_dir or _design(tmp_path)), base, head, repo=str(repo),
    )


# --- (a) the 150/151 cap edge ------------------------------------------------


def test_cap_edge_150_is_eligible(tmp_path, repo):
    base = _rev(repo, "HEAD")
    head = _commit(repo, {"src/a.py": "".join(f"x = {i}\n" for i in range(150))})
    assert _check(tmp_path, repo, base, head) == (0, "ELIGIBLE")


def test_cap_edge_151_escalates_with_exact_reason(tmp_path, repo):
    base = _rev(repo, "HEAD")
    head = _commit(repo, {"src/a.py": "".join(f"x = {i}\n" for i in range(151))})
    rc, line = _check(tmp_path, repo, base, head)
    assert rc == 1
    assert line == "ESCALATE diff-cap: 151 changed lines exceeds cap of 150"


# --- (b) three-pillars-docs/ is paper: exempt from the sum ------------------


def test_docs_paths_are_exempt_from_the_line_sum(tmp_path, repo):
    base = _rev(repo, "HEAD")
    head = _commit(repo, {
        "three-pillars-docs/x.md": "".join(f"line {i}\n" for i in range(100)),
        "src/a.py": "".join(f"x = {i}\n" for i in range(100)),
    })
    assert _check(tmp_path, repo, base, head) == (0, "ELIGIBLE")


# --- (c) one hit per surface class -----------------------------------------


@pytest.mark.parametrize("rel", [
    ".three-pillars/config.json",            # hot-patch excluded prefix
    "framework-check.sh",                    # hot-patch excluded file
    ".githooks/pre-commit",                  # jdi-only excluded prefix
    "skills/_shared/launch_design_run.py",   # jdi-only excluded file
    "skills/_shared/github_pr_author.py",    # jdi-only excluded file
])
def test_excluded_surface_in_the_diff_escalates_naming_the_path(tmp_path, repo, rel):
    base = _rev(repo, "HEAD")
    head = _commit(repo, {rel: "x = 1\n"})
    rc, line = _check(tmp_path, repo, base, head)
    assert rc == 1
    assert line.startswith("ESCALATE surface:")
    assert rel in line


def test_docs_surface_is_still_checked_though_paper_is_line_exempt(tmp_path, repo):
    base = _rev(repo, "HEAD")
    head = _commit(repo, {"three-pillars-docs/x.md": "x = 1\n",
                          "framework-check.sh": "echo hi\n"})
    rc, line = _check(tmp_path, repo, base, head)
    assert rc == 1
    assert "framework-check.sh" in line


# --- (d) binary files -------------------------------------------------------


def test_binary_file_escalates(tmp_path, repo):
    base = _rev(repo, "HEAD")
    head = _commit(repo, {"assets/blob.bin": b"\x00\x01\x02binary\n" * 5})
    rc, line = _check(tmp_path, repo, base, head)
    assert rc == 1
    assert line.startswith("ESCALATE binary:")
    assert "assets/blob.bin" in line


# --- (e) the Scope-path check (no diff needed) ------------------------------


def test_scope_naming_an_excluded_surface_escalates_with_no_diff(tmp_path, repo):
    d = _design(tmp_path, "### In scope\n\n- `skills/_shared/github_pr_author.py` (new)\n")
    base = _rev(repo, "HEAD")
    assert _check(tmp_path, repo, base, base, d)[0] == 1


def test_scope_naming_only_ordinary_paths_is_eligible(tmp_path, repo):
    d = _design(tmp_path, "### In scope\n\n- `skills/foo/bar.py` (new)\n")
    base = _rev(repo, "HEAD")
    assert _check(tmp_path, repo, base, base, d) == (0, "ELIGIBLE")


def test_scope_span_under_out_of_scope_is_ignored(tmp_path, repo):
    d = _design(
        tmp_path,
        "### In scope\n\n- `skills/foo/bar.py` (new)\n\n"
        "### Out of scope\n\n- `skills/_shared/github_pr_author.py`\n",
    )
    base = _rev(repo, "HEAD")
    assert _check(tmp_path, repo, base, base, d) == (0, "ELIGIBLE")


def test_scope_paths_returns_the_in_scope_backticked_paths(tmp_path):
    d = _design(tmp_path)
    assert je.scope_paths(str(d)) == ["skills/foo/bar.py", "skills/foo/test_bar.py"]


# --- (f) bad input: exit 2, never eligible ----------------------------------


@pytest.mark.parametrize("case", ["missing_dir", "no_design_md", "no_scope_heading"])
def test_bad_design_input_exits_2(tmp_path, repo, case):
    base = _rev(repo, "HEAD")
    if case == "missing_dir":
        d = tmp_path / "not-a-design-dir"
    elif case == "no_design_md":
        d = tmp_path / "design"
        d.mkdir()
    else:
        d = tmp_path / "design"
        d.mkdir()
        (d / "design.md").write_text(
            "---\nweight-class: just-do-it\n---\n\n# fixture\n\n"
            "## Behaviors\n\n1. x\n",
            encoding="utf-8",
        )
    rc, line = je.check(str(d), base, base, repo=str(repo))
    assert rc == 2
    assert line.startswith("ESCALATE bad-input:")


def test_scope_paths_raises_value_error_without_a_scope_heading(tmp_path):
    d = tmp_path / "design"
    d.mkdir()
    (d / "design.md").write_text(
        "---\nweight-class: just-do-it\n---\n\n# fixture\n\n## Behaviors\n\n1. x\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        je.scope_paths(str(d))


@pytest.mark.parametrize("which", ["base", "head"])
def test_unresolvable_ref_exits_2(tmp_path, repo, which):
    d = _design(tmp_path)
    good = _rev(repo, "HEAD")
    bad = "definitely-not-a-ref"
    rc, line = je.check(
        str(d), bad if which == "base" else good,
        good if which == "base" else bad, repo=str(repo),
    )
    assert rc == 2
    assert line.startswith("ESCALATE bad-input:")


def test_non_git_repo_exits_2(tmp_path):
    d = _design(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    rc, line = je.check(str(d), "HEAD", "HEAD", repo=str(plain))
    assert rc == 2
    assert line.startswith("ESCALATE bad-input:")


# --- (g) property: every hot-patch exclusion is a jdi surface ---------------


def test_every_hot_patch_exclusion_is_a_surface():
    for p in hpc.EXCLUDED_FILES:
        assert je.surface_hit(p) is not None, p
    for prefix in hpc.EXCLUDED_PREFIXES:
        assert je.surface_hit(prefix + "x") is not None, prefix


def test_ordinary_paths_are_not_surfaces():
    for p in ("skills/foo/bar.py", "three-pillars-docs/x.md", "src/a.py"):
        assert je.surface_hit(p) is None, p


# --- (h) nothing is duplicated from hot_patch_check -------------------------


def test_cap_and_exclusions_are_the_hot_patch_check_objects(monkeypatch):
    # Identity alone would pass for a copied literal (small ints intern), so the
    # cap is checked behaviourally: a sentinel on the source module must reach
    # jdi_eligibility on reload.
    assert je.EXCLUDED_PREFIXES is hpc.EXCLUDED_PREFIXES
    assert je.EXCLUDED_FILES is hpc.EXCLUDED_FILES
    monkeypatch.setattr(hpc, "DIFF_CAP", 987654)
    try:
        importlib.reload(je)
        assert je.DIFF_CAP == 987654
    finally:
        monkeypatch.undo()
        importlib.reload(je)


def test_jdi_surfaces_add_the_lane_specific_paths():
    assert je.JDI_EXCLUDED_PREFIXES == (".githooks/",)
    assert je.JDI_EXCLUDED_FILES == frozenset({
        "skills/_shared/launch_design_run.py",
        "skills/_shared/github_pr_author.py",
    })


def test_git_diff_failure_is_never_eligible(tmp_path, repo):
    """A diff git could not compute (no merge base) is bad input, never ELIGIBLE."""
    base = _rev(repo, "HEAD")
    (Path(repo) / "big.py").write_text("x = 1\n" * 400, encoding="utf-8")
    _git("add", "big.py", cwd=repo)
    tree = subprocess.run(["git", "-C", str(repo), "write-tree"], check=True,
                          capture_output=True, text=True).stdout.strip()
    orphan = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                             "commit-tree", tree, "-m", "orphan"], check=True,
                            capture_output=True, text=True).stdout.strip()
    rc, line = je.check(str(_design(tmp_path)), base, orphan, repo=str(repo))
    assert rc == 2 and line.startswith("ESCALATE bad-input"), (rc, line)
