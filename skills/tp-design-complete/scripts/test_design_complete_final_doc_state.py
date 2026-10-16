"""`/tp-design-complete` runs `final_doc_state.py close` and `check`, and writes the PR number back.

design: design-complete-final-doc-state (plan task 3.1). Oracle: example, per
`skills/_shared/test-fragility.md`. No assert here reads a heading, a section or a phrase out of
the SKILL.md prose: commands come through `skill_spans` (the `_commands` / `_calls_of` pattern of
`test_design_complete_skill_md.py`), and the shipped `close` line and its `paths[]` staging loop
are run verbatim in a fixture repo (the `_shipped` approach of `test_post_merge_inventory_wiring.py`).

Run with: python3 -m pytest skills/tp-design-complete/scripts/test_design_complete_final_doc_state.py -q
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
SKILL_MD = SCRIPTS.parent / "SKILL.md"
REPO_ROOT = SCRIPTS.parents[2]
SHARED = REPO_ROOT / "skills" / "_shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

_VARIABLE = re.compile(r"\$\w+")
SLUG = "fixture-design"
DOCS = "three-pillars-docs"
LIVE = f"{DOCS}/product_roadmap.md"
ARCHIVE = f"{DOCS}/product_roadmap_archive.md"
DONE_DIR = f"{DOCS}/completed-tp-designs/{SLUG}"
PENDING, NUMBERLESS = "Completion PR pending", "Done (completion PR)"
ROW = f"| {SLUG} | Fixture. | design | {PENDING} — [design]({DONE_DIR}/design.md) | Docs |"


def _words(tokens: list[str]) -> list[str]:
    """A span's tokens, with a `VAR="$(cmd ...)"` capture split back into the command's words."""
    words: list[str] = []
    for token in tokens:
        if " " in token:
            inner = re.sub(r"^\w+=\$\(", "", token).removesuffix(")")
            try:
                words.extend(shlex.split(inner))
                continue
            except ValueError:
                pass
        words.append(token)
    return words


def _commands() -> list[list[str]]:
    """Every command the SKILL.md shows, in document order, read through `skill_spans`."""
    skill_spans = pytest.importorskip("skill_spans")
    found = []
    for _line, span, shell in skill_spans.code_spans(SKILL_MD.read_text(encoding="utf-8")):
        try:
            found.append(_words(skill_spans.tokens_of(span, shell)))
        except ValueError:  # a span that is not a shell command at all
            continue
    return found


def _calls_of(script: str) -> list[tuple[int, list[str]]]:
    """`(position, args)` of every `python3 <...>/<script> args...` command, in document order."""
    return [(pos, words[i + 2:]) for pos, words in enumerate(_commands())
            for i in range(len(words) - 1)
            if words[i] == "python3" and words[i + 1].endswith("/" + script)]


def _verb_calls(verb: str) -> list[tuple[int, list[str]]]:
    """Every `final_doc_state.py <verb>` call. How many there are is the order test's to pin."""
    hits = [(pos, args) for pos, args in _calls_of("final_doc_state.py") if args[:1] == [verb]]
    assert hits, f"the SKILL.md must run final_doc_state.py {verb}"
    return hits


def _writeback_calls() -> list[tuple[int, list[str]]]:
    return [(pos, args) for pos, args in _calls_of("reconcile_docs.py") if "--pre-merge" in args]


def _positions(match) -> list[int]:
    return [pos for pos, words in enumerate(_commands()) if match(words)]


def _flag_value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_close_and_check_are_called_for_the_design(tmp_path):
    """Both verbs name the design with `--slug {design-name}` and parse with the script's argparse."""
    argparse_probe = pytest.importorskip("argparse_probe")
    for verb in ("close", "check"):
        for _pos, args in _verb_calls(verb):
            assert _flag_value(args, "--slug") == "{design-name}", f"{verb} does not name the design: {args}"
            assert "--json" in args, f"{verb} does not ask for --json: {args}"
            probe = argparse_probe.probe(SHARED / "final_doc_state.py", args, cache_dir=tmp_path)
            assert probe["status"] == "parsed", f"{verb} does not parse: {probe['message']}"


def test_pre_merge_writeback_names_the_design_and_the_pr(tmp_path):
    """The PR-number writeback is `reconcile_docs.py --slug {design-name} --pre-merge --pr {n}`
    with `--apply --json` (it edits, and prints the edited paths to stage)."""
    argparse_probe = pytest.importorskip("argparse_probe")
    calls = _writeback_calls()
    assert calls, "step 6g must run the --pre-merge writeback"
    for _pos, args in calls:
        assert _flag_value(args, "--slug") == "{design-name}", f"writeback does not name the design: {args}"
        assert {"--pr", "--apply", "--json"} <= set(args), f"writeback lacks --pr/--apply/--json: {args}"
        probe = argparse_probe.probe(SHARED / "reconcile_docs.py",
                                     [a.replace("{n}", "1") for a in args], cache_dir=tmp_path)
        assert probe["status"] == "parsed", f"writeback does not parse: {probe['message']}"


def test_recovery_path_is_pointed_at_not_restated():
    """The SKILL.md names `final-doc-state.md`, which holds the drift recovery and the writeback."""
    skill_spans = pytest.importorskip("skill_spans")
    named = [span for _line, span, _shell in skill_spans.code_spans(SKILL_MD.read_text(encoding="utf-8"))
             if "skills/_shared/final-doc-state.md" in span]
    assert named, "the SKILL.md must point at skills/_shared/final-doc-state.md"
    assert (SHARED / "final-doc-state.md").is_file()


