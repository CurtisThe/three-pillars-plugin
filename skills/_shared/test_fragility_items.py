"""test_fragility_items.py — the per-branch store of confirmed fragile items
(design: fragile-test-prevention, detailed-design-stages.md Part C4).

Oracle: ``example``. Each case builds a real tmp git repo and drives `fragility_items`'
entry points (`record_round`, `open_items`, `waive`) plus `replace_source` and the CLI over
it. Items are keyed on structured fields (never the summary): only blocking findings whose
class is in `FRAGILE_CLASSES` become items, the id hashes source/path/class/anchor so a
re-worded re-report keeps its id and waiver, and the newest head's source list decides.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fragility_items as fi

_SCRIPTS = Path(__file__).resolve().parent.parent / "tp-pr-iterate" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import review_merge  # noqa: E402

IDENTITY = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test"}


def git(repo, *args):
    import os
    env = {**os.environ, **IDENTITY}
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=env)
    return done.stdout.strip()


def commit(repo, files, message="change"):
    for rel, text in files.items():
        path = Path(repo) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    base = commit(repo, {"lib.py": "def helper():\n    return 1\n"}, "base")
    return repo, base


# The producer shape: normalize_codereview emits line_range as a [start, end] int list.
FINDING = {"file": "lib.py", "line_range": [2, 2], "summary": "asserts an exact internal value",
           "class": "T", "blocking": True, "origin": "regression",
           "fragility_class": "change-detector"}


def test_only_blocking_fragile_class_findings_become_items(tmp_path):
    repo, base = make_repo(tmp_path)
    findings = [
        dict(FINDING),
        {**FINDING, "fragility_class": "unclassified"},
        {**FINDING, "fragility_class": "none"},
        {**FINDING, "blocking": False},
    ]
    count = fi.record_round(repo, "tp/x", base, findings)
    assert count == 1
    items = fi.open_items(repo, "tp/x")
    assert len(items) == 1
    assert items[0]["fragility_class"] == "change-detector"
    assert items[0]["path"] == "lib.py"


def test_id_hashes_structured_fields_and_anchors_on_enclosing_qualname(tmp_path):
    repo, base = make_repo(tmp_path)
    count = fi.record_round(repo, "tp/x", base, [dict(FINDING)])
    assert count == 1
    items = fi.open_items(repo, "tp/x")
    item = items[0]
    assert item["anchor"] == "helper"
    assert item["id"] == fi.item_id("pr-loop", "lib.py", "change-detector", "helper")


def test_anchor_falls_back_to_module_outside_any_def(tmp_path):
    repo, base = make_repo(tmp_path)
    finding = {**FINDING, "line_range": "1"}
    fi.record_round(repo, "tp/x", base, [finding])
    items = fi.open_items(repo, "tp/x")
    assert items[0]["anchor"] in ("<module>", "helper")


def test_lint_sourced_item_anchors_on_rule_id(tmp_path):
    repo, base = make_repo(tmp_path)
    finding = {**FINDING, "rule_id": "golden-hash"}
    fi.record_round(repo, "tp/x", base, [finding])
    items = fi.open_items(repo, "tp/x")
    assert items[0]["anchor"] == "golden-hash"


def test_reworded_rereport_keeps_id_and_waiver(tmp_path):
    repo, base = make_repo(tmp_path)
    fi.record_round(repo, "tp/x", base, [dict(FINDING)])
    item_id = fi.open_items(repo, "tp/x")[0]["id"]
    fi.waive(repo, "tp/x", item_id, by="alice", reason="known noise")
    assert fi.open_items(repo, "tp/x") == []

    reworded = {**FINDING, "summary": "a completely different wording of the same finding"}
    count = fi.record_round(repo, "tp/x", base, [reworded])
    assert count == 1
    # still waived: the reworded re-report kept the same id
    assert fi.open_items(repo, "tp/x") == []


def test_replace_source_stamps_the_head(tmp_path):
    repo, base = make_repo(tmp_path)
    items = [{"id": "abc123", "source": "impl-audit", "path": "lib.py", "line": 2,
              "fragility_class": "change-detector", "anchor": "helper", "summary": "x"}]
    fi.replace_source(repo, "tp/x", "impl-audit", base, items)
    stored = fi._load(repo)
    assert stored["branches"]["tp/x"]["sources"]["impl-audit"]["head"] == base


def test_newer_head_pr_loop_supersedes_impl_audit(tmp_path):
    repo, base = make_repo(tmp_path)
    audit_items = [{"id": "audit-item", "source": "impl-audit", "path": "lib.py", "line": 2,
                    "fragility_class": "change-detector", "anchor": "helper", "summary": "old"}]
    fi.replace_source(repo, "tp/x", "impl-audit", base, audit_items)

    head2 = commit(repo, {"other.py": "X = 1\n"}, "second")
    count = fi.record_round(repo, "tp/x", head2, [dict(FINDING)])
    assert count == 1

    items = fi.open_items(repo, "tp/x")
    ids = {i["id"] for i in items}
    assert "audit-item" not in ids
    assert len(items) == 1


def test_waive_refuses_empty_by_or_reason(tmp_path):
    repo, base = make_repo(tmp_path)
    fi.record_round(repo, "tp/x", base, [dict(FINDING)])
    item_id = fi.open_items(repo, "tp/x")[0]["id"]
    try:
        fi.waive(repo, "tp/x", item_id, by="", reason="ok")
        assert False, "expected ValueError"
    except ValueError:
        pass
    try:
        fi.waive(repo, "tp/x", item_id, by="alice", reason="")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_waive_scope_path_class_covers_every_matching_item(tmp_path):
    repo, base = make_repo(tmp_path)
    f1 = dict(FINDING)
    f2 = {**FINDING, "rule_id": "other-rule"}
    fi.record_round(repo, "tp/x", base, [f1, f2])
    items = fi.open_items(repo, "tp/x")
    assert len(items) == 2
    target = next(i for i in items if i["anchor"] == "helper")
    fi.waive(repo, "tp/x", target["id"], by="alice", reason="known", scope="path-class")
    assert fi.open_items(repo, "tp/x") == []


def test_cli_list_waive_replace_round_trip(tmp_path):
    repo, base = make_repo(tmp_path)
    findings_file = tmp_path / "findings.json"
    findings_file.write_text(json.dumps([dict(FINDING)]), encoding="utf-8")

    rc = fi.main(["replace", "--root", str(repo), "--branch", "tp/x",
                  "--source", "pr-loop", "--head", base,
                  "--findings", str(findings_file)])
    assert rc == 0

    items = fi.open_items(repo, "tp/x")
    assert len(items) == 1
    item_id = items[0]["id"]

    rc = fi.main(["waive", "--root", str(repo), "--branch", "tp/x",
                  "--id", item_id, "--by", "alice", "--reason", "noise"])
    assert rc == 0
    assert fi.open_items(repo, "tp/x") == []

    rc = fi.main(["list", "--root", str(repo), "--branch", "tp/x"])
    assert rc == 0


def test_pr_loop_findings_from_normalize_codereview_anchor_per_function(tmp_path):
    """record_round receives normalize_codereview output: line_range [start, end], no
    `line`. Each item anchors on its enclosing def, so two findings in different
    functions of one file and class get distinct ids and an item waiver covers one."""
    repo, _base = make_repo(tmp_path)
    head = commit(repo, {"test_lib.py": "def test_a():\n    assert 1\n\n\n"
                                        "def test_b():\n    assert 2\n"}, "tests")
    raw = {"file": "test_lib.py", "summary": "pins an internal value", "class": "T",
           "blocking": True, "fragility_class": "change-detector",
           "reproducer": {"kind": "command", "argv": ["true"],
                          "expect": {"exit": 0, "stdout_contains": ""}}}
    findings = [review_merge.normalize_codereview({**raw, "line_range": [2, 2]}),
                review_merge.normalize_codereview({**raw, "line_range": [6, 6]})]
    assert all("line" not in f and f["blocking"] for f in findings)
    assert fi.record_round(repo, "tp/x", head, findings) == 2
    items = fi.open_items(repo, "tp/x")
    assert [(i["line"], i["anchor"]) for i in items] == [(2, "test_a"), (6, "test_b")]
    assert items[0]["id"] != items[1]["id"]
    fi.waive(repo, "tp/x", items[0]["id"], by="op", reason="false positive")
    assert [i["anchor"] for i in fi.open_items(repo, "tp/x")] == ["test_b"]


def test_start_line_accepts_int_range_string_and_pair():
    assert fi._start_line(7) == 7
    assert fi._start_line("3-9") == 3
    assert fi._start_line([4, 8]) == 4
    assert fi._start_line((5, 5)) == 5
    for bad in (None, "", "x-1", "\u00b2", [], ["4", 8], [True, 2], True, {"start": 1}):
        assert fi._start_line(bad) is None


def test_a_finding_on_a_decorator_line_anchors_on_the_def_it_decorates(tmp_path):
    """A parametrize table sits above the `def` line; a finding there belongs to the
    decorated test, so two tests' decorator findings keep distinct ids."""
    repo, _base = make_repo(tmp_path)
    head = commit(repo, {"test_lib.py": "import pytest\n\n"
                                        "@pytest.mark.parametrize('v', ['exact-a'])\n"
                                        "def test_a(v):\n    assert v\n\n\n"
                                        "@pytest.mark.parametrize('v', ['exact-b'])\n"
                                        "def test_b(v):\n    assert v\n"}, "tests")
    findings = [{**FINDING, "file": "test_lib.py", "line_range": [3, 3]},
                {**FINDING, "file": "test_lib.py", "line_range": [8, 8]}]
    assert fi.record_round(repo, "tp/x", head, findings) == 2
    items = fi.open_items(repo, "tp/x")
    assert [i["anchor"] for i in items] == ["test_a", "test_b"]
    fi.waive(repo, "tp/x", items[0]["id"], by="op", reason="false positive")
    assert [i["anchor"] for i in fi.open_items(repo, "tp/x")] == ["test_b"]
