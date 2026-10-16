"""Tests for the review-prep text oracles in cheap_oracle.py.

design: cheap-tier-review-prep (Phase 2). Task 2.1: hunk_bytes and _diff_hunks.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_oracle as co  # noqa: E402

APP_H1 = ("@@ -1,3 +1,3 @@\n import os\n-x = 1\n+x = 2\n y = 3\n")
APP_H2 = ("@@ -10,2 +10,3 @@ def f():\n a = 1\n+b = 2\n c = 3\n")
GONE_H = "@@ -1,2 +0,0 @@\n-gone\n-away\n"
APP_BLOCK = ("diff --git a/src/app.py b/src/app.py\nindex 1111111..2222222 100644\n"
             "--- a/src/app.py\n+++ b/src/app.py\n" + APP_H1 + APP_H2)
GONE_BLOCK = ("diff --git a/old.txt b/old.txt\ndeleted file mode 100644\n"
              "index 3333333..0000000\n--- a/old.txt\n+++ /dev/null\n" + GONE_H)
DIFF = APP_BLOCK + GONE_BLOCK
PAIRS = [("src/app.py", APP_H1), ("src/app.py", APP_H2), ("old.txt", GONE_H)]

BINARY_BLOCK = ("diff --git a/logo.png b/logo.png\nindex 4444444..5555555 100644\n"
                "Binary files a/logo.png and b/logo.png differ\n")
RENAME_BLOCK = ("diff --git a/before.py b/after.py\nsimilarity index 100%\n"
                "rename from before.py\nrename to after.py\n")
MODE_BLOCK = "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n"
NEW_FILE_BLOCK = ("diff --git a/new.txt b/new.txt\nnew file mode 100644\n"
                  "index 0000000..6666666\n--- /dev/null\n+++ b/new.txt\n"
                  "@@ -0,0 +1 @@\n+hello\n")


def _slice(pairs):
    return {"hunks": [{"file": f, "hunk": h} for f, h in pairs]}


def _run(tmp_path, text, pairs):
    p = tmp_path / "diff.txt"
    p.write_bytes(text.encode("utf-8"))
    return co.check("review_slice", _slice(pairs), {"diff_path": str(p)})


def test_diff_hunks_parses_per_block_and_names_deletions_by_old_path():
    assert co._diff_hunks(DIFF) == set(PAIRS)


def test_exact_one_hunk_slice_and_the_full_set_pass(tmp_path):
    for pairs in ([PAIRS[1]], [PAIRS[2]], PAIRS):
        v = _run(tmp_path, DIFF, pairs)
        assert v["ok"] is True, v
        assert v["oracle"] == "hunk_bytes"
        assert co.settle("review_slice", v) == "accept"


@pytest.mark.parametrize("pairs, index", [
    ([PAIRS[0], ("src/app.py", APP_H2.replace("b = 2", "b = 3"))], 1),
    ([("src/app.py", APP_H1.rstrip("\n"))], 0),          # not newline-terminated
    ([("src/app.py", " " + APP_H1)], 0),                  # no strip: a leading space
    ([PAIRS[2], ("nope.py", APP_H1)], 1),                 # an unknown file
    ([("old.txt", APP_H1)], 0),                           # real hunk, wrong file
    ([PAIRS[0], PAIRS[1], PAIRS[0]], 2),                  # duplicate (file, hunk)
])
def test_bad_slice_fails_and_names_its_index(tmp_path, pairs, index):
    v = _run(tmp_path, DIFF, pairs)
    assert v["ok"] is False
    assert f"hunk {index}" in v["reason"], v["reason"]
    assert co.settle("review_slice", v) == "drop"


def test_empty_list_fails(tmp_path):
    v = _run(tmp_path, DIFF, [])
    assert v["ok"] is False and "empty" in v["reason"]
    assert co.settle("review_slice", v) == "drop"


def test_more_hunks_than_parsed_fails_at_the_first_excess_index(tmp_path):
    v = _run(tmp_path, GONE_BLOCK, [PAIRS[2], PAIRS[2]])
    assert v["ok"] is False and "hunk 1" in v["reason"], v
    v = _run(tmp_path, "", [PAIRS[2]])  # a diff that parsed to nothing
    assert v["ok"] is False and "hunk 0" in v["reason"], v


@pytest.mark.parametrize("artifact", [
    {}, {"hunks": "x"}, {"hunks": [{"file": "a"}]}, {"hunks": [{"file": 1, "hunk": "h"}]},
    {"hunks": [["a", "h"]]}, {"hunks": [None]},
])
def test_malformed_artifact_is_not_ok_and_never_raises(tmp_path, artifact):
    p = tmp_path / "d.txt"
    p.write_text(DIFF)
    v = co.check("review_slice", artifact, {"diff_path": str(p)})
    assert v["ok"] is False
    assert co.settle("review_slice", v) == "drop"


def test_missing_ctx_or_unreadable_diff_is_an_oracle_error(tmp_path):
    v = co.check("review_slice", _slice(PAIRS), {})
    assert v["ok"] is False and v["reason"].startswith("oracle-error")
    v = co.check("review_slice", _slice(PAIRS), {"diff_path": str(tmp_path / "absent")})
    assert v["ok"] is False and v["reason"].startswith("oracle-error")


def test_artifact_claims_are_ignored(tmp_path):
    art = {**_slice([("src/app.py", "@@ forged\n")]), "ok": True, "passed": True}
    p = tmp_path / "d.txt"
    p.write_text(DIFF)
    assert co.check("review_slice", art, {"diff_path": str(p)})["ok"] is False


# --- parser robustness: content is never structure ---------------------------------


def test_lookalike_header_lines_inside_a_hunk_are_content(tmp_path):
    hunk = ('@@ -1,5 +1,7 @@\n ctx\n+"diff --git a/z b/z"\n+++ b/q\n--- a/q\n'
            '+@@ -9 +9 @@ not a hunk\n+\\ literal\n ctx2\n')
    text = ("diff --git a/real.py b/real.py\n--- a/real.py\n+++ b/real.py\n" + hunk
            + GONE_BLOCK)
    assert co._diff_hunks(text) == {("real.py", hunk), PAIRS[2]}
    v = _run(tmp_path, text, [("real.py", hunk)])
    assert v["ok"] is True, v
    assert _run(tmp_path, text, [("z", hunk)])["ok"] is False
    assert _run(tmp_path, text, [("q", hunk)])["ok"] is False


def test_a_block_starts_only_at_the_start_of_a_line():
    hunk = "@@ -1 +1 @@\n-a\n+see diff --git a/x b/x here\n"
    text = "diff --git a/f b/f\n--- a/f\n+++ b/f\n" + hunk
    assert co._diff_hunks(text) == {("f", hunk)}


def test_split_is_on_newlines_only_not_on_other_line_separators():
    hunk = "@@ -1 +1 @@\n-a\n+x\x0c@@ y\x85diff --git a/q b/q +++ b/w\n"
    text = "diff --git a/f b/f\n--- a/f\n+++ b/f\n" + hunk
    assert co._diff_hunks(text) == {("f", hunk)}


@pytest.mark.parametrize("order", [
    (BINARY_BLOCK, APP_BLOCK, GONE_BLOCK),                 # hunk-less block first
    (APP_BLOCK, RENAME_BLOCK, GONE_BLOCK),                 # in the middle
    (APP_BLOCK, GONE_BLOCK, MODE_BLOCK),                   # last
    (APP_BLOCK, GONE_BLOCK, RENAME_BLOCK),
    (APP_BLOCK, GONE_BLOCK, BINARY_BLOCK),
    (BINARY_BLOCK, APP_BLOCK, RENAME_BLOCK, GONE_BLOCK, MODE_BLOCK),
])
def test_hunkless_blocks_contribute_nothing_wherever_they_sit(tmp_path, order):
    text = "".join(order)
    assert co._diff_hunks(text) == set(PAIRS)
    for pairs in ([PAIRS[1]], PAIRS):
        v = _run(tmp_path, text, pairs)
        assert v["ok"] is True, v


def test_mixed_real_style_diff_with_new_file_parses_to_the_edit_blocks_only(tmp_path):
    text = BINARY_BLOCK + APP_BLOCK + RENAME_BLOCK + NEW_FILE_BLOCK + GONE_BLOCK + MODE_BLOCK
    want = set(PAIRS) | {("new.txt", "@@ -0,0 +1 @@\n+hello\n")}
    assert co._diff_hunks(text) == want
    v = _run(tmp_path, text, sorted(want)[:2])
    assert v["ok"] is True, v


def test_only_hunkless_blocks_parse_to_the_empty_set():
    assert co._diff_hunks(BINARY_BLOCK + RENAME_BLOCK + MODE_BLOCK) == set()
    assert co._diff_hunks("") == set()


def test_a_block_with_hunks_but_no_file_is_an_oracle_error(tmp_path):
    text = "diff --git a/f b/f\nindex 1..2 100644\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(ValueError):
        co._diff_hunks(text)
    v = _run(tmp_path, text, [("f", "@@ -1 +1 @@\n-a\n+b\n")])
    assert v["ok"] is False and v["reason"].startswith("oracle-error")
    assert co.settle("review_slice", v) == "drop"


def test_crlf_content_is_compared_byte_for_byte(tmp_path):
    hunk = "@@ -1,2 +1,2 @@\n-a\r\n+b\r\n c\r\n"
    text = "diff --git a/w.txt b/w.txt\n--- a/w.txt\n+++ b/w.txt\n" + hunk
    assert _run(tmp_path, text, [("w.txt", hunk)])["ok"] is True
    assert _run(tmp_path, text, [("w.txt", hunk.replace("\r\n", "\n"))])["ok"] is False


def test_a_path_with_spaces_drops_the_trailing_tab_git_appends():
    text = ("diff --git a/my file.py b/my file.py\n--- a/my file.py\t\n+++ b/my file.py\t\n"
            "@@ -1 +1 @@\n-a\n+b\n")
    assert co._diff_hunks(text) == {("my file.py", "@@ -1 +1 @@\n-a\n+b\n")}


def test_a_last_line_without_a_newline_is_newline_terminated():
    text = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b"
    assert co._diff_hunks(text) == {("f", "@@ -1 +1 @@\n-a\n+b\n")}


# --- path_line: review_refs (task 2.2) -------------------------------------------


def test_path_line_cases(tmp_path):
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    file = root / "src" / "app.py"
    file.write_text("a\nb\nc\n", encoding="utf-8")
    ctx = {"root": str(root)}

    def run(refs):
        return co.check("review_refs", {"refs": refs}, ctx)

    def ref(path="src/app.py", line=2, note="a ref"):
        return {"path": path, "line": line, "note": note}

    # a valid ref passes
    v = run([ref()])
    assert v["ok"] is True, v
    assert v["oracle"] == "path_line"
    assert co.settle("review_refs", v) == "accept"
    # every line in range passes, first and last included
    assert run([ref(line=1), ref(line=3)])["ok"] is True
    # a symlink that stays inside the root is followed and passes
    (root / "link.py").symlink_to(file)
    assert run([{"path": "link.py", "line": 1, "note": "n"}])["ok"] is True
    # a note of exactly 200 chars passes
    assert run([ref(note="x" * 200)])["ok"] is True
    # exactly REFS_CAP refs passes
    assert run([ref() for _ in range(co.REFS_CAP)])["ok"] is True

    # a phantom path
    assert run([ref(path="nope.py")])["ok"] is False
    # line 0
    assert run([ref(line=0)])["ok"] is False
    # a line past EOF (the file has 3 lines)
    assert run([ref(line=4)])["ok"] is False
    # a `..` part
    assert run([ref(path="../app.py")])["ok"] is False
    assert run([ref(path="src/../../outside.py")])["ok"] is False
    # a symlink out of the root
    outside = tmp_path / "outside.py"
    outside.write_text("x\n", encoding="utf-8")
    (root / "out.py").symlink_to(outside)
    assert run([{"path": "out.py", "line": 1, "note": "n"}])["ok"] is False
    # a note over 200 chars
    assert run([ref(note="x" * 201)])["ok"] is False
    # more than REFS_CAP refs
    assert run([ref() for _ in range(co.REFS_CAP + 1)])["ok"] is False
    # zero refs
    assert run([])["ok"] is False
    # a bool line is not a valid int line
    assert run([ref(line=True)])["ok"] is False
    assert run([ref(line=False)])["ok"] is False
    # a directory is not a regular file
    assert run([{"path": "src", "line": 1, "note": "n"}])["ok"] is False
    # an absolute path is not relative
    assert run([{"path": str(file), "line": 1, "note": "n"}])["ok"] is False
    # every failure settles to drop
    assert co.settle("review_refs", run([])) == "drop"
    # a missing ctx is an oracle-error, still not ok
    v = co.check("review_refs", {"refs": [ref()]}, {})
    assert v["ok"] is False and v["reason"].startswith("oracle-error")


def test_log_substring_cases(tmp_path):
    log = tmp_path / "log.txt"
    text = "build\ttest\tok\nrun lint\tcheck\tFAILED: something went wrong\n"
    log.write_text(text, encoding="utf-8")
    ctx = {"log_path": str(log)}

    def run(quote, step):
        return co.check("ci_log_triage", {"quote": quote, "step": step}, ctx)

    # a verbatim quote plus a present step passes
    v = run("FAILED: something went wrong", "lint")
    assert v["ok"] is True, v
    assert v["oracle"] == "log_substring"
    assert co.settle("ci_log_triage", v) == "accept"
    # an edited quote fails
    assert run("FAILED: something went terribly wrong", "lint")["ok"] is False
    # an absent step fails
    assert run("FAILED: something went wrong", "nope-step")["ok"] is False
    # an empty quote fails
    assert run("", "lint")["ok"] is False
    # a quote over QUOTE_CAP fails
    assert run("x" * (co.QUOTE_CAP + 1), "lint")["ok"] is False
    # an empty step fails
    assert run("FAILED: something went wrong", "")["ok"] is False
    # a non-str quote is a failure, never a raise
    v = run(None, "lint")
    assert v["ok"] is False
    assert co.settle("ci_log_triage", v) == "drop"
    # a quote of exactly QUOTE_CAP chars is allowed when the log holds it
    pad = "y" * (co.QUOTE_CAP - 10)
    log2 = tmp_path / "long.log"
    log2.write_text("stepA\t" + pad + "\n", encoding="utf-8")
    v = co.check("ci_log_triage", {"quote": pad, "step": "stepA"},
                 {"log_path": str(log2)})
    assert v["ok"] is True, v
    # an absent log is an oracle-error, still not ok
    v = co.check("ci_log_triage", {"quote": "q", "step": "s"},
                 {"log_path": str(tmp_path / "absent")})
    assert v["ok"] is False and v["reason"].startswith("oracle-error")


# --- 2.4: every review-prep oracle is registered and documented -------------------


def test_review_oracles_registered_and_documented():
    import cheap_tier
    import cheap_oracle_run  # noqa: F401 — importing it registers observed_red
    md = (Path(__file__).resolve().parent / "cheap-dispatch.md").read_text(encoding="utf-8")
    rows = [l for l in md.splitlines() if l.lstrip().startswith("| `")]
    keys = {
        "hunk_bytes": ["hunks", "diff_path"],
        "path_line": ["refs", "root"],
        "log_substring": ["quote", "step", "log_path"],
        "observed_red": ["source", "test_name", "cwd", "head", "scratch_dir", "timeout"],
    }
    for slot in cheap_tier.REVIEW_PREP_SLOTS:
        oracle = cheap_tier.SLOTS[slot].oracle
        assert co._lookup(oracle) is not None, f"oracle {oracle!r} not registered"
        row = next((l for l in rows if l.lstrip().startswith(f"| `{oracle}` |")), None)
        assert row is not None, f"no `| {oracle} |` table row in cheap-dispatch.md"
        for key in keys[oracle]:
            assert key in row, f"{oracle} row missing {key!r}: {row}"
