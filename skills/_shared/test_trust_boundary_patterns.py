"""test_trust_boundary_patterns.py — the trust-boundary pattern table (design: review-convergence).

Task 3.1 covers `SH/trust_boundary.py`'s table shape and `surfaces(diff_text)`: one positive and
one negative unified diff per row of the security companion's pattern table, plus one removal-only
positive per surface. Entry points here only — `surfaces_for_range`, `brief_path`, `CHECKLIST` and
the CLI land in later tasks.
"""
from __future__ import annotations

import re

import pytest

from trust_boundary import PATTERNS, SECURITY_BAR, SURFACES, Pattern, surfaces


def diff(path, hunk_start, *lines):
    """A minimal unified diff for one file: `lines` carry their own +/- prefix."""
    old_count = sum(1 for ln in lines if ln.startswith("-"))
    new_count = sum(1 for ln in lines if ln.startswith("+"))
    body = "\n".join(
        ln if ln[:1] in "+-@ " else " " + ln for ln in lines
    )
    return (
        "--- a/%s\n" % path
        + "+++ b/%s\n" % path
        + "@@ -%d,%d +%d,%d @@\n" % (hunk_start, old_count, hunk_start, new_count)
        + body
        + "\n"
    )


def entry(surface, path, line, text, removed):
    return {"surface": surface, "path": path, "line": line, "text": text, "removed": removed}


# ------------------------------------------------------------------ table shape

def test_pattern_namedtuple_fields():
    assert Pattern._fields == ("name", "path_glob", "line_re")


def test_surface_names_and_order():
    assert SURFACES == (
        "argv-subprocess",
        "file-write-path",
        "credentials",
        "git-gh",
        "untrusted-parse",
        "agent-tool-grant",
    )


def test_patterns_is_a_tuple_of_valid_patterns():
    assert isinstance(PATTERNS, tuple) and PATTERNS
    for pat in PATTERNS:
        assert isinstance(pat, Pattern)
        assert pat.name in SURFACES
        assert isinstance(pat.path_glob, tuple)
        assert pat.line_re is None or isinstance(pat.line_re, re.Pattern)


def test_table_has_a_row_for_every_surface():
    assert {p.name for p in PATTERNS} == set(SURFACES)


# ---------------------------------------------------- one positive + negative per table row

POSITIVE = [
    # row 1: argv-subprocess, *.py
    (
        "argv-subprocess",
        "scripts/runner.py",
        "import subprocess\n",
        ["+    subprocess.run(cmd, check=True)"],
    ),
    # row 2: argv-subprocess, *.sh
    (
        "argv-subprocess",
        "hooks/pre-commit.sh",
        "#!/bin/sh\n",
        ['+bash -c "echo $TASK"'],
    ),
    # row 3: file-write-path, any code
    (
        "file-write-path",
        "pkg/notes.py",
        "def save(p, text):\n",
        ['+    return open(p, "w").write(text)'],
    ),
    # row 4: credentials, any
    (
        "credentials",
        "notes.txt",
        "intro\n",
        ["+GH_TOKEN is read from the keyring"],
    ),
    # row 5: git-gh, any
    (
        "git-gh",
        "scripts/push.sh",
        "set -e\n",
        ["+git push origin HEAD"],
    ),
    # row 6: git-gh, hooks/** (any changed line)
    (
        "git-gh",
        ".pre-commit-config.yaml",
        "repos: []\n",
        ["+- id: scratch"],
    ),
    # row 7: untrusted-parse, *.py
    (
        "untrusted-parse",
        "pkg/parse.py",
        "import json\n",
        ["+    payload = json.loads(raw)"],
    ),
    # row 8: agent-tool-grant, agents/*.md
    (
        "agent-tool-grant",
        "agents/tp-task-worker.md",
        "name: tp-task-worker\n",
        ["+tools: Read, Bash"],
    ),
]

NEGATIVE = [
    # row 1: *.py, no subprocess/token in the line
    ("scripts/runner.py", "def total(xs):\n", ["+    return sum(xs)"]),
    # row 2: *.sh, a comment — no command position
    ("hooks/pre-commit.sh", "#!/bin/sh\n", ["+# nothing to do here"]),
    # row 3: any code, a read
    ("pkg/notes.py", "def load(p):\n", ['+    return open(p).read()']),
    # row 4: prose with no credential word
    ("notes.txt", "intro\n", ["+a sentence about nothing"]),
    # row 5: a script that touches no git/gh command
    ("scripts/push.sh", "set -e\n", ["+echo done"]),
    # row 6: hooks/** with no changed line at all (context only)
    (".pre-commit-config.yaml", "repos: []\n", [" unchanged"]),
    # row 7: *.py with no parse call
    ("pkg/parse.py", "import json\n", ["+    return raw.strip()"]),
    # row 8: agents/*.md with no grant key
    ("agents/tp-task-worker.md", "---\n", ["+Read the brief carefully."]),
]


