"""test_explain_state.py — the explainer's out-of-tree state: root, delivery records, telemetry.

Covers explainer-agent plan Task 8.2 (detailed-design §Interfaces, the explain_state bullet):
  - `state_root(root)` is `<git rev-parse --git-common-dir>/three-pillars/explainer/`, the same
    path from the main checkout and from a linked worktree, and it does not depend on the cwd;
  - `delivery(root, slug, kind)` reads and writes only its own kind's entry in
    `<state_root>/<slug>/delivery.json`; `pr-brief` and `rulings` never share an entry;
    any other kind raises ValueError;
  - a degrade reason recorded twice is stored once in `degraded`;
  - `telemetry_append(root, row)` appends one NDJSON line with the ten telemetry keys;
    `report(root)` gives per-engine `{n, rewrite_rate, check_rewritten_rate}`.

Every state function takes the repo root first, so every test builds a tmp git repo under
`tmp_path`; nothing here touches the real repo's `.git/three-pillars/explainer/`.
Assertions are on returned values and on the JSON files' parsed content, never on source text
(skills/_shared/test-fragility.md).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_state  # noqa: E402

TELEMETRY_KEYS = {"ts", "slug", "kind", "engine", "served", "gates", "rewrite_used",
                  "check_outcome", "facts_only", "degraded"}


def _git(cwd, *args) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                         cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    """A tmp git repo with one commit (so a linked worktree can be added)."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    return root


def _delivery_file(root, slug) -> Path:
    return explain_state.state_root(root) / slug / "delivery.json"


# ---------------------------------------------------------------- state root


def test_state_root_is_under_the_git_common_dir(repo):
    expected = (repo / ".git").resolve() / "three-pillars" / "explainer"
    assert explain_state.state_root(repo) == expected


def test_state_root_is_the_same_from_a_linked_worktree(repo, tmp_path):
    wt = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "side", str(wt))
    assert explain_state.state_root(wt) == explain_state.state_root(repo)


