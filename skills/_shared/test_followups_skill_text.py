"""Skill text of the lean-default follow-ups (dev repo only).

design: lean-default-followups (task 1.6; Behaviors 1, 2, 4 and 6). Five docs carry the
change: the seed skill writes every seed text through a file, never through argv; the promote
and design skills stamp a line estimate for a just-do-it class; the weight-class protocol lists
that key; the fleet skill says its `lighten:` note reads the seed too. These checks read parsed
structures only, as `test_weight_class_lean_prose.py` does: the code spans of each doc (through
`skill_spans`), the commands in them (parsed with the writer's own argparse through
`argparse_probe`), and the references (through `skill_refs`). No assert reads a phrase out of
the prose.

Run with: pytest skills/_shared/test_followups_skill_text.py -q
"""
from __future__ import annotations

import ast
import re
from itertools import takewhile
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parent
REPO_ROOT = SHARED.parents[1]
SKILLS = REPO_ROOT / "skills"
SEED = SKILLS / "tp-seed" / "SKILL.md"
PROMOTE = SKILLS / "tp-promote" / "SKILL.md"
DESIGN = SKILLS / "tp-design" / "SKILL.md"
# split: the release leak guard bans a pro-exclusive skill name in a free-tier file
FLEET = SKILLS / ("tp-" + "fleet") / "SKILL.md"
PROTOCOL = SHARED / "weight-class.md"
FIVE_DOCS = (SEED, PROMOTE, DESIGN, PROTOCOL, FLEET)

SCRATCH = ".tp-scratch/seed/"
INLINE_TEXT_FLAGS = frozenset({"--problem", "--direction", "--open-questions", "--consumer"})
SECTION_FILE_FLAGS = frozenset({"--problem-file", "--direction-file", "--open-questions-file",
                                "--consumer-file"})
# subcommand -> how many positionals it takes (the slug); `similar` has none and no text slot
POSITIONALS = {"new": 1, "amend": 1, "similar": 0}

_STEP_LINE = re.compile(r"^\d+[a-z]?\. ")
_FENCE = re.compile(r"^\s*(```|~~~)")
_QUOTED_HEREDOC = re.compile(r"<<-?\s*'(\w+)'")
_WORD = re.compile(r"[\w./-]+")
_CONTROL = frozenset({"|", "||", "&&", ";", "&"})


@pytest.fixture(autouse=True)
def shared_on_path(monkeypatch):
    """Each test sets up its own import path, so it passes alone in a fresh process."""
    monkeypatch.syspath_prepend(str(SHARED))


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")


def _spans(path: Path, first: int = 0, last: int | None = None) -> list[tuple[int, str, bool]]:
    """`(line, span, shell)` for each code span of the file opening on a line in `[first, last)`."""
    skill_spans = pytest.importorskip("skill_spans")
    text = path.read_text(encoding="utf-8")
    return [(line, span, shell) for line, span, shell in skill_spans.code_spans(text)
            if line >= first and (last is None or line < last)]


def _step_range(path: Path, label: str) -> tuple[int, int]:
    """The lines of one top-level numbered step: from its `N. ` line to the next step's."""
    start, in_fence = None, False
    lines = _lines(path)
    for number, line in enumerate(lines, 1):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif in_fence:
            continue
        elif start is None:
            start = number if line.startswith(f"{label}. ") else None
        elif _STEP_LINE.match(line):
            return start, number
    assert start is not None, f"{path.name} has no step {label}"
    return start, len(lines) + 1


def _step_spans(path: Path, label: str) -> list[tuple[int, str, bool]]:
    return _spans(path, *_step_range(path, label))


def _section_range(path: Path, heading: str) -> tuple[int, int]:
    """The lines of one `## ` section: from its heading to the next `## ` heading."""
    lines = _lines(path)
    start = next(n for n, line in enumerate(lines, 1) if line.strip() == heading)
    end = next((n for n, line in enumerate(lines, 1) if n > start and line.startswith("## ")),
               len(lines) + 1)
    return start, end


