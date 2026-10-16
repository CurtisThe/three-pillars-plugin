"""test_fragility_rules_flag_regex_clock.py — the flag-only rules `prose-regex` (production
side) and `wall-clock` (test side), and their promotion by `fragility.gating_rules`.

design: fragile-test-prevention (detailed-design-lint §Rule registry, §Scoping and exit codes)

Every case is a source string parsed here: a line ending in `# HIT` must be reported by the
rule under test and no other line may be; a source with no marker is a counter-example that
passes. Promotion is checked in a real temp git repo whose `.three-pillars/config.json`
names the gating set, through the lint's own `check` path and the config loader.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path

import pytest

import repo_config_load
from fragility_lint import check_diff, lint_source, main
from fragility_rules_flag import visit

TEST_PATH = "skills/_shared/test_sample.py"
PROD_PATH = "skills/_shared/sample.py"


def mod(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def fn(*body: str) -> str:
    return "\n".join(["def test_a():", *(f"    {line}" for line in body)]) + "\n"


MD_CONST = 'DOC = Path("skills/x/SKILL.md")'
TABLES = {
    "prose-regex": [
        ("re call beside a .md constant path read",
         mod("import re", MD_CONST, "def f():",
             "    text = DOC.read_text(encoding='utf-8')",
             "    return re.findall(r'^## (.+)$', text)  # HIT")),
        ("re call beside plan_tasks",
         mod("import re", "def f(plan):", "    tasks = plan_tasks(plan)",
             "    return re.match(r'Task', tasks[0])  # HIT")),
        ("re call beside extract_tasks",
         mod("import re", "def f(plan):", "    tasks = extract_tasks(plan)",
             "    return re.search(r'Task', tasks[0])  # HIT")),
        ("re call beside captured console output",
         mod("import re, subprocess", "def f():",
             "    out = subprocess.run(['ls'], capture_output=True, text=True).stdout",
             "    return re.split(r'\\s+', out)  # HIT")),
        ("re call beside check_output",
         mod("import re, subprocess", "def f():",
             "    out = subprocess.check_output(['ls'], text=True)",
             "    return re.sub(r'a', 'b', out)  # HIT")),
        ("re alone, no prose source", mod("import re", "def f(s):", "    return re.match(r'a', s)")),
        ("prose source without re",
         mod(MD_CONST, "def f():", "    return DOC.read_text(encoding='utf-8')")),
        ("a subprocess run without capture",
         mod("import re, subprocess", "def f(s):", "    subprocess.run(['ls'])",
             "    return re.match(r'a', s)")),
    ],
    "wall-clock": [
        ("time.sleep in a test", "import time\n" + fn("time.sleep(1)  # HIT")),
        ("elapsed difference asserted against a number",
         "import time\n" + fn("start = time.monotonic()", "run()",
                              "assert time.monotonic() - start < 2  # HIT")),
        ("elapsed held in a name",
         "import time\n" + fn("t0 = time.perf_counter()", "run()",
                              "elapsed = time.perf_counter() - t0",
                              "assert elapsed <= 0.5  # HIT")),
        ("time.time difference against a number",
         "import time\n" + fn("t0 = time.time()", "run()", "assert 3 > time.time() - t0  # HIT")),
        ("an injected clock passes",
         fn("clock = FakeClock()", "start = clock()", "run(clock)",
            "assert clock() - start == 5")),
        ("an injected sleep passes", fn("sleeper = FakeSleep()", "run(sleeper)",
                                        "assert sleeper.total == 5")),
        ("a clock difference compared with a computed value",
         "import time\n" + fn("t0 = time.time()", "run()", "assert time.time() - t0 < budget")),
    ],
}
ROWS = [(rule, name, src) for rule, cases in TABLES.items() for name, src in cases]
PATHS = {"prose-regex": PROD_PATH, "wall-clock": TEST_PATH}
OTHER = {"prose-regex": TEST_PATH, "wall-clock": PROD_PATH}


def _marked(src: str) -> list[int]:
    return [n for n, line in enumerate(src.splitlines(), 1) if "# HIT" in line]


def _hits(src: str, path: str, rule_id: str) -> list[int]:
    return [f.line for f in visit(ast.parse(src), path, None) if f.rule_id == rule_id]


@pytest.mark.parametrize("rule_id, name, src", ROWS, ids=[f"{r}: {n}" for r, n, _ in ROWS])
def test_each_example_is_flagged_and_each_counter_example_passes(rule_id, name, src):
    assert _hits(src, PATHS[rule_id], rule_id) == _marked(src)


@pytest.mark.parametrize("rule_id, name, src", ROWS, ids=[f"{r}: {n}" for r, n, _ in ROWS])
def test_a_rule_fires_only_on_its_own_side(rule_id, name, src):
    assert _hits(src, OTHER[rule_id], rule_id) == []


def test_a_waiver_naming_the_grammar_waives_the_prose_regex_hit():
    src = mod("import re", MD_CONST, "def f():",
              "    text = DOC.read_text(encoding='utf-8')",
              "    return re.findall(r'^## (.+)$', text)  # tp-allow-fragile: closed grammar")
    hits = lint_source(PROD_PATH, src)
    assert [(h.rule_id, h.waived, h.gating) for h in hits] == [("prose-regex", True, False)]


def test_a_flag_hit_without_a_waiver_is_reported_unwaived_and_not_gating():
    src = dict(TABLES["wall-clock"])["time.sleep in a test"]
    hits = lint_source(TEST_PATH, src)
    assert [(h.rule_id, h.waived, h.gating) for h in hits] == [("wall-clock", False, False)]


# --- promotion by config, in a real temp git repo ------------------------------------------

@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=root,
                          capture_output=True, text=True, check=True, encoding="utf-8")
    return done.stdout.strip()


def _commit(root: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", "c")
    return _git(root, "rev-parse", "HEAD")


def _repo(tmp_path: Path, monkeypatch, config: dict | None) -> tuple[Path, str]:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    monkeypatch.chdir(tmp_path)
    files = {"README.md": "# demo\n"}
    if config is not None:
        files[".three-pillars/config.json"] = json.dumps({"schema_version": 1, **config})
    return tmp_path, _commit(tmp_path, files)


SLEEPS = "import time\n\ndef test_slow():\n    time.sleep(1)\n"


def test_a_promoted_flag_rule_gates_a_check(tmp_path, monkeypatch, capsys):
    root, base = _repo(tmp_path, monkeypatch, {"fragility": {"gating_rules": ["wall-clock"]}})
    _commit(root, {TEST_PATH: SLEEPS})
    assert main(["check", "--base", base]) == 1
    assert "wall-clock [gating]" in capsys.readouterr().out


def test_the_same_diff_does_not_block_without_the_promotion(tmp_path, monkeypatch):
    root, base = _repo(tmp_path, monkeypatch, None)
    _commit(root, {TEST_PATH: SLEEPS})
    result = check_diff(root, base)
    assert result.exit == 0
    assert [h.rule_id for h in result.hits] == ["wall-clock"]


def test_a_waived_promoted_hit_does_not_block(tmp_path, monkeypatch):
    root, base = _repo(tmp_path, monkeypatch, {"fragility": {"gating_rules": ["wall-clock"]}})
    waived = SLEEPS.replace("time.sleep(1)", "time.sleep(1)  # tp-allow-fragile: real timer")
    _commit(root, {TEST_PATH: waived})
    assert check_diff(root, base).exit == 0


def test_an_unknown_rule_id_in_the_gating_set_exits_two(tmp_path, monkeypatch):
    root, base = _repo(tmp_path, monkeypatch, {"fragility": {"gating_rules": ["no-such-rule"]}})
    _commit(root, {TEST_PATH: SLEEPS})
    assert main(["check", "--base", base]) == 2


def test_the_config_loader_keeps_the_fragility_block(tmp_path, monkeypatch):
    block = {"gating_rules": ["wall-clock"], "strict": True}
    root, _ = _repo(tmp_path, monkeypatch, {"fragility": block})
    loaded = repo_config_load.load_repo_config(root)
    assert loaded.config["fragility"] == block
    assert loaded.warnings == []
