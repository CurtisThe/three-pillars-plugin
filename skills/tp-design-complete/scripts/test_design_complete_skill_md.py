"""Structured contract checks for `skills/tp-design-complete/SKILL.md` (dev repo only).

design: fragile-test-prevention (Part D reference integrity + frontmatter schema, phase 18).
These replace the substring and regex pins on the SKILL.md with checks on parsed structures:
the frontmatter through `skill_frontmatter`, the references through `skill_refs`, the command
spans through `skill_spans` (the parser `skill_refs` reads references with), the script CLIs
through `argparse_probe`, and the registries the code uses (`resolve_script`,
`review_readiness`). No assert here reads a heading, a section or a phrase out of the prose.

The archive-and-stamp behaviour (completion stamp, `cleanup-pending` lock phase, the bannered
handoff) is the artifact the skill makes; it is graded by the eval scenario
`evals/skills/tp-design-complete/design-complete-skill-md.json`, and the staged-blob guard it
rides on (`verify_archive_staged.py`) has its own tests.

Run with: pytest skills/tp-design-complete/scripts/test_design_complete_skill_md.py -q
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
SKILL_MD = SCRIPTS.parent / "SKILL.md"
REPO_ROOT = SCRIPTS.parents[2]
for _dir in (REPO_ROOT / "skills" / "_shared", SCRIPTS):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

_VARIABLE = re.compile(r"\$\w+")


def _frontmatter() -> dict:
    """`{key: value}` of the SKILL.md frontmatter, through the shipped parser."""
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    fields, issues = skill_frontmatter.parse(SKILL_MD.read_text(encoding="utf-8"))
    assert fields is not None and issues == [], f"unparseable frontmatter {issues}"
    return {key: value for key, (_line, value) in fields.items()}


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
    """Every command the SKILL.md shows (an inline code span or a fenced line), in document
    order, read through `skill_spans`."""
    skill_spans = pytest.importorskip("skill_spans")
    found = []
    for _line, span, shell in skill_spans.code_spans(SKILL_MD.read_text(encoding="utf-8")):
        try:
            found.append(_words(skill_spans.tokens_of(span, shell)))
        except ValueError:  # a span that is not a shell command at all
            continue
    return found


def _python_calls() -> list[tuple[int, str, list[str]]]:
    """`(position, script, args)` of every `python3 <script> args...` command, in document order."""
    return [(pos, words[i + 1], words[i + 2:])
            for pos, words in enumerate(_commands())
            for i in range(len(words) - 1) if words[i] == "python3"]


def _calls_of(script: str) -> list[tuple[int, list[str]]]:
    return [(pos, args) for pos, path, args in _python_calls() if path.endswith("/" + script)]


def _review_requests() -> list[tuple[int, list[str]]]:
    """`(position, words)` of every `gh api ... -f reviewers[]=<login>` command."""
    return [(pos, words) for pos, words in enumerate(_commands())
            if words[:2] == ["gh", "api"] and any(w.startswith("reviewers[]=") for w in words)]


def _flags(args: list[str]) -> set[str]:
    return {token.split("=", 1)[0] for token in args if token.startswith("--")}


def _declared_flags() -> set[str]:
    return set(re.findall(r"--[a-z][a-z-]*", _frontmatter()["argument-hint"]))


def test_skill_frontmatter_passes_schema():
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    assert skill_frontmatter.check(SKILL_MD) == []


def test_skill_references_resolve(tmp_path):
    """Every path, `/tp-*` skill and `python3` invocation the SKILL.md names exists and parses
    with its script's own argparse (invariant 46's check, run in-suite). This covers the shared
    auto-mode convention, the weight-class doc and `weight_class.py`, and `reconcile_docs.py
    --archive-cites`."""
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(REPO_ROOT, [SKILL_MD], cache_dir=tmp_path)
    assert report.issues == []


def test_mode_flags_are_declared_in_argument_hint():
    """`--skip-learn` (the learn-ran escape), `--no-review` (the review-request opt-out) and
    `--auto` (the unattended archival half) are the skill's interface: the frontmatter declares them."""
    assert {"--skip-learn", "--no-review", "--auto"} <= _declared_flags()


def test_python_invocations_are_root_anchored_or_resolved():
    """Every `python3 <script>` the SKILL.md shows is anchored at `$TP_ROOT` (never an install
    path such as `~/.claude/skills/`, which a plugin install never creates) and the script
    exists there, or it is a variable the resolver step set (an inline `-c` snippet names no script)."""
    calls = _python_calls()
    assert calls
    for _pos, script, _args in calls:
        if script.startswith("-") or _VARIABLE.fullmatch(script):
            continue
        assert script.startswith("$TP_ROOT/"), script
        assert (REPO_ROOT / script.removeprefix("$TP_ROOT/")).is_file(), script