def _words(span: str) -> set[str]:
    return set(_WORD.findall(span))


def _holds(spans: list[tuple[int, str, bool]], word: str) -> bool:
    """True when one code span carries `word` as a whole word (a key, a class, a file name)."""
    return any(word in _words(span) for _line, span, _shell in spans)


def _tokens(span: str, shell: bool) -> list[str]:
    return pytest.importorskip("skill_spans").tokens_of(span, shell)


def _seed_write_commands() -> list[list[str]]:
    """The args of each `python3 <path>/seed_write.py args...` command among the seed skill's
    code spans, cut at the first control operator."""
    found = []
    for _line, span, shell in _spans(SEED):
        try:
            tokens = _tokens(span, shell)
        except ValueError:  # a span that is not a shell command at all
            continue
        if len(tokens) > 2 and tokens[0] == "python3" and tokens[1].endswith("/seed_write.py"):
            found.append(list(takewhile(lambda tok: tok not in _CONTROL, tokens[2:])))
    return found


def _command(name: str) -> list[str]:
    return next(argv for argv in _seed_write_commands() if argv[0] == name)


def _filled(argv: list[str]) -> list[str]:
    """A placeholder (`<slug>`, `.tp-scratch/seed/<slug>/x.md`) becomes a plain value."""
    return [tok if tok.startswith("--") or i == 0 else "low" for i, tok in enumerate(argv)]


def _flag_pairs(argv: list[str]) -> list[tuple[str, str]]:
    """`(flag, value)` for each `--flag value` pair (every flag of the writer takes one value)."""
    return [(tok, argv[i + 1]) for i, tok in enumerate(argv[:-1]) if tok.startswith("--")]


def _positionals(argv: list[str]) -> list[str]:
    """The tokens after the subcommand that are neither a flag nor a flag's value."""
    found, skip = [], False
    for tok in argv[1:]:
        if skip:
            skip = False
        elif tok.startswith("--"):
            skip = "=" not in tok
        else:
            found.append(tok)
    return found


def _heredocs() -> list[tuple[int, str, str | None]]:
    """`(line, delimiter, target)` for each seed-skill shell span that opens a quoted heredoc;
    the target is the token after the span's `>` redirect."""
    found = []
    for line, span, shell in _spans(SEED):
        match = _QUOTED_HEREDOC.search(span) if shell else None
        if not match:
            continue
        tokens = _tokens(span, shell)
        target = next((tokens[i + 1] for i, tok in enumerate(tokens[:-1]) if tok == ">"), None)
        found.append((line, match.group(1), target))
    return found


def _calls_ensure_excluded(span: str, shell: bool) -> bool:
    """True when the span is `python3 -c "<program>"` and the program calls
    `scratch_root.ensure_excluded(...)`."""
    try:
        tokens = _tokens(span, shell)
        program = tokens[tokens.index("-c") + 1]
        tree = ast.parse(program)
    except (ValueError, IndexError, SyntaxError):
        return False
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "ensure_excluded"
               and ast.unparse(node.func.value) == "scratch_root"
               for node in ast.walk(tree))


# --- Behavior 1: seed text goes through files, never through argv --------------------------

def test_seed_skill_shows_the_three_writer_commands_and_each_parses_with_its_argparse(tmp_path):
    """`similar`, `amend` and `new` are the writer commands the seed skill shows, and each
    parses with `seed_write.py`'s own argparse."""
    argparse_probe = pytest.importorskip("argparse_probe")
    commands = _seed_write_commands()
    assert sorted(argv[0] for argv in commands) == ["amend", "new", "similar"]
    for argv in commands:
        result = argparse_probe.probe(SHARED / "seed_write.py", _filled(argv), cache_dir=tmp_path)
        assert result["status"] == "parsed", (argv, result)