def test_command_order_close_guard_commit_check_create_writeback_review():
    """`close` -> staged-blob guard -> archival commit -> `check` (commit first, then check: plan
    deviation 3) -> PR create -> `--pre-merge` writeback -> review request. Each step runs exactly
    once, so no stray copy (say a writeback left in place while another runs after the review
    request) can sit outside its slot; then each adjacent pair is checked on its own."""
    steps = [
        ("close", [pos for pos, _args in _verb_calls("close")]),
        ("staged-blob guard", [pos for pos, _args in _calls_of("verify_archive_staged.py")]),
        ("archival commit", _positions(lambda w: w[:2] == ["git", "commit"] and "Complete" in w)),
        ("check", [pos for pos, _args in _verb_calls("check")]),
        ("PR create", _positions(lambda w: "python3" in w and any(
            _VARIABLE.fullmatch(t) for t in w) and "pr-create" in w and "--context" in w)),
        ("--pre-merge writeback", [pos for pos, _args in _writeback_calls()]),
        ("review request", _positions(
            lambda w: w[:2] == ["gh", "api"] and any(t.startswith("reviewers[]=") for t in w))),
    ]
    for name, at in steps:
        assert len(at) == 1, f"step count: the {name} must run exactly once, found at command positions {at}"
    for (first, (at_first,)), (then, (at_then,)) in zip(steps, steps[1:]):
        assert at_first < at_then, (
            f"out of order: the {first} (command {at_first}) must precede the {then} (command {at_then})")


# --- the shipped `close` line and its `paths[]` staging loop, run verbatim ----------------------


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=f", "-c", "user.email=f@t", *args],
                          capture_output=True, text=True, check=True, env=_env()).stdout


def _bound(command: str) -> str:
    """The shipped text, its placeholders bound to this checkout and the fixture design."""
    return command.replace('"$TP_ROOT"', shlex.quote(str(REPO_ROOT))).replace("{design-name}", SLUG)


def _shipped_close() -> list[str]:
    """The `FINAL_JSON="$(... close ...)"` capture of step 6f as an argv (the capture wrapper removed)."""
    skill_spans = pytest.importorskip("skill_spans")
    spans = [span for _line, span, _shell in skill_spans.code_spans(SKILL_MD.read_text(encoding="utf-8"))
             if span.startswith("FINAL_JSON=") and "final_doc_state.py" in span]
    assert len(spans) == 1, f"step 6f must capture one FINAL_JSON from `close`, got {spans}"
    argv = shlex.split(_bound(spans[0].removeprefix('FINAL_JSON="$(').removesuffix(')"')))
    assert argv[0] == "python3" and "close" in argv
    argv[0] = sys.executable
    return argv


def _shipped_loop() -> str:
    """The `for ... "$FINAL_JSON" ...; done` staging loop of step 6f, verbatim from the SKILL.md."""
    lines = [ln.strip() for ln in SKILL_MD.read_text(encoding="utf-8").splitlines()]
    start = next((i for i, ln in enumerate(lines) if ln.startswith("for ") and "$FINAL_JSON" in ln), None)
    assert start is not None, "step 6f must stage the FINAL_JSON paths[] by a for loop"
    end = next(i for i in range(start, len(lines)) if re.search(r"(^|[;\s])done$", lines[i]))
    return "\n".join(lines[start:end + 1])


def _fixture(root: Path) -> None:
    _git(root, "init", "-q", "-b", "master")
    (root / DOCS / "tp-designs" / SLUG).mkdir(parents=True)
    (root / DOCS / "tp-designs" / SLUG / "design.md").write_text("# d\n", encoding="utf-8")
    (root / LIVE).write_text("\n".join([
        "# Product Roadmap", "", "## Design Inventory", "", "### Active", "",
        "| Name | What | Type | Status | Track |", "|---|---|---|---|---|",
        "| other | Stays live. | design | Seed | Docs |", ROW, "",
    ]) + "\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "designed")
    (root / DOCS / "completed-tp-designs").mkdir()
    _git(root, "mv", f"{DOCS}/tp-designs/{SLUG}", DONE_DIR)  # step 6c, before step 6f


def test_shipped_close_moves_and_flips_and_its_paths_loop_stages_the_two_roadmap_files(tmp_path):
    _fixture(tmp_path)
    staged_before = set(_git(tmp_path, "diff", "--cached", "--name-only").split())

    ran = subprocess.run(_shipped_close(), cwd=tmp_path, capture_output=True, text=True, env=_env())

    assert ran.returncode == 0, ran.stdout + ran.stderr
    payload = json.loads(ran.stdout)
    assert payload["moved"] > 0 and payload["refused"] is None
    assert sorted(payload["paths"]) == sorted([ARCHIVE, LIVE])
    done_row = ROW.replace(PENDING, NUMBERLESS)
    assert done_row in (tmp_path / ARCHIVE).read_text(encoding="utf-8").splitlines()
    assert SLUG not in (tmp_path / LIVE).read_text(encoding="utf-8")

    staged = subprocess.run(["bash", "-c", _bound(_shipped_loop())], cwd=tmp_path, capture_output=True,
                            text=True, env={**_env(), "FINAL_JSON": ran.stdout})

    assert staged.returncode == 0, staged.stdout + staged.stderr
    staged_after = set(_git(tmp_path, "diff", "--cached", "--name-only").split())
    assert staged_after - staged_before == {ARCHIVE, LIVE}