def test_archive_cite_rewrite_requests_the_json_file_list(tmp_path):
    """Step 6f stages exactly the files `reconcile_docs.py --archive-cites` rewrote, so the call
    must ask for its machine-readable list (`--json`) and name the design (`--slug`), and its
    flags must parse with the script's own argparse (the call is a `VAR="$(...)"` capture, a
    span `skill_refs` does not probe)."""
    argparse_probe = pytest.importorskip("argparse_probe")
    # 6g's `--pre-merge` writeback is pinned by test_design_complete_final_doc_state.py.
    calls = [c for c in _calls_of("reconcile_docs.py") if "--pre-merge" not in c[1]]
    assert calls, "step 6f must run reconcile_docs.py"
    for _pos, args in calls:
        assert {"--archive-cites", "--slug", "--json"} <= _flags(args), args
        probe = argparse_probe.probe(REPO_ROOT / "skills" / "_shared" / "reconcile_docs.py", args,
                                     cache_dir=tmp_path)
        assert probe["status"] == "parsed", probe["message"]


def test_archive_is_verified_by_the_staged_blob_guard():
    """The completion stamp and the `cleanup-pending` lock phase must be in the archival commit's
    staged blobs: the skill runs `verify_archive_staged.py`, the shipped validator for exactly
    that (`skill_refs` checks that its `--repo` and `--slug` are the script's own)."""
    calls = _calls_of("verify_archive_staged.py")
    assert calls, "step 6f must run verify_archive_staged.py"
    for _pos, args in calls:
        assert {"--repo", "--slug"} <= _flags(args), args


def test_archive_steps_run_before_the_pr_opens_and_review_follows():
    """The cite rewrite and the staged-blob guard precede the PR open (so the marker and the
    rewritten cites ride the PR), and the Copilot review request follows it (it needs the PR)."""
    rewrite = _calls_of("reconcile_docs.py")
    guard = _calls_of("verify_archive_staged.py")
    opened = [(pos, args) for pos, path, args in _python_calls()
              if _VARIABLE.fullmatch(path) and args[:1] == ["pr-create"]]
    requested = _review_requests()
    assert rewrite and guard and opened and requested
    assert rewrite[0][0] < guard[0][0] < opened[0][0] < requested[0][0]


def test_pr_open_goes_through_the_resolved_author_chokepoint(tmp_path):
    """The PR is opened by `forge.py pr-create --context manual` (the forge chokepoint; on GitHub it
    hands the args to `github_pr_author.py`), reached through the resolver step: the name the
    resolver is given resolves to a real script, and the pr-create call's own flags parse with the
    forge CLI's argparse (`forge.py` delegates to `forge_cli.py`), `--context` taking a value its
    subparser declares. The compare-URL fallback goes through `forge.py compare-url`."""
    resolve_script = pytest.importorskip("resolve_script")
    argparse_probe = pytest.importorskip("argparse_probe")
    forge_cli = pytest.importorskip("forge_cli")
    variable_calls = [(path, args) for _pos, path, args in _python_calls() if _VARIABLE.fullmatch(path)]
    named = [args[0] for _path, args in variable_calls if args[:1] and args[0].endswith(".py")]
    created = [args for _path, args in variable_calls if args[:1] == ["pr-create"]]
    assert named and created, "the SKILL.md must resolve the chokepoint and call its pr-create"
    chokepoint = resolve_script.resolve_shared_script(named[0], cwd=REPO_ROOT, self_root=REPO_ROOT)
    assert chokepoint.is_file()
    cli = chokepoint.with_name("forge_cli.py")
    sub = next(a for a in forge_cli._parser()._actions if isinstance(a, argparse._SubParsersAction))
    for args in created:
        own = args[:args.index("--")] if "--" in args else args
        probe = argparse_probe.probe(cli, own, cache_dir=tmp_path)
        assert probe["status"] == "parsed", probe["message"]
        ctx = next(a for a in sub.choices[own[0]]._actions if "--context" in a.option_strings)
        assert own[own.index("--context") + 1] in ctx.choices
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "compare-url" in text, "the fallback must print the forge's own URL via `forge.py compare-url`"
    assert "https://github.com/{owner}" not in text, "no hard-coded github.com compare URL literal"


def test_review_request_names_a_known_copilot_reviewer():
    """The completion PR's review request goes through `gh api ... -f reviewers[]=<login>`, and the
    login is one the review-readiness registry knows as the Copilot reviewer."""
    review_readiness = pytest.importorskip("review_readiness")
    requests = _review_requests()
    assert requests, "step 6g must request the Copilot review through `gh api`"
    for _pos, words in requests:
        logins = {w.split("=", 1)[1] for w in words if w.startswith("reviewers[]=")}
        assert logins <= review_readiness._REST_COPILOT_LOGINS, logins