@pytest.mark.parametrize("name", sorted(POSITIONALS))
def test_no_command_passes_seed_text_through_argv(name):
    """No command holds an inline text flag, or a positional text after the slug."""
    argv = _command(name)
    assert INLINE_TEXT_FLAGS.isdisjoint(flag for flag, _value in _flag_pairs(argv))
    assert len(_positionals(argv)) == POSITIONALS[name], argv


def test_new_passes_each_section_by_file_and_carries_the_estimate():
    flags = {flag for flag, _value in _flag_pairs(_command("new"))}
    assert SECTION_FILE_FLAGS <= flags
    assert "--estimated-lines" in flags


@pytest.mark.parametrize("name", ["amend", "similar"])
def test_amend_and_similar_pass_the_text_by_file(name):
    assert "--text-file" in {flag for flag, _value in _flag_pairs(_command(name))}


def test_every_text_file_a_command_reads_is_written_by_a_heredoc_under_the_scratch_dir():
    """Each `--*-file` value starts `.tp-scratch/seed/` and is the target of a quoted heredoc."""
    written = {target for _line, _word, target in _heredocs()}
    files = [value for argv in _seed_write_commands() for flag, value in _flag_pairs(argv)
             if flag.endswith("-file")]
    assert files, "no command passes a text file"
    for value in files:
        assert value.startswith(SCRATCH), value
        assert value in written, value


def test_a_quoted_heredoc_writes_text_under_the_scratch_dir():
    """Some shell span opens a quoted heredoc (any delimiter word) on a `.tp-scratch/seed/` file."""
    targets = [target for _line, _word, target in _heredocs()]
    assert any(target and target.startswith(SCRATCH) for target in targets), targets


def test_scratch_dir_is_excluded_before_the_first_heredoc():
    """A code span calls `scratch_root.ensure_excluded`, and the first such span comes before
    the first heredoc span."""
    calls = [line for line, span, shell in _spans(SEED) if _calls_ensure_excluded(span, shell)]
    heredocs = [line for line, _word, _target in _heredocs()]
    assert calls and heredocs
    assert min(calls) < min(heredocs)


# --- Behaviors 2 and 4: the estimate is stamped for a just-do-it class ---------------------

def test_promote_step_7_stamps_the_estimate_for_a_just_do_it_class():
    spans = _step_spans(PROMOTE, "7")
    assert _holds(spans, "estimated-lines")
    assert _holds(spans, "just-do-it")


def test_design_step_7_stamps_the_estimate():
    assert _holds(_step_spans(DESIGN, "7"), "estimated-lines")


def test_protocol_frontmatter_schema_lists_the_estimate_key():
    assert _holds(_spans(PROTOCOL, *_section_range(PROTOCOL, "## Frontmatter schema")),
                  "estimated-lines")


# --- Behavior 6: the fleet note reads the seed of a design-ready design --------------------

def test_fleet_lighten_paragraph_names_the_seed_file():
    """The blank-line bounded paragraph holding the `scripts/fleet_lighten.py` span also holds
    a `seed.md` span."""
    anchor = next(line for line, span, _shell in _spans(FLEET)
                  if "scripts/fleet_lighten.py" in _words(span))
    lines = _lines(FLEET)
    first, last = anchor, anchor
    while first > 1 and lines[first - 2].strip():
        first -= 1
    while last < len(lines) and lines[last].strip():
        last += 1
    assert _holds(_spans(FLEET, first, last + 1), "seed.md")


# --- every reference the five docs show resolves -------------------------------------------

def test_references_in_the_five_docs_resolve(tmp_path):
    """Every path, `/tp-*` skill and `python3` invocation the five files name resolves and
    parses (invariant 46's check, run in-suite)."""
    skill_refs = pytest.importorskip("skill_refs")
    assert skill_refs.check(REPO_ROOT, list(FIVE_DOCS), cache_dir=tmp_path).issues == []