@pytest.mark.parametrize("surface,path,context,added", POSITIVE, ids=range(len(POSITIVE)))
def test_positive_per_table_row(surface, path, context, added):
    got = surfaces(diff(path, 2, context.rstrip("\n"), *added))
    assert got, "row must be matched by some pattern"
    assert surface in [e["surface"] for e in got]
    for e in got:
        assert e["path"] == path
        assert e["line"] == 3  # the added line, per the @@ +2,1 header
        assert e["removed"] is False


@pytest.mark.parametrize("path,context,added", NEGATIVE, ids=range(len(NEGATIVE)))
def test_negative_per_table_row(path, context, added):
    assert surfaces(diff(path, 2, context.rstrip("\n"), *added)) == []


# ------------------------------------------------- one removal-only positive per surface

REMOVALS = {
    "argv-subprocess": ("pkg/run.py", ["-    subprocess.run(cmd, check=True)"]),
    "file-write-path": ("pkg/notes.py", ['-    open(p, "w").write(text)']),
    "credentials": ("pkg/auth.py", ['-    token = os.environ["GH_TOKEN"]']),
    "git-gh": ("hooks/pre-commit.sh", ["-git push origin HEAD"]),
    "untrusted-parse": ("pkg/parse.py", ["-    payload = json.loads(raw)"]),
    "agent-tool-grant": ("agents/tp-task-worker.md", ["-allowed-tools: Read, Bash"]),
}


@pytest.mark.parametrize("surface", SURFACES)
def test_removal_only_per_surface(surface):
    path, removed = REMOVALS[surface]
    got = surfaces(diff(path, 7, *removed))
    assert entry(surface, path, 7, removed[0][1:].strip(), True) in got


def test_removed_flag_is_false_for_added_lines():
    got = surfaces(diff("pkg/run.py", 1, "+    subprocess.run(cmd, check=True)"))
    assert [e["removed"] for e in got] == [False]


# ------------------------------------------------------------- entry bookkeeping

def test_results_are_in_diff_order():
    text = (
        "--- a/pkg/a.py\n"
        "+++ b/pkg/a.py\n"
        "@@ -1,0 +1,2 @@\n"
        "+x = shlex.split(raw)\n"
        "+    subprocess.run(cmd, check=True)\n"
        "@@ -20,0 +22 @@\n"
        '+    open(p, "w").write(text)\n'
    )
    got = surfaces(text)
    assert [(e["path"], e["line"]) for e in got] == [
        ("pkg/a.py", 1),
        ("pkg/a.py", 2),
        ("pkg/a.py", 22),
    ]


def test_de_dupe_one_line_matching_two_patterns_of_one_surface():
    text = (
        "--- a/pkg/a.py\n"
        "+++ b/pkg/a.py\n"
        "@@ -1,0 +1 @@\n"
        "+    subprocess.run(cmd, shell=True)\n"
    )
    got = surfaces(text)
    assert [e["surface"] for e in got] == ["argv-subprocess"]
    assert got[0]["text"] == "subprocess.run(cmd, shell=True)"


def test_path_is_the_b_path_or_a_when_b_is_dev_null():
    added = surfaces(diff("pkg/a.py", 4, "+    subprocess.run(cmd, check=True)"))
    assert added[0]["path"] == "pkg/a.py"
    removed_all = (
        "--- a/pkg/a.py\n"
        "+++ /dev/null\n"
        "@@ -9,1 +0,0 @@\n"
        "-    subprocess.run(cmd, check=True)\n"
    )
    got = surfaces(removed_all)
    assert [e["path"] for e in got] == ["pkg/a.py"]
    assert got[0]["line"] == 9
    assert got[0]["removed"] is True


def test_text_is_stripped_and_cut_to_160_chars():
    long_line = "+x = subprocess.run(" + "a" * 300 + ")"
    got = surfaces(diff("pkg/a.py", 1, long_line))
    assert len(got) == 1
    assert len(got[0]["text"]) == 160
    assert got[0]["text"] == ("x = subprocess.run(" + "a" * 300)[:160]


def test_header_lines_are_ignored():
    assert surfaces("--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1,0 +1 @@\n") == []


# ----------------------------------------------------------------- SECURITY_BAR

def test_security_bar_text():
    assert SECURITY_BAR == (
        "A security finding blocks only with a demonstrated exploit path: the "
        "attacker-controlled input, the trust boundary it crosses and the effect, with "
        "a reproducer. Hardening ideas without one are notes (blocking=false). Prefer "
        "allowlist or build-the-input fixes; a blocklist patch is not a fix."
    )
