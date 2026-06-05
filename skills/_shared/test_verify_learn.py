"""Tests for verify_learn.py — learn-verification (diff-derived deleted-symbol grep).

Advisory: every entry point always exits 0 / never raises (fail-open). Pure-logic
units + one temp-repo git integration for the --range CLI path.

Run with: python -m pytest skills/_shared/test_verify_learn.py -q

Design refs:
  - three-pillars-docs/tp-designs/merged-design-closeout/detailed-design.md
  - three-pillars-docs/tp-designs/merged-design-closeout/plan.md
"""

from pathlib import Path

import pytest

import io
import json
import subprocess

import verify_learn
from verify_learn import retired_identifiers, scan_docs, StaleRef, main


# --------------------------------------------------------------------------- #
# Task 3.1 — retired_identifiers(diff_text): removed symbols + deleted-file names
# --------------------------------------------------------------------------- #


def test_deleted_def_extracted():
    diff = (
        "--- a/skills/_shared/foo.py\n"
        "+++ b/skills/_shared/foo.py\n"
        "@@ -1,3 +1,1 @@\n"
        "-def foo_bar():\n"
        "-    return 1\n"
        " keep = 2\n"
    )
    assert "foo_bar" in retired_identifiers(diff)


def test_renamed_old_name():
    # A symbol rename: the removed (-) old name is retired; the added (+) new name is not.
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def old_name(x):\n"
        "+def new_name(x):\n"
        "     return x\n"
    )
    ids = retired_identifiers(diff)
    assert "old_name" in ids
    assert "new_name" not in ids


def test_deleted_file_basename():
    diff = (
        "diff --git a/skills/_shared/old_helper.py b/skills/_shared/old_helper.py\n"
        "deleted file mode 100644\n"
        "--- a/skills/_shared/old_helper.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-def gone():\n"
        "-    pass\n"
    )
    ids = retired_identifiers(diff)
    assert "old_helper.py" in ids   # deleted-file basename
    assert "gone" in ids            # ...and its removed symbol


def test_class_and_shell_and_const_forms():
    # Concrete identifier forms (audit fix — drops vague "const-helper").
    diff = (
        "--- a/x\n"
        "+++ b/x\n"
        "@@ -1,4 +1,1 @@\n"
        "-class OldThing:\n"
        "-build_thing() {\n"
        "-MAX_RETRIES = 3\n"
        " keep\n"
    )
    ids = retired_identifiers(diff)
    assert {"OldThing", "build_thing", "MAX_RETRIES"} <= ids


def test_zero_deletion_empty():
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,1 +1,3 @@\n"
        " keep = 1\n"
        "+def added():\n"
        "+    pass\n"
    )
    assert retired_identifiers(diff) == set()


def test_added_def_not_extracted():
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def added_fn():\n"
        "+    pass\n"
    )
    assert "added_fn" not in retired_identifiers(diff)


def test_malformed_diff_empty():
    assert retired_identifiers("this is not a diff at all\nrandom text") == set()
    assert retired_identifiers("") == set()
    assert retired_identifiers(None) == set()  # fail-open, no raise


# --------------------------------------------------------------------------- #
# Task 3.2 — scan_docs(repo_root, identifiers): living + archived doc mentions
# --------------------------------------------------------------------------- #


def _doc(root: Path, relpath: str, text: str) -> None:
    p = root / "three-pillars-docs" / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_doc_mention_flagged(tmp_path):
    _doc(tmp_path, "architecture.md", "Intro line\nThe old_helper drives X\nmore\n")
    refs = scan_docs(tmp_path, {"old_helper"})
    assert len(refs) == 1
    r = refs[0]
    assert isinstance(r, StaleRef)
    assert r.identifier == "old_helper"
    assert r.line == 2
    assert r.doc.endswith("architecture.md")


def test_no_mention_empty(tmp_path):
    _doc(tmp_path, "architecture.md", "nothing retired here\n")
    assert scan_docs(tmp_path, {"old_helper"}) == []
    # empty identifier set short-circuits to empty too
    assert scan_docs(tmp_path, set()) == []


def test_scans_completed_dir(tmp_path):
    # Archived docs count: a retired symbol lingering under completed-tp-designs/
    # is still drift the learn pass should have scrubbed.
    _doc(tmp_path, "completed-tp-designs/foo/design.md", "uses RETIRED_CONST still\n")
    refs = scan_docs(tmp_path, {"RETIRED_CONST"})
    assert len(refs) == 1
    assert "completed-tp-designs/foo/design.md" in refs[0].doc


def test_word_boundary_not_substring(tmp_path):
    # "foo" must not match inside "foobar" (whole-word, reduces false positives).
    _doc(tmp_path, "architecture.md", "the foobar thing is fine\n")
    assert scan_docs(tmp_path, {"foo"}) == []


# --------------------------------------------------------------------------- #
# Task 3.3 — main(argv): --range (git diff) / stdin, --json, always exit 0
# --------------------------------------------------------------------------- #


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_cli_range_flags_stale(tmp_path, capsys):
    # Build a temp repo where a later commit RETIRES a const that a doc still names.
    _git(["init", "-q", "-b", "master"], tmp_path)
    _git(["config", "user.email", "t@e.com"], tmp_path)
    _git(["config", "user.name", "T"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "skills" / "_shared").mkdir(parents=True)
    (tmp_path / "skills" / "_shared" / "thing.py").write_text("OLD_CONST = 1\ndef keep():\n    return OLD_CONST\n")
    _doc(tmp_path, "architecture.md", "We rely on OLD_CONST for X.\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "seed"], tmp_path)
    # retire OLD_CONST in code (doc still mentions it → drift)
    (tmp_path / "skills" / "_shared" / "thing.py").write_text("def keep():\n    return 1\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "retire OLD_CONST"], tmp_path)

    rc = main(["--repo", str(tmp_path), "--range", "HEAD~1...HEAD", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(r["identifier"] == "OLD_CONST" and r["doc"].endswith("architecture.md") for r in payload)


def test_cli_stdin(tmp_path, capsys, monkeypatch):
    _doc(tmp_path, "architecture.md", "the gone function is described here\n")
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,1 @@\n-def gone():\n-    pass\n keep = 1\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(diff))
    rc = main(["--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(r["identifier"] == "gone" for r in payload)


def test_cli_always_exit_zero(tmp_path, capsys, monkeypatch):
    # Advisory: a bogus --range (git errors) must still exit 0, never raise.
    rc = main(["--repo", str(tmp_path), "--range", "no-such-ref...also-bad", "--json"])
    assert rc == 0
    # And empty stdin → exit 0.
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["--repo", str(tmp_path)]) == 0
