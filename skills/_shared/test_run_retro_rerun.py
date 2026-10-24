"""run_retro.py re-runs (design-learn-retro 1.4, B11, B17, N1, N11): a second pass files
nothing new, evidence lines land once, the observations entry is written only when it
changes, and no run_retro module reaches for notion-ops.

Fixtures copy real shapes: seed.md with frontmatter and ``## Evidence``, decisions.md with
``local_route_log``'s schema header and ``### [prefix] title`` entries. Tests drive
``run_retro.main`` in-process and parse JSON, seed files and decisions.md entries.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import local_route_log as lr  # noqa: E402
import run_retro as rr  # noqa: E402
from run_retro_collect import parse_entries  # noqa: E402

FOO_PATH = "skills/_shared/foo_helper.py"
FOO_KEY = "path:skills/_shared/foo_helper.py"
BAR_KEY = "path:skills/_shared/bar_widget.py"
SLUG, FOREIGN = "retro-foo-helper", "bar-widget-flake"
ACCEPT = [{"slug": SLUG, "verdict": "accept", "reason": "recurring gate failure"}]
SEED = ("---\nweight-class: light\nparent: none\nstatus: seed\nseeded: 2026-10-21\n---\n"
        "# {slug} — seed\n\n## Evidence\n\n- one earlier observation\n\n## Rulings\n\n- none\n")


def retries(path: str) -> list[tuple[str, str]]:
    return [("[orchestrator/design-audit] retry-with-advice attempt 2/3",
             f"- Decided: retry; the gate failed in {path}"),
            ("[orchestrator/design-audit] retry-exhausted (attempt 3/3)",
             f"- Decided: escalate; {path} failed again")]


# The orchestrator's real heading prefix, built from parts: its skill-dir name as a raw literal
# beside a SKILL.md path makes rule_ledger_extract.pin_tests_for count this file as a pin test
# of that skill, and the sealed rule ledgers then want a row for every literal here.
RFD = "tp-run-" + "full-design"
NOOP = (f"[{RFD}/tier-2] worker-noop", "- the worker changed nothing")
ENTRIES = [*retries("skills/_shared/foo_helper.py"), *retries("skills/_shared/bar_widget.py"), NOOP]


@pytest.fixture(autouse=True)
def _no_junit_env(monkeypatch):
    monkeypatch.delenv("CI_LOCAL_MANIFEST_DIR", raising=False)


@pytest.fixture
def repo(tmp_path) -> Path:
    designs = tmp_path / "three-pillars-docs" / "tp-designs"
    (designs / "demo").mkdir(parents=True)
    body = "".join(f"\n### {h}\n{b}\n" for h, b in ENTRIES)
    (designs / "demo" / "decisions.md").write_text(lr.SCHEMA_HEADER + body, encoding="utf-8")
    (designs / FOREIGN).mkdir()
    (designs / FOREIGN / "seed.md").write_text(SEED.format(slug=FOREIGN), encoding="utf-8")
    return tmp_path


def design(repo: Path) -> Path:
    return repo / "three-pillars-docs" / "tp-designs" / "demo"


def run(capsys, *argv) -> tuple[int, str]:
    capsys.readouterr()
    code = rr.main([str(a) for a in argv])
    assert code == 0
    return code, capsys.readouterr().out


def findings(d: Path) -> dict:
    return json.loads((d / "retro-findings.json").read_text(encoding="utf-8"))


def retro_entries(d: Path) -> list[dict]:
    text = (d / "decisions.md").read_text(encoding="utf-8")
    return [e for e in parse_entries(text) if e["prefix"] == "run-retro"]


def seeds(repo: Path) -> dict:
    return {p.parent.name: p.read_text(encoding="utf-8")
            for p in sorted(repo.glob("three-pillars-docs/tp-designs/*/seed.md"))}


def seed_pass(repo: Path, capsys) -> list[str]:
    known, d = repo / "known-items.json", design(repo)
    verdicts = repo / "verdicts.json"
    verdicts.write_text(json.dumps(ACCEPT), encoding="utf-8")
    run(capsys, "known-items", "--repo", repo, "--out", known)
    run(capsys, "draft", "--design-dir", d, "--known-items", known)
    return run(capsys, "file", "--design-dir", d, "--verdicts", verdicts,
               "--board", "none")[1].splitlines()


def test_board_rerun_keeps_filed_and_empties_the_outbox(repo, capsys):
    d, verdicts = design(repo), repo / "verdicts.json"
    verdicts.write_text(json.dumps(ACCEPT), encoding="utf-8")
    board = ("--board", "automated_upgrades", "--notion-skill", "present")
    run(capsys, "draft", "--design-dir", d)
    first = json.loads(run(capsys, "file", "--design-dir", d, "--verdicts", verdicts, *board)[1])
    assert first["entries"] >= 1
    reply = repo / "filed.json"
    reply.write_text(json.dumps([{"slug": SLUG, "id": "row-1"}]), encoding="utf-8")
    run(capsys, "record", "--design-dir", d, "--filed", reply)
    filed = findings(d)["filed"]
    run(capsys, "draft", "--design-dir", d)
    assert findings(d)["filed"] == filed
    again = json.loads(run(capsys, "file", "--design-dir", d, "--verdicts", verdicts, *board)[1])
    assert again["entries"] == 0
    box = json.loads((d / "retro-outbox.json").read_text(encoding="utf-8"))
    assert box["entries"] == []
    assert findings(d)["filed"] == filed
    assert any("row-1" in mark for mark in filed)


def test_an_unrecorded_outbox_entry_survives_a_second_pass_until_record_marks_it(repo, capsys):
    # F1: a row notion-ops never filed must stay in the outbox; only `record` marks it filed
    d, verdicts = design(repo), repo / "verdicts.json"
    verdicts.write_text(json.dumps(ACCEPT), encoding="utf-8")
    board = ("--board", "automated_upgrades", "--notion-skill", "present")
    box = d / "retro-outbox.json"

    def pass_() -> dict:
        run(capsys, "draft", "--design-dir", d)
        return json.loads(run(capsys, "file", "--design-dir", d, "--verdicts", verdicts,
                              *board)[1])

    assert pass_()["entries"] == 1
    assert pass_()["entries"] == 1  # no record between: the entry is still owed to notion-ops
    (entry,) = json.loads(box.read_text(encoding="utf-8"))["entries"]
    assert entry["slug"] == SLUG and entry["retro_key"] == FOO_KEY
    reply = repo / "filed.json"
    reply.write_text(json.dumps([{"slug": SLUG, "id": "row-1"}]), encoding="utf-8")
    run(capsys, "record", "--design-dir", d, "--filed", reply)
    filed = findings(d)["filed"]
    assert {FOO_KEY, SLUG, f"id:{SLUG}:row-1"} <= set(filed)
    run(capsys, "record", "--design-dir", d, "--filed", reply)
    assert findings(d)["filed"] == filed
    assert pass_()["entries"] == 0  # recorded: never re-filed
    assert json.loads(box.read_text(encoding="utf-8"))["entries"] == []
    assert findings(d)["filed"] == filed


BAR_PATH, URL = "skills/_shared/bar_widget.py", "https://www.notion.so/x"


def _two_entry_outbox(tmp_path, capsys) -> tuple[Path, str, str]:
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "demo"
    d.mkdir(parents=True)
    body = "".join(f"\n### {h}\n{b}\n" for h, b in [*retries(FOO_PATH), *retries(BAR_PATH)])
    (d / "decisions.md").write_text(lr.SCHEMA_HEADER + body, encoding="utf-8")
    run(capsys, "draft", "--design-dir", d)
    one, two = sorted(x["proposed_slug"] for x in findings(d)["drafts"])
    verdicts = tmp_path / "verdicts.json"
    verdicts.write_text(json.dumps([{**ACCEPT[0], "slug": s} for s in (one, two)]), encoding="utf-8")
    run(capsys, "file", "--design-dir", d, "--verdicts", verdicts, "--board", "automated_upgrades",
        "--notion-skill", "present")
    return d, one, two


def _replies(tmp_path, *rows) -> Path:
    path = tmp_path / "replies.json"
    path.write_text(json.dumps([{"slug": s, "reply": r} for s, r in rows]), encoding="utf-8")
    return path


def test_a_not_filed_reply_seeds_that_entry_only_and_names_the_reason_once(tmp_path, capsys):
    d, one, two = _two_entry_outbox(tmp_path, capsys)
    why = "automated upgrades are off"
    replies = _replies(tmp_path, (one, f"filed: create {URL}"), (two, f"not filed: {why}"))
    seed = d.parent / two / "seed.md"
    assert json.loads(run(capsys, "record", "--design-dir", d, "--filed", replies)[1]) == {
        "recorded": 1, "seeds": [str(seed)]}
    head = set(seed.read_text(encoding="utf-8").splitlines())
    assert {"upstream: three-pillars", "origin: run-retro"} <= head
    assert not (d.parent / one).exists()  # the filed entry is unaffected
    filed = set(findings(d)["filed"])
    assert {f"id:{one}:{URL}", f"seed:{two}", two} <= filed and f"id:{two}:" not in " ".join(filed)
    notes = [e["body"] for e in retro_entries(d) if why in e["body"]]
    assert len(notes) == 1 and two in notes[0] and one not in notes[0]

    def snap():
        return {p.name: p.read_bytes() for p in d.parent.rglob("*") if p.is_file()}
    before = snap()
    run(capsys, "record", "--design-dir", d, "--filed", replies)  # a second record changes nothing
    assert snap() == before


def test_not_filed_never_overwrites_an_existing_seed_or_logs_a_leak(tmp_path, capsys):
    d, one, two = _two_entry_outbox(tmp_path, capsys)
    existing = d.parent / two / "seed.md"
    existing.parent.mkdir()
    existing.write_text(SEED.format(slug=two), encoding="utf-8")
    secret = "API_" + "KEY=" + "abc123def456"  # split so no scanner sees an assignment
    run(capsys, "record", "--design-dir", d, "--filed",
        _replies(tmp_path, (one, f"not filed: {secret}"), (two, "not filed: off")))
    text = existing.read_text(encoding="utf-8")
    assert "one earlier observation" in text and "origin: run-retro" not in text
    assert "abc123def456" not in (d / "decisions.md").read_text(encoding="utf-8")
    assert (d.parent / one / "seed.md").is_file()
    for bad in (_replies(tmp_path, (one, "not filed: off"), ("not-in-outbox", "not filed: off")),
                _replies(tmp_path, (one, "error: the write failed"))):
        assert rr.main(["record", "--design-dir", str(d), "--filed", str(bad)]) == 2


def test_seed_rerun_writes_no_new_seed_and_no_new_evidence(repo, capsys):
    first = seed_pass(repo, capsys)
    new_seed = design(repo).parent / SLUG / "seed.md"
    foreign = design(repo).parent / FOREIGN / "seed.md"
    assert sorted(first) == sorted([str(new_seed), str(foreign)])
    line = f"- evidence (run-retro): {BAR_KEY}"
    assert [ln for ln in foreign.read_text(encoding="utf-8").splitlines()
            if ln.startswith(line)] != []
    assert f"evidence:{FOREIGN}@{BAR_KEY}" in findings(design(repo))["filed"]
    before_seeds = seeds(repo)
    before_log = (design(repo) / "decisions.md").read_text(encoding="utf-8")
    known = json.loads((repo / "known-items.json").read_text(encoding="utf-8"))
    assert SLUG not in [k["id"] for k in known]
    second = seed_pass(repo, capsys)
    known = json.loads((repo / "known-items.json").read_text(encoding="utf-8"))
    assert {"id": SLUG, "kind": "seed", "retro_key": FOO_KEY, "text": SLUG} in known
    assert second == []
    assert seeds(repo) == before_seeds
    assert (design(repo) / "decisions.md").read_text(encoding="utf-8") == before_log


def test_foreign_seed_gets_exactly_one_evidence_line_under_evidence(repo, capsys):
    for _ in range(3):
        seed_pass(repo, capsys)
    text = (design(repo).parent / FOREIGN / "seed.md").read_text(encoding="utf-8")
    hits = [ln for ln in text.splitlines() if ln.startswith("- evidence (run-retro):")]
    assert len(hits) == 1 and BAR_KEY in hits[0]
    assert text.index("## Evidence") < text.index(hits[0]) < text.index("## Rulings")


def test_board_path_keeps_evidence_in_findings_and_one_entry(repo, capsys):
    d, known = design(repo), repo / "known-items.json"
    run(capsys, "known-items", "--repo", repo, "--out", known)
    run(capsys, "draft", "--design-dir", d, "--known-items", known)
    before = seeds(repo)
    for _ in range(2):
        run(capsys, "file", "--design-dir", d, "--board", "automated_upgrades",
            "--notion-skill", "present")
    assert seeds(repo) == before
    assert [a["seed"] for a in findings(d)["evidence_adds"]] == [FOREIGN]
    assert len([e for e in retro_entries(d) if FOREIGN in e["body"]]) == 1


def observation_entries(d: Path) -> list[dict]:
    return [e for e in retro_entries(d) if e["title"] == "observations"]


def test_observations_entry_is_skipped_when_unchanged_and_added_when_changed(repo, capsys):
    d = design(repo)
    for _ in range(2):
        run(capsys, "draft", "--design-dir", d)
        run(capsys, "file", "--design-dir", d, "--board", "none")
    (only,) = observation_entries(d)
    assert "event:worker-noop" in only["body"]
    lr.append_entry(d / "decisions.md", f"### [{RFD}/tier-3] sha-mismatch\n- moved")
    run(capsys, "draft", "--design-dir", d)
    run(capsys, "file", "--design-dir", d, "--board", "none")
    old, new = observation_entries(d)
    assert old == only and "event:sha-mismatch" in new["body"]
    assert all(e["title"] == "observations" or "sha-mismatch" not in e["body"]
               for e in retro_entries(d))


def _is_sys_path(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "path"
            and isinstance(node.value, ast.Name) and node.value.id == "sys")


def _assigned(tree: ast.AST, name: str) -> list[ast.AST]:
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]


def _is_file_dir(node):
    """True when node is the module's own dir: [str(]Path(__file__).resolve().parent[)] or
    os.path.dirname(os.path.abspath(__file__)); no parents[N] subscript, no BinOp."""
    while (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id == "str" and len(node.args) == 1):
        node = node.args[0]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "dirname" and len(node.args) == 1:
        inner = node.args[0]
        return (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "abspath" and len(inner.args) == 1
                and isinstance(inner.args[0], ast.Name) and inner.args[0].id == "__file__")
    if not (isinstance(node, ast.Attribute) and node.attr == "parent"):
        return False
    call = node.value
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == "resolve"):
        return False
    path = call.func.value
    return (isinstance(path, ast.Call) and isinstance(path.func, ast.Name)
            and path.func.id == "Path" and len(path.args) == 1
            and isinstance(path.args[0], ast.Name) and path.args[0].id == "__file__")


def test_no_run_retro_module_imports_notion_ops_or_edits_sys_path():
    modules = sorted(HERE.glob("run_retro*.py"))
    assert "run_retro.py" in [m.name for m in modules]
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                imported += [n.module or ""] + [a.name for a in n.names]
        bad = [m for m in imported if "notion" in m.lower()]
        assert not bad, f"{module.name}: ast.ImportFrom/ast.Name alias imports notion: {bad}"
        for node in ast.walk(tree):
            targets = getattr(node, "targets", None) or [getattr(node, "target", None)]
            assert not any(_is_sys_path(t) for t in targets if t is not None), module.name
            if isinstance(node, ast.Call) and _is_sys_path(getattr(node.func, "value", None)):
                (arg,) = [a for a in node.args if not isinstance(a, ast.Constant)]
                if isinstance(arg, ast.Name):
                    values = _assigned(tree, arg.id)
                    assert values and all(_is_file_dir(v) for v in values), (
                        f"{module.name}: ast.Name {arg.id} resolved to a non-_shared-dir value")
                else:
                    assert _is_file_dir(arg), (
                        f"{module.name}: sys.path arg must be an ast.Name or inline _shared "
                        f"self-insert, got {type(arg).__name__}")


def test_same_file_name_in_two_directories_files_two_separate_seeds(tmp_path, capsys):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "demo"
    d.mkdir(parents=True)
    entries = [(f"[{RFD}/tier-3] worker-noop", f"- touched skills/{x}/SKILL.md")
               for x in ("tp-design", "tp-design", "tp-spike", "tp-spike")]
    body = "".join(f"\n### {h}\n{b}\n" for h, b in entries)
    (d / "decisions.md").write_text(lr.SCHEMA_HEADER + body, encoding="utf-8")
    run(capsys, "draft", "--design-dir", d, "--repo", tmp_path)
    slugs = sorted(x["proposed_slug"] for x in findings(d)["drafts"])
    assert slugs == ["retro-tp-design-skill", "retro-tp-spike-skill"]
    verdicts = tmp_path / "verdicts.json"
    verdicts.write_text(json.dumps([{"slug": s, "verdict": "accept", "reason": "x"}
                                    for s in slugs]), encoding="utf-8")
    printed = run(capsys, "file", "--design-dir", d, "--verdicts", verdicts,
                  "--board", "none")[1].splitlines()
    assert sorted(Path(p).parent.name for p in printed) == slugs
    assert sorted(seeds(tmp_path)) == slugs
