"""Unit tests for the shared AUTO-SAFE conflict-resolution module.

`auto_safe_resolution.py` is the ONE definition both the merge-back producer
(`merge_driver.py`) and the (Phase 2) base-sync certificate verifier run. These tests pin:
  (a) the AUTO_SAFE_PATHS allowlist matches merge_driver's living-doc list (single-definition
      guard);
  (b) resolve_conflict_bytes reproduces resolve_living_doc's merged bytes exactly, on an
      asymmetric fixture where any positional/keyword confusion between (base, ours, theirs)
      is byte-detectable;
  (c) resolve_conflict_bytes is keyword-only -- a positional call raises TypeError;
  (d) the bytes-explicit blob/encoding policy: CRLF survives the diff3-building step
      byte-identically (no universal-newline translation anywhere), and undecodable
      (non-UTF-8) content is a detectable strict-decode failure.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from auto_safe_resolution import (  # noqa: E402
    AUTO_SAFE_PATHS,
    DEFER,
    is_auto_safe_path,
    resolve_conflict_bytes_detail,
    RESOLVED,
    _diff3_conflict_text,
    decode_blob_strict,
    resolve_conflict_bytes,
)

_MERGE_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "tp-merge-from-main", "scripts")
)
sys.path.insert(0, _MERGE_SCRIPTS)
import merge_driver  # noqa: E402

KI = "three-pillars-docs/known_issues.md"


def _git(repo, *args, check=True):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=env)


def _asymmetric_repo(tmp_path):
    """base/ours/theirs pairwise structurally distinct -- ANY positional swap between
    (base, ours, theirs) is byte-detectable in the merged output. Both sides append dated log
    entries after base's last entry: a `log-entry-insertion` that fully auto-resolves. (Before
    round 20 this was an `id-renumber-collision`, a class now gated.)"""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / "three-pillars-docs").mkdir()
    base_txt = "*Last updated: 2026-05-01*\n\n# Known issues\n\n### L1: base issue\nbody\n"
    ours_txt = base_txt + "- **2026-05-02** — ours unique entry\n"
    theirs_txt = base_txt + "- **2026-05-03** — theirs entry one\n- **2026-05-04** — theirs entry two\n"
    (repo / KI).write_text(base_txt)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "design")
    (repo / KI).write_text(ours_txt)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "ours")
    _git(repo, "checkout", "-q", "master")
    (repo / KI).write_text(theirs_txt)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "theirs")
    _git(repo, "checkout", "-q", "design")
    return repo, base_txt, ours_txt, theirs_txt


# ---- (a) single-definition guard --------------------------------------------------

def test_allowlist_matches_merge_driver_living_docs():
    assert AUTO_SAFE_PATHS == frozenset(merge_driver.DEFAULT_LIVING_DOCS)


# ---- (b) asymmetric parity fixture -------------------------------------------------

def test_resolve_conflict_bytes_reproduces_resolve_living_doc_bytes(tmp_path):
    repo, base_txt, ours_txt, theirs_txt = _asymmetric_repo(tmp_path)
    report = merge_driver.merge_back(str(repo), "master")
    assert KI in report.auto_resolved, report.to_json()
    written = (repo / KI).read_text(encoding="utf-8")

    status, merged = resolve_conflict_bytes(base=base_txt, ours=ours_txt, theirs=theirs_txt)
    assert status == RESOLVED
    assert merged == written
    # BYTES, not just text. `_cond5_resolve` re-derives the expected blob oid from
    # `merged.encode("utf-8")`, so the identity that matters is on-disk bytes == those bytes. A
    # text-mode write would encode with the ambient locale and translate `\n` -> `os.linesep`,
    # which `read_text` above would silently translate BACK, hiding the mismatch.
    assert (repo / KI).read_bytes() == merged.encode("utf-8")

    # Asymmetry backstop: swapping the base<->ours keyword mapping changes the result -- proving
    # the fixture actually detects a positional/keyword confusion, not a coincidental match.
    _swapped_status, swapped_merged = resolve_conflict_bytes(
        base=ours_txt, ours=base_txt, theirs=theirs_txt)
    assert swapped_merged != merged


# ---- (c) keyword-only ---------------------------------------------------------------

def test_resolve_conflict_bytes_is_keyword_only():
    with pytest.raises(TypeError):
        resolve_conflict_bytes("base", "ours", "theirs")  # type: ignore[misc]


# ---- (d) bytes-explicit blob/encoding policy -----------------------------------------

def test_diff3_conflict_text_preserves_crlf_bytes():
    # No universal-newline translation anywhere on the path: a CRLF-only file merges to itself
    # (all three sides identical -> no conflict) with \r\n intact, byte-for-byte.
    content = "line one\r\nline two\r\n"
    out = _diff3_conflict_text(base=content, ours=content, theirs=content)
    assert out == content


def test_crlf_bytes_round_trip_through_binary_subprocess_capture(tmp_path):
    """The blob-acquisition discipline (binary capture, never text=True) must not mangle CRLF --
    Python's subprocess text=True mode applies universal-newline translation that silently
    converts \r\n -> \n even though git preserves the original bytes in the blob."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / "f.md").write_bytes(b"line one\r\nline two\r\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "crlf blob")
    oid = _git(repo, "rev-parse", "HEAD:f.md").stdout.strip()
    raw = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", oid],
                         capture_output=True).stdout   # binary, never text=True
    assert raw == b"line one\r\nline two\r\n"
    assert decode_blob_strict(raw) == "line one\r\nline two\r\n"


