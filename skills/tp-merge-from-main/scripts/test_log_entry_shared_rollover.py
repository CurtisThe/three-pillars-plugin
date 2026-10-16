"""PR #206 round 1 (correctness-leak): keep-both must not duplicate an entry both sides inserted.

`product_roadmap_archive.md` / `architecture_archive.md` joined `AUTO_SAFE_PATHS`, so their
conflicts reach `log-entry-insertion`. The normal archive conflict is two branches that each
rolled the SAME History lines out of the live doc (ours [A, B], theirs [C, A, B]); verbatim
concatenation wrote A and B twice under a RESOLVED verdict. The resolver now emits the whole
entries both blocks open or close with once, defers when the differing middles still share an
entry, and keeps both copies of a body line two distinct entries share. The licence checker and
its oracle both account for the collapsed twin.
"""
import os
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))
import licence_oracle  # noqa: E402
import resolvers  # noqa: E402
from classify import Hunk  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from resolve import DEFER, RESOLVED, resolve_hunk  # noqa: E402
from resolve_totality import overproduced, unplaceable  # noqa: E402
from task_scope import _git_env  # noqa: E402

ARCH = "three-pillars-docs/architecture_archive.md"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
HEAD = "# Architecture — Archive\n\n## History\n\n"
OLD = "- **2026-09-01** — `old-design` implemented (light class).\n"
A = "- **2026-09-23** — `alpha-design` implemented (light class).\n"
B = "- **2026-09-22** — `beta-design` implemented (light class).\n"
C = "- **2026-09-23** — `gamma-design` implemented (light class).\n"
D = "- **2026-09-21** — `delta-design` implemented (light class).\n"
L = {k: v.rstrip("\n") for k, v in {"A": A, "B": B, "C": C, "D": D, "OLD": OLD}.items()}
BODY = "  Approved-by: operator"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=_git_env(**IDENT))


def _commit(repo, text):
    p = repo / ARCH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "x")


def _hunk(ours, theirs):
    return Hunk(ours=list(ours), base=[], theirs=list(theirs), label="log-entry-insertion",
                post_context=L["OLD"])


def _licensed(h, result):
    assert unplaceable(h, result.label, result.lines) == []
    assert overproduced(h, result.label, result.lines) == []
    assert licence_oracle.lost_lines(h, SimpleNamespace(
        label=result.label, renumbered={}, lines=result.lines)) == []


def test_both_sides_rolling_the_same_history_into_an_archive_are_not_duplicated(
        tmp_path, monkeypatch):
    for k, v in IDENT.items():
        monkeypatch.setenv(k, v)
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _commit(repo, HEAD + OLD)
    _git(repo, "checkout", "-q", "-b", "feat")
    _commit(repo, HEAD + A + B + OLD)          # branch rolled A, B out of architecture.md
    _git(repo, "checkout", "-q", "master")
    _commit(repo, HEAD + C + A + B + OLD)      # master rolled C, A, B (the same A, B lines)
    _git(repo, "checkout", "-q", "feat")
    report = merge_back(str(repo), "master")
    text = (repo / ARCH).read_text(encoding="utf-8")
    assert ARCH in report.auto_resolved, report.to_json()
    assert text == HEAD + C + A + B + OLD, text


def test_shared_suffix_and_prefix_are_emitted_once():
    h = _hunk([L["A"], L["B"]], [L["C"], L["A"], L["B"]])
    r = resolve_hunk(h)
    assert r.status == RESOLVED and r.lines == [L["C"], L["A"], L["B"]]
    _licensed(h, r)
    h = _hunk([L["A"], L["D"]], [L["A"], L["C"]])
    r = resolve_hunk(h)
    assert r.status == RESOLVED and r.lines == [L["A"], L["D"], L["C"]]
    _licensed(h, r)


def test_a_shared_entry_between_unshared_ones_defers():
    h = _hunk([L["C"], L["A"], L["D"]], [L["B"], L["A"], L["D"] + " (amended)"])
    assert resolve_hunk(h).status == DEFER
    try:
        resolvers.resolve_log_entry_insertion(h)
    except resolvers.CannotPlace:
        pass
    else:
        raise AssertionError("a shared entry in the differing middles must raise CannotPlace")


def test_shared_body_line_in_distinct_entries_still_keeps_both():
    h = _hunk([L["A"], BODY], [L["C"], BODY])
    r = resolve_hunk(h)
    assert r.status == RESOLVED
    assert r.lines == [L["A"], BODY, L["C"], BODY]
    _licensed(h, r)


def test_collapsing_a_shared_body_line_is_still_reported_by_checker_and_oracle():
    """The licence covers whole shared entries only, so a resolver that regressed to per-line
    dedupe (one `  Approved-by: operator` for two distinct entries) is caught by both."""
    h = _hunk([L["A"], BODY], [L["C"], BODY])
    collapsed = [L["A"], BODY, L["C"]]
    assert unplaceable(h, "log-entry-insertion", collapsed) == [BODY]
    assert licence_oracle.lost_lines(h, SimpleNamespace(
        label="log-entry-insertion", renumbered={}, lines=collapsed)) == [BODY]


def test_the_oracle_reads_entry_starts_as_the_production_pattern_does():
    from line_shapes import LOG_ENTRY
    samples = [L["A"], L["OLD"], "- **`run-throughput`** — Done", "-\t**2026-01-02**\t— x",
               BODY, "- **2026-1-02** — x", "- **`Bad`** — x", "-**2026-01-02** — x",
               "- **2026-01-02**— x", "- **`a-b`** - x", "* **2026-01-02** — x", ""]
    for line in samples:
        assert licence_oracle.is_log_entry_start(line) == bool(LOG_ENTRY.match(line)), line