def test_state_root_does_not_depend_on_the_cwd(repo, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert explain_state.state_root(repo) == (repo / ".git").resolve() / "three-pillars" / "explainer"
    explain_state.delivery(repo, "s", "pr-brief", update={"comment_id": 1})
    assert _delivery_file(repo, "s").is_file()
    assert not (elsewhere / ".git").exists()


def test_state_root_outside_a_git_repo_raises(tmp_path):
    bare_dir = tmp_path / "plain"
    bare_dir.mkdir()
    with pytest.raises(RuntimeError):
        explain_state.state_root(bare_dir)


# ------------------------------------------------------------ delivery records


def test_delivery_kinds_are_closed():
    assert explain_state.DELIVERY_KINDS == ("pr-brief", "rulings")


def test_delivery_read_of_an_unwritten_kind_is_empty(repo):
    assert explain_state.delivery(repo, "s", "pr-brief") == {}
    assert not _delivery_file(repo, "s").exists()


def test_delivery_write_touches_only_its_kind_entry(repo):
    entry = explain_state.delivery(repo, "s", "pr-brief",
                                   update={"comment_id": 11, "posted_head": "abc", "html": "p.html"})
    assert entry == {"comment_id": 11, "posted_head": "abc", "html": "p.html"}
    on_disk = json.loads(_delivery_file(repo, "s").read_text(encoding="utf-8"))
    assert on_disk == {"pr-brief": {"comment_id": 11, "posted_head": "abc", "html": "p.html"}}
    assert explain_state.delivery(repo, "s", "pr-brief") == entry


def test_writing_rulings_leaves_pr_brief_intact(repo):
    explain_state.delivery(repo, "s", "pr-brief", update={"comment_id": 11, "posted_head": "abc"})
    explain_state.delivery(repo, "s", "rulings", update={"comment_id": 22})
    on_disk = json.loads(_delivery_file(repo, "s").read_text(encoding="utf-8"))
    assert on_disk["pr-brief"] == {"comment_id": 11, "posted_head": "abc"}
    assert on_disk["rulings"] == {"comment_id": 22}
    explain_state.delivery(repo, "s", "pr-brief", update={"comment_id": 12})
    assert explain_state.delivery(repo, "s", "rulings") == {"comment_id": 22}


def test_delivery_update_merges_into_the_existing_entry(repo):
    explain_state.delivery(repo, "s", "pr-brief", update={"comment_id": 11, "html": "a.html"})
    merged = explain_state.delivery(repo, "s", "pr-brief", update={"artifact_url": "https://x/y"})
    assert merged == {"comment_id": 11, "html": "a.html", "artifact_url": "https://x/y"}


def test_delivery_records_are_per_slug(repo):
    explain_state.delivery(repo, "one", "pr-brief", update={"comment_id": 1})
    assert explain_state.delivery(repo, "two", "pr-brief") == {}


@pytest.mark.parametrize("kind", ["human-escalation", "", "PR-BRIEF", "comment"])
def test_any_other_delivery_kind_raises_on_read_and_write(repo, kind):
    with pytest.raises(ValueError):
        explain_state.delivery(repo, "s", kind)
    with pytest.raises(ValueError):
        explain_state.delivery(repo, "s", kind, update={"comment_id": 1})
    assert not _delivery_file(repo, "s").exists()


@pytest.mark.parametrize("slug", ["", "../escape", "a/b", ".."])
def test_a_slug_that_is_not_one_path_component_raises(repo, slug):
    with pytest.raises(ValueError):
        explain_state.delivery(repo, slug, "pr-brief", update={"comment_id": 1})


def test_a_degrade_reason_recorded_twice_is_stored_once(repo):
    explain_state.record_degraded(repo, "s", "pr-brief", "no token")
    explain_state.record_degraded(repo, "s", "pr-brief", "no token")
    assert explain_state.delivery(repo, "s", "pr-brief")["degraded"] == ["no token"]


def test_degraded_in_an_update_is_deduplicated_and_ordered(repo):
    explain_state.delivery(repo, "s", "rulings", update={"degraded": ["a", "b"]})
    entry = explain_state.delivery(repo, "s", "rulings", update={"degraded": ["b", "c", "a"]})
    assert entry["degraded"] == ["a", "b", "c"]


def test_degraded_is_kept_per_kind(repo):
    explain_state.record_degraded(repo, "s", "pr-brief", "no token")
    explain_state.record_degraded(repo, "s", "rulings", "forge down")
    assert explain_state.delivery(repo, "s", "pr-brief")["degraded"] == ["no token"]
    assert explain_state.delivery(repo, "s", "rulings")["degraded"] == ["forge down"]


def test_a_corrupt_delivery_file_reads_as_empty_and_is_replaced_on_write(repo):
    path = _delivery_file(repo, "s")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert explain_state.delivery(repo, "s", "pr-brief") == {}
    explain_state.delivery(repo, "s", "pr-brief", update={"comment_id": 5})
    assert json.loads(path.read_text(encoding="utf-8")) == {"pr-brief": {"comment_id": 5}}


# ----------------------------------------------------------------- telemetry


def _row(engine="sonnet", **extra) -> dict:
    row = {"ts": "2026-10-09T00:00:00Z", "slug": "s", "kind": "pr-brief", "engine": engine,
           "served": engine, "gates": 1, "rewrite_used": False, "check_outcome": "accepted",
           "facts_only": False, "degraded": []}
    row.update(extra)
    return row


def _telemetry_lines(root) -> list:
    path = explain_state.state_root(root) / "telemetry.ndjson"
    return path.read_text(encoding="utf-8").splitlines()


def test_telemetry_append_writes_one_ndjson_line_with_the_ten_keys(repo):
    explain_state.telemetry_append(repo, _row())
    lines = _telemetry_lines(repo)
    assert len(lines) == 1
    assert set(json.loads(lines[0])) == TELEMETRY_KEYS


def test_telemetry_append_appends_rather_than_rewrites(repo):
    explain_state.telemetry_append(repo, _row(slug="one"))
    explain_state.telemetry_append(repo, _row(slug="two"))
    assert [json.loads(line)["slug"] for line in _telemetry_lines(repo)] == ["one", "two"]


def test_telemetry_append_fills_a_missing_ts_and_missing_keys(repo):
    explain_state.telemetry_append(repo, {"engine": "local", "slug": "s"})
    row = json.loads(_telemetry_lines(repo)[0])
    assert set(row) == TELEMETRY_KEYS
    assert row["engine"] == "local" and row["ts"]
    assert row["rewrite_used"] is False and row["degraded"] == []


def test_report_gives_per_engine_rates(repo):
    explain_state.telemetry_append(repo, _row("sonnet", rewrite_used=True))
    explain_state.telemetry_append(repo, _row("sonnet", check_outcome="rewritten"))
    assert explain_state.report(repo) == {
        "sonnet": {"n": 2, "rewrite_rate": 0.5, "check_rewritten_rate": 0.5}}


def test_report_keeps_engines_apart(repo):
    explain_state.telemetry_append(repo, _row("sonnet", rewrite_used=True))
    explain_state.telemetry_append(repo, _row("local"))
    explain_state.telemetry_append(repo, _row("local", check_outcome="rewritten"))
    explain_state.telemetry_append(repo, _row("local", check_outcome="rewritten"))
    rep = explain_state.report(repo)
    assert rep["sonnet"] == {"n": 1, "rewrite_rate": 1.0, "check_rewritten_rate": 0.0}
    assert rep["local"]["n"] == 3
    assert rep["local"]["rewrite_rate"] == 0.0
    assert rep["local"]["check_rewritten_rate"] == pytest.approx(2 / 3, abs=1e-3)


def test_report_with_no_telemetry_is_empty(repo):
    assert explain_state.report(repo) == {}


def test_report_skips_a_malformed_line(repo):
    explain_state.telemetry_append(repo, _row("sonnet", rewrite_used=True))
    path = explain_state.state_root(repo) / "telemetry.ndjson"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{torn line\n")
    explain_state.telemetry_append(repo, _row("sonnet"))
    assert explain_state.report(repo) == {
        "sonnet": {"n": 2, "rewrite_rate": 0.5, "check_rewritten_rate": 0.0}}