def test_undecodable_content_is_a_strict_decode_failure():
    with pytest.raises(UnicodeDecodeError):
        decode_blob_strict(b"\xff\xfe not valid utf-8")


# ---- Task 1.3: the per-file "a mechanical resolution was applied" fact -----------------------

def test_detail_reports_mechanical_applied():
    """`resolve_conflict_bytes_detail` exposes the OR-of-hunks fact `verify()` needs to tell
    'nothing was lost' from 'nothing was examined'. A real `log-entry-insertion` conflict
    resolves mechanically -> True; a generic-prose conflict defers -> False."""
    base = "# Architecture\n\n## History\n\n- **2026-07-01** — decision A\n"
    ours = ("# Architecture\n\n## History\n\n"
            "- **2026-07-04** — decision OURS\n- **2026-07-01** — decision A\n")
    theirs = ("# Architecture\n\n## History\n\n"
              "- **2026-07-05** — decision THEIRS\n- **2026-07-01** — decision A\n")
    status, merged, mechanical = resolve_conflict_bytes_detail(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED and mechanical is True
    assert "decision OURS" in merged and "decision THEIRS" in merged

    p_base = "# Doc\n\nSome shared prose paragraph.\n"
    p_ours = "# Doc\n\nOurs rewrote the paragraph entirely.\n"
    p_theirs = "# Doc\n\nTheirs rewrote it a different way.\n"
    status, _merged, mechanical = resolve_conflict_bytes_detail(
        base=p_base, ours=p_ours, theirs=p_theirs)
    assert status == DEFER and mechanical is False


def test_detail_and_plain_agree_on_bytes():
    """`resolve_conflict_bytes` must stay a pure delegate — the RME-certified byte path and its
    signature are unchanged, so both forms produce byte-identical output."""
    base = "# Architecture\n\n## History\n\n- **2026-07-01** — decision A\n"
    ours = base.replace("## History\n\n", "## History\n\n- **2026-07-04** — decision OURS\n")
    theirs = base.replace("## History\n\n", "## History\n\n- **2026-07-05** — decision THEIRS\n")
    plain = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    detail = resolve_conflict_bytes_detail(base=base, ours=ours, theirs=theirs)
    assert detail[:2] == plain


def test_detail_is_keyword_only():
    with pytest.raises(TypeError):
        resolve_conflict_bytes_detail("b", "o", "t")   # type: ignore[misc]


# ---- Task 1.9: `tp-designs/*/decisions.md` joins the mechanical lane -------------------------

def test_is_auto_safe_path_admits_design_decisions_log():
    assert is_auto_safe_path("three-pillars-docs/tp-designs/some-slug/decisions.md") is True
    assert is_auto_safe_path("three-pillars-docs/tp-designs/a-b-c-123/decisions.md") is True
    # the five exact allowlist members still qualify
    for p in AUTO_SAFE_PATHS:
        assert is_auto_safe_path(p) is True


def test_is_auto_safe_path_rejects_siblings_and_traversal():
    rejected = [
        "three-pillars-docs/tp-designs/some-slug/design.md",      # sibling artifacts
        "three-pillars-docs/tp-designs/some-slug/plan.md",
        "three-pillars-docs/tp-designs/some-slug/handoff.md",
        "three-pillars-docs/tp-designs/some-slug/lock.json",
        "three-pillars-docs/tp-designs/some-slug/a/decisions.md",  # nested — [^/]+ is one segment
        "three-pillars-docs/tp-designs/decisions.md",              # no slug segment
        "three-pillars-docs/completed-tp-designs/some-slug/decisions.md",   # frozen archive
        "three-pillars-docs/tp-designs/../secrets/decisions.md",   # traversal
        "../three-pillars-docs/tp-designs/s/decisions.md",
        "three-pillars-docs/tp-designs/some-slug/decisions.md.bak",
        "xthree-pillars-docs/tp-designs/s/decisions.md",           # unanchored prefix
        "",
        # `$` matches BEFORE a trailing newline, so `^...$` admitted these — contradicting the
        # "fully anchored" claim. `fullmatch` + `[^/\n]+` closes both.
        "three-pillars-docs/tp-designs/some-slug/decisions.md\n",
        "three-pillars-docs/tp-designs/some-slug/decisions.md\nrogue",
        # `[^/]+` alone admits a `.`/`..` slug, which normalizes OUT of the designs tree.
        "three-pillars-docs/tp-designs/../decisions.md",
        "three-pillars-docs/tp-designs/./decisions.md",
    ]
    for p in rejected:
        assert is_auto_safe_path(p) is False, p
    # total: any exception fails closed
    assert is_auto_safe_path(None) is False
    assert is_auto_safe_path(123) is False


def test_auto_safe_paths_and_default_living_docs_are_unchanged():
    # The exact-membership allowlist is NOT widened by this design — the pattern is an addition
    # inside `is_auto_safe_path`, so the single-definition guard still holds.
    assert AUTO_SAFE_PATHS == frozenset(merge_driver.DEFAULT_LIVING_DOCS)
    assert "three-pillars-docs/tp-designs/some-slug/decisions.md" not in AUTO_SAFE_PATHS
