"""certify.py path arguments are files, never directories (run-tooling-footguns, Task 1.4).

Trap 4: the protocol text said `--claims <scratch>`, a directory, but `lint`, `brief` and
`run` take a claims FILE, `fold --out` takes a file and `run`'s records are a JSON list. Three
pins, none of which parses prose it did not write itself (skills/_shared/test-fragility.md):

1. no shared doc snippet hands a directory to a certify path argument. A directory is a
   placeholder the same document uses as `<dir>/something`, or a value ending in `/`, so
   there is no hand-kept list of directory names;
2. the protocol says the file shapes;
3. every subcommand's `--help` states the shape, read from the real parser's output.

The CLI's accepted arguments do not change (a directory is still bad input, exit 2).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

import certify_cli

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "skills" / "_shared" / "certification-protocol.md"
# Docs that carry a certify snippet today; each must be seen by the scanner (not vacuous).
SNIPPET_DOCS = (
    "skills/_shared/certification-protocol.md",
    "skills/tp-run-full-design/tier-5-closeout.md",
    "skills/tp-design-audit/SKILL.md",
    "skills/tp-implementation-audit/SKILL.md",
    "skills/tp-phase-review/SKILL.md",
)
# Every path-valued flag the CLI declares a FILE (the trap names `--claims`, `--out`): the real
# registry, so a new file flag is covered without editing this guard.
PATH_FLAGS = tuple(dict.fromkeys(certify_cli.FILE_FLAGS))


def subcommands() -> dict:
    """name -> subparser, from the real parser (the registry, not a hand-copied list)."""
    parser = certify_cli.build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


SUBS = subcommands()


def invocations(text: str):
    """(subcommand, argument span) for each `"$CERT" <sub>` / `certify.py <sub>` in `text`.

    A span ends at the next backtick (an inline snippet or a code fence), a blank line or
    the next resolved-script call."""
    names = "|".join(re.escape(name) for name in sorted(SUBS, key=len, reverse=True))
    call = re.compile(rf'(?:"\$CERT"|certify\.py)\s+({names})(?![\w-])')
    for match in call.finditer(text):
        rest = text[match.end():]
        stop = re.search(r'`|\n\s*\n|"\$CERT"|"\$CL"', rest)
        yield match.group(1), rest[: stop.start() if stop else len(rest)]


def path_values(text: str):
    """(subcommand, flag, value) for every path flag written in a certify snippet."""
    flags = "|".join(re.escape(flag) for flag in sorted(PATH_FLAGS, key=len, reverse=True))
    for name, span in invocations(text):
        for match in re.finditer(rf"(?<!\S)({flags})\s+(\S+)", span):
            yield name, match.group(1), match.group(2).rstrip("`',.);")


def directory_values(text: str) -> list[str]:
    """Snippet arguments whose value is a directory by the document's own usage."""
    dirs = set(re.findall(r"([<{][^<>{}\s/]+[>}])/", text))
    return [f"{name} {flag} {value}" for name, flag, value in path_values(text)
            if value.endswith("/") or value in dirs]


def doc_files() -> list[Path]:
    return sorted([*ROOT.glob("skills/**/*.md"), *ROOT.glob("agents/*.md")])


def flat(text: str) -> str:
    return " ".join(text.split())


def test_scanner_flags_a_directory_value_and_passes_a_file():
    text = (
        "scratch holds <scratch>/diff.txt and <scratch>/kept.json\n\n"
        '`python3 "$CERT" lint --claims <scratch> --ref S --kept-out <scratch>/kept.json`\n'
        '`python3 "$CERT" run --claims <claims.json> --records <scratch>/r1.records.json\n'
        "   --repo . --out <scratch>/r1.result.json`\n"
        '`python3 "$CERT" fold --envelope E --out <scratch> --slot 8`\n'
        '`python3 "$CERT" run --claims out/ --records R`\n'
        '`python3 "$CERT" lint --claims <claims.json> --ref S --kept-out <scratch>`\n'
    )
    assert directory_values(text) == ["lint --claims <scratch>", "fold --out <scratch>",
                                      "run --claims out/", "lint --kept-out <scratch>"]
    assert [v for _n, f, v in path_values(text) if f == "--records"] == [
        "<scratch>/r1.records.json", "R"]


def test_no_shared_doc_snippet_shows_a_directory_for_a_path_argument():
    seen: dict[str, int] = {}
    bad = []
    for path in doc_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        seen[rel] = sum(1 for _n, flag, _v in path_values(text) if flag == "--claims")
        bad += [f"{rel}: {item}" for item in directory_values(text)]
    assert not bad, "a certify path argument is a file, never a directory:\n" + "\n".join(bad)
    assert all(seen.get(rel) for rel in SNIPPET_DOCS), seen  # the scan really reached them


def test_protocol_states_the_file_shapes():
    text = flat(PROTOCOL.read_text(encoding="utf-8"))
    assert "--claims <file>" in text
    assert "--out <file>" in text
    assert re.search(r"--records <file>[^.]*JSON list", text), "records are a JSON list file"


def test_a_directory_is_still_bad_input(tmp_path, capsys):
    """The CLI does not change: the docs were wrong, not the argument handling."""
    assert certify_cli.main(["validate", "--claims", str(tmp_path), "--ref", "HEAD"]) == 2
    assert "bad input" in capsys.readouterr().err


def help_text(name: str, capsys) -> str:
    with pytest.raises(SystemExit) as exc:
        certify_cli.main([name, "--help"])
    assert exc.value.code == 0
    return flat(capsys.readouterr().out)


def own_flags(name: str) -> set[str]:
    return {opt for act in SUBS[name]._actions for opt in act.option_strings}


@pytest.mark.parametrize("name", sorted(SUBS))
def test_help_states_the_shape_each_subcommand_takes(name, capsys):
    text = help_text(name, capsys)
    flags = own_flags(name)
    files = sorted(flags & set(PATH_FLAGS))
    for flag in files:
        assert re.search(rf"{re.escape(flag)} FILE\b", text), f"{name} --help: {flag} is a FILE"
    if files:
        assert "not a directory" in text, f"{name} --help says path arguments are files"
    if flags & {"--records", "--records-out"}:
        assert "JSON list" in text, f"{name} --help says the records are a JSON list"
    # Split so no 10+ char literal here is pinned by the rule ledgers' extract_pins.
    for flag in sorted(flags & {"--design", "--design" + "-dir"}):
        assert re.search(rf"{re.escape(flag)} DIR\b", text), f"{name} --help: {flag} is a DIR"
