"""test_fragility_lint_cli.py — the fragility lint's pure core, waivers and `scan`.

design: fragile-test-prevention (detailed-design-lint §Waivers, §Scoping and exit codes)

`lint_source` is called directly; `scan` runs in process through `main` with the
output captured. Output lines are parsed by their `path:line: <rule-id> [gating|flag]`
grammar and never substring-matched. Fixtures are source strings written to a temp
tree; nothing reads a live file.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import fragility_lint
from fragility_lint import Hit, lint_source, main, scan

TEST_PATH = "skills/_shared/test_sample.py"
PROD_PATH = "skills/_shared/sample.py"
LINT_SCRIPT = Path(fragility_lint.__file__).resolve()

GOLDEN = '''\
import hashlib
from pathlib import Path


def test_pin():
    body = Path("hooks/x.sh").read_bytes()
    assert hashlib.sha256(body).hexdigest() == "abc123"{tail}
'''
DENY = 'DENYLIST = {"a", "b"}\n'
CLEAN = "def test_ok():\n    assert 1 + 1 == 2\n"

_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<rule>[a-z0-9-]+) "
                   r"\[(?P<flag>gating|flag)\](?: (?P<rest>.*))?$")


def _parse(out: str) -> list[dict]:
    """The hit lines of `out`, by grammar; every other line is ignored."""
    return [m.groupdict() for m in map(_LINE.match, out.splitlines()) if m]


def _names(out: str) -> list[str]:
    return [Path(hit["path"]).name for hit in _parse(out)]


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _scan(capsys, *args: str) -> tuple[int, str]:
    code = main(["scan", *args])
    return code, capsys.readouterr().out


# --- lint_source: the pure core ---------------------------------------------------

def test_lint_source_returns_a_gating_hit_with_no_waiver():
    hits = lint_source(TEST_PATH, GOLDEN.format(tail=""))
    assert hits == [Hit(TEST_PATH, 7, "golden-hash", True, None)]


def test_lint_source_uses_the_side_of_the_path():
    assert lint_source(PROD_PATH, DENY) == [Hit(PROD_PATH, 1, "deny-literal", True, None)]
    assert lint_source(TEST_PATH, DENY) == []
    assert lint_source(TEST_PATH, CLEAN) == []


def test_lint_source_rules_argument_is_the_gating_set():
    source = GOLDEN.format(tail="")
    assert lint_source(TEST_PATH, source, []) == [Hit(TEST_PATH, 7, "golden-hash", False, None)]
    assert lint_source(TEST_PATH, source, ["golden-hash"])[0].gating is True
    assert lint_source(TEST_PATH, source, ["shape-pin"])[0].gating is False


def test_lint_source_raises_syntax_error_on_unparseable_text():
    with pytest.raises(SyntaxError):
        lint_source(TEST_PATH, "def (:\n")


# --- waivers, found by comment token and statement span ----------------------------

def test_waiver_on_the_hit_line_carries_its_reason():
    hits = lint_source(TEST_PATH, GOLDEN.format(tail="  # tp-allow-fragile: vendored blob"))
    assert hits == [Hit(TEST_PATH, 7, "golden-hash", True, "vendored blob")]


def test_empty_reason_does_not_waive_and_keeps_the_gating_flag():
    for tail in ("  # tp-allow-fragile:", "  # tp-allow-fragile:   "):
        (hit,) = lint_source(TEST_PATH, GOLDEN.format(tail=tail))
        assert (hit.gating, hit.waiver_reason) == (True, "")


def test_waiver_on_the_first_line_of_a_multi_line_statement_waives_every_hit_in_it():
    source = (
        "import ast\nimport inspect\n\n\n"
        "def test_boundary():\n"
        "    tree = ast.parse(  # tp-allow-fragile: import boundary\n"
        "        inspect.getsource(mod)\n"
        "    )\n"
    )
    hits = lint_source(TEST_PATH, source)
    assert {(h.line, h.rule_id) for h in hits} == {(6, "shape-pin"), (7, "shape-pin")}
    assert [h.waiver_reason for h in hits] == ["import boundary"] * 2


def test_waiver_on_a_standalone_line_directly_above_the_statement():
    source = GOLDEN.format(tail="").replace(
        "    assert", "    # tp-allow-fragile: pinned upstream\n    assert")
    (hit,) = lint_source(TEST_PATH, source)
    assert (hit.line, hit.waiver_reason) == (8, "pinned upstream")


def test_a_trailing_waiver_on_the_previous_statement_does_not_waive():
    source = GOLDEN.format(tail="").replace(
        "read_bytes()", "read_bytes()  # tp-allow-fragile: wrong statement")
    (hit,) = lint_source(TEST_PATH, source)
    assert hit.waiver_reason is None


def test_waiver_text_inside_a_string_is_not_a_waiver():
    source = GOLDEN.format(tail="").replace('"abc123"', '"# tp-allow-fragile: fake"')
    (hit,) = lint_source(TEST_PATH, source)
    assert hit.waiver_reason is None


def test_a_waiver_in_a_compound_body_does_not_reach_the_header():
    source = (
        "import inspect\n\n\n"
        "def test_a():\n"
        "    if inspect.getsource(mod):\n"
        "        x = 1  # tp-allow-fragile: only this line\n"
    )
    (hit,) = lint_source(TEST_PATH, source)
    assert (hit.line, hit.waiver_reason) == (5, None)


# --- scan: printing, exit codes ----------------------------------------------------

def test_scan_prints_one_line_per_hit_and_exits_zero(tmp_path, capsys):
    _write(tmp_path, "test_bad.py", GOLDEN.format(tail=""))
    _write(tmp_path, "prod.py", DENY)
    _write(tmp_path, "test_good.py", CLEAN)
    code, out = _scan(capsys, str(tmp_path))
    found = {(Path(h["path"]).name, int(h["line"]), h["rule"], h["flag"]) for h in _parse(out)}
    assert code == 0
    assert found == {("test_bad.py", 7, "golden-hash", "gating"),
                     ("prod.py", 1, "deny-literal", "gating")}
    assert len(_parse(out)) == 2


def test_scan_prints_a_waived_hit_with_its_reason_and_still_exits_zero(tmp_path, capsys):
    _write(tmp_path, "test_w.py", GOLDEN.format(tail="  # tp-allow-fragile: vendored blob"))
    code, out = _scan(capsys, str(tmp_path))
    (hit,) = _parse(out)
    assert code == 0
    assert (hit["rule"], hit["flag"]) == ("golden-hash", "gating")
    assert "[waived: vendored blob]" in hit["rest"]


def test_scan_marks_an_empty_waiver_and_keeps_it_gating(tmp_path, capsys):
    _write(tmp_path, "test_e.py", GOLDEN.format(tail="  # tp-allow-fragile:"))
    _, out = _scan(capsys, str(tmp_path))
    (hit,) = _parse(out)
    assert hit["flag"] == "gating"
    assert "waiver-empty" in hit["rest"] and "[waived" not in hit["rest"]


SKIPPED_DIRS = [".git", "__pycache__", "node_modules", "venv",
                "three-pillars-docs/completed-tp-designs"]


@pytest.mark.parametrize("skipped", SKIPPED_DIRS)
def test_scan_skips_uninteresting_directories(tmp_path, capsys, skipped):
    _write(tmp_path, "keep/test_keep.py", GOLDEN.format(tail=""))
    _write(tmp_path, f"{skipped}/test_hidden.py", GOLDEN.format(tail=""))
    if skipped == "venv":
        _write(tmp_path, "venv/pyvenv.cfg", "home = /usr/bin\n")
    _, out = _scan(capsys, str(tmp_path))
    assert _names(out) == ["test_keep.py"]


def test_scan_walks_a_directory_named_venv_that_holds_no_pyvenv_cfg(tmp_path, capsys):
    _write(tmp_path, "venv/test_real.py", GOLDEN.format(tail=""))
    _, out = _scan(capsys, str(tmp_path))
    assert _names(out) == ["test_real.py"]


def test_scan_of_an_unparseable_python_file_exits_two_and_names_it(tmp_path, capsys):
    _write(tmp_path, "test_broken.py", "def (:\n")
    _write(tmp_path, "test_bad.py", GOLDEN.format(tail=""))
    code, out = _scan(capsys, str(tmp_path))
    cannot = [ln for ln in out.splitlines() if ln.startswith("could-not-evaluate: ")]
    assert code == 2
    assert len(cannot) == 1 and re.match(r"^could-not-evaluate: .+test_broken\.py: .+", cannot[0])
    assert _names(out) == ["test_bad.py"]


def test_scan_of_a_missing_path_exits_two(tmp_path, capsys):
    code, out = _scan(capsys, str(tmp_path / "absent.py"))
    assert code == 2 and "could-not-evaluate: " in out


def test_scan_lists_a_code_file_as_skipped_and_ignores_markdown_and_json(tmp_path, capsys):
    js = _write(tmp_path, "web/app.js", "console.log(1)\n")
    _write(tmp_path, "notes.md", "# notes\n")
    _write(tmp_path, "data.json", "{}\n")
    code, out = _scan(capsys, str(tmp_path))
    skipped = [ln for ln in out.splitlines() if ln.startswith("skipped (non-python): ")]
    assert code == 0
    assert skipped == [f"skipped (non-python): {js}"]


def test_scan_accepts_file_arguments_and_the_rules_flag(tmp_path, capsys):
    bad = _write(tmp_path, "test_bad.py", GOLDEN.format(tail=""))
    code, out = _scan(capsys, str(bad), "--rules", str(tmp_path / "fragility-rules.json"))
    assert code == 0 and [h["rule"] for h in _parse(out)] == ["golden-hash"]


def test_scan_function_takes_the_gating_set(tmp_path):
    bad = _write(tmp_path, "test_bad.py", GOLDEN.format(tail=""))
    result = scan([str(bad)], rules=[])
    assert [(h.rule_id, h.gating) for h in result.hits] == [("golden-hash", False)]
    assert result.exit == 0


# --- --json ----------------------------------------------------------------------

def _json(capsys, *args: str) -> dict:
    code = main(["scan", *args, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit"] == code
    return payload


def test_json_shape(tmp_path, capsys):
    _write(tmp_path, "test_bad.py", GOLDEN.format(tail="  # tp-allow-fragile: vendored blob"))
    _write(tmp_path, "test_open.py", GOLDEN.format(tail=""))
    payload = _json(capsys, str(tmp_path))
    assert set(payload) == {"hits", "skipped", "could_not_evaluate",
                            "judge_dimension_required", "exit", "repo_rules"}
    assert payload["exit"] == 0 and payload["judge_dimension_required"] is False
    assert all(set(h) == {"path", "line", "rule", "gating", "waiver", "source"}
               for h in payload["hits"])
    by_name = {Path(h["path"]).name: h for h in payload["hits"]}
    assert by_name["test_bad.py"]["waiver"] == "vendored blob"
    assert by_name["test_open.py"]["waiver"] is None
    assert {h["rule"] for h in payload["hits"]} == {"golden-hash"}
    assert all(h["gating"] is True and h["source"] == "generic" for h in payload["hits"])


def test_json_flags_the_judge_dimension_for_a_skipped_code_file(tmp_path, capsys):
    js = _write(tmp_path, "app.js", "1\n")
    _write(tmp_path, "notes.md", "# n\n")
    payload = _json(capsys, str(tmp_path))
    assert payload["skipped"] == [str(js)]
    assert payload["judge_dimension_required"] is True


def test_json_leaves_the_judge_dimension_off_for_markdown_and_json_only(tmp_path, capsys):
    _write(tmp_path, "notes.md", "# n\n")
    _write(tmp_path, "data.json", "{}\n")
    payload = _json(capsys, str(tmp_path))
    assert (payload["skipped"], payload["judge_dimension_required"]) == ([], False)


def test_json_lists_a_could_not_evaluate_file_and_exits_two(tmp_path, capsys):
    _write(tmp_path, "test_broken.py", "def (:\n")
    payload = _json(capsys, str(tmp_path))
    assert payload["exit"] == 2 and len(payload["could_not_evaluate"]) == 1
    assert "test_broken.py" in payload["could_not_evaluate"][0]


def test_runs_as_a_script(tmp_path):
    _write(tmp_path, "test_bad.py", GOLDEN.format(tail=""))
    proc = subprocess.run([sys.executable, str(LINT_SCRIPT), "scan", str(tmp_path)],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert [h["rule"] for h in _parse(proc.stdout)] == ["golden-hash"]
