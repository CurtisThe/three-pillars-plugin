"""Step 1 of the `basesync-autoresolve-coverage` seed, pinned on the LIVE docs.

The two insert-only keyed shapes from the real #191 conflicts — a dated History line
(`- **YYYY-MM-DD** — …`) in `known_issues.md` and a slug bullet (`- **`slug`** — …`) in
`product_roadmap.md` — must resolve mechanically on those paths, and so must disjoint issue entries
(`### M48:` vs `### M49:`, keep-both); a SAME-ID pair (both add `### M48:`) stays GATED for the human.
Split out of `test_merge_driver.py` to respect the
500-line hard cap; it carries its own git helpers like the other per-scenario test files here.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from merge_driver import merge_back  # noqa: E402

KI = "three-pillars-docs/known_issues.md"
ROADMAP = "three-pillars-docs/product_roadmap.md"
PRE = "*Last updated: {date}*\n\n# Known issues\n"


def git(repo, *args, check=True):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=env)


def make_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    (repo / "three-pillars-docs").mkdir()
    return repo


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def test_seed_entry_shapes_resolve_on_their_live_docs(tmp_path):
    """The dated History line in `known_issues.md` and the slug bullet in `product_roadmap.md` are
    the AUTO-SAFE `log-entry-insertion` class (insertion-only, keyed, both-sides-added), so a real
    base-sync conflict on those live docs resolves mechanically — keep-both, zero-drop, staged —
    rather than deferring as generic prose. This is what keeps the driver's #191 `auto` count from
    regressing back to 0. The `older`/`base entry` line is the `_ends_at_boundary` line that makes
    each hunk a log insertion rather than generic prose."""
    repo = make_repo(tmp_path)
    ki_base = PRE.format(date="2026-05-01") + "\n## History\n\n- **2026-05-01** — base entry\n"
    write(repo, KI, ki_base)
    rm_base = "# Product roadmap\n\n## Recent completions\n\n- **`older`** — Done — PR #170\n"
    write(repo, ROADMAP, rm_base)
    commit(repo, "base")

    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, ki_base + "- **2026-05-09** — `design-a` amended **L94**.\n")
    write(repo, ROADMAP, rm_base + "- **`cheap-tier-offload`** — Done — PR #187\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, ki_base + "- **2026-05-10** — `design-b` filed **L107**.\n")
    write(repo, ROADMAP, rm_base + "- **`task-worker-sonnet`** — Done — PR #188\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")

    report = merge_back(str(repo), "master")
    for path in (KI, ROADMAP):
        assert path in report.auto_resolved, report.to_json()
        content = (repo / path).read_text(encoding="utf-8")
        assert "<<<<<<<" not in content
    ki = (repo / KI).read_text(encoding="utf-8")
    assert "design-a" in ki and "design-b" in ki                # zero-drop: both History entries kept
    rm = (repo / ROADMAP).read_text(encoding="utf-8")
    assert "cheap-tier-offload" in rm and "task-worker-sonnet" in rm   # both slug bullets kept


def _issue_conflict(tmp_path, ours_id, theirs_id):
    """A base-sync conflict on `known_issues.md`: both branches file one issue entry above the same
    `### L1:` base entry, ours as `ours_id` and theirs as `theirs_id`. Returns (repo, report)."""
    repo = make_repo(tmp_path)
    pre = PRE.format(date="2026-05-01") + "\n## Medium\n\n"
    tail = "### L1: base issue\nbody\n\n## Low\n"
    write(repo, KI, pre + tail)
    commit(repo, "base")

    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, pre + f"### {ours_id}: ours issue title\nbody ours\n\n" + tail)
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, pre + f"### {theirs_id}: theirs issue title\nbody theirs\n\n" + tail)
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    return repo, merge_back(str(repo), "master")


def test_disjoint_issue_entries_auto_resolve_keep_both(tmp_path):
    """Flipped from `test_issue_entry_is_still_gated_not_auto_resolved`, which pinned `### M48:` vs
    `### M49:` as a human case. Disjoint keys are now `keyed-heading-insertion`: keep-both, nothing
    renumbered, and the zero-drop verifier guards every entry, so the file auto-resolves with both
    entries present, M48 first and no markers. Only a same-ID pair reaches the GATED class."""
    repo, report = _issue_conflict(tmp_path, "M48", "M49")
    assert KI in report.auto_resolved, report.to_json()
    content = (repo / KI).read_text(encoding="utf-8")
    assert "<<<<<<<" not in content and "=======" not in content
    assert content.count("### M48: ours issue title\nbody ours\n") == 1
    assert content.count("### M49: theirs issue title\nbody theirs\n") == 1
    assert content.index("### M48:") < content.index("### M49:") < content.index("### L1:")


def test_same_id_issue_entries_stay_gated_and_human(tmp_path):
    """Both branches filed `### M48:` — the `id-renumber-collision` shape, GATED: it is never
    auto-applied, so the file lands in a human bucket with its markers left in place (the driver
    keys the bucket by outcome action, so it may sit in `partially-resolved`), no atom dropped."""
    repo, report = _issue_conflict(tmp_path, "M48", "M48")
    assert KI not in report.auto_resolved, report.to_json()
    assert KI in (report.partially_resolved + report.deferred), report.to_json()
    content = (repo / KI).read_text(encoding="utf-8")
    assert "<<<<<<<" in content                                # left for the human
    assert "M48: ours issue title" in content and "M48: theirs issue title" in content
