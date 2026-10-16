"""cert_brief — the certifier's dispatch prompt: claims bytes plus the subject diff.

design: certifier-lean (Task 1.7; design.md Scope "Smaller certifier brief"). The brief
carries the claims file verbatim inside a fence its own content cannot close, the
certified SHA, the resolved `$CERT` path, the protocol pointer and the diff of the
claims' `subjects` ONLY: no design text and no non-subject change reaches the certifier.
Real temp repos (test_certify_scratch helpers, git_env), so this file is tiered dev (P3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import cert_brief
import certify_cli

# dev-only fixture modules, guarded so a tree that ships without them skips.
test_certify_scratch = pytest.importorskip("test_certify_scratch")
test_certify_status = pytest.importorskip("test_certify_status")
make_repo = test_certify_scratch.make_repo
commit_files = test_certify_scratch.commit_files
FILES = test_certify_status.FILES
GUARD = test_certify_status.GUARD
claim = test_certify_status.claim

DESIGN = "three-pillars-docs/tp-designs/demo/design.md"
SENTINEL1 = "DESIGN-SENTINEL-1"
SENTINEL2 = "DESIGN-SENTINEL-2"
INSTALL_NEW = "Install with the plugin route, then verify.\n"
CERT = "/abs/certify.py"
NAME = "impl-audit.claims.json"


def claims_doc() -> dict:
    return {"disposition": "verdict", "claims": [claim(subjects=["docs/install.md"])]}


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    """`base`: FILES plus the design; `head`: one commit touching both subjects and the design."""
    path, base = make_repo(tmp_path / "caller", {**FILES, DESIGN: SENTINEL1 + "\n"})
    head = commit_files(path, {"docs/install.md": INSTALL_NEW, "docs/old.md": "older\n",
                               DESIGN: SENTINEL2 + "\n"})
    return path, base, head


def fences(text: str) -> list[str]:
    """Every fence line of a rendered prompt (a line that is only backticks)."""
    return [ln for ln in text.splitlines() if ln.strip() and set(ln.strip()) == {"`"}]


# --- the diff of the claims' subjects only (the smaller brief) --------------------------------

def test_subject_diff_is_subjects_only(repo):
    path, base, head = repo
    d = cert_brief.subject_diff(path, base, head, ["docs/install.md"])
    assert "docs/install.md" in d, d
    assert "+Install with the plugin route, then verify." in d, d
    assert "docs/old.md" not in d, "a non-subject change never reaches the brief"
    assert "DESIGN-SENTINEL" not in d, "the design never reaches the brief"


def test_no_subjects_diffs_nothing(repo):
    """An empty pathspec must not fall back to the whole-repo diff."""
    path, base, head = repo
    assert cert_brief.subject_diff(path, base, head, []) == ""


# --- the prompt --------------------------------------------------------------------------------

def test_prompt_parts(repo, tmp_path):
    path, base, head = repo
    claims = write_json(tmp_path / NAME, claims_doc())
    body = claims.read_text(encoding="utf-8")
    d = cert_brief.subject_diff(path, base, head, ["docs/install.md"])
    out = cert_brief.prompt(body.encode(), sha=head, cert_path=CERT, diff=d)
    assert body in out, "the claims bytes are verbatim"
    assert head in out
    assert CERT in out
    assert "skills/_shared/certification-protocol.md" in out
    assert "+Install with the plugin route, then verify." in out
    assert "DESIGN-SENTINEL" not in out
    assert "docs/old.md" not in out


def test_fence_outlasts_content():
    """A claim body holding a 4-backtick run is fenced (and closed) by >= 5 backticks."""
    body = '{"claims": [{"id": "c1", "property": "```` four ````"}]}\n'
    out = cert_brief.prompt(body.encode(), sha="s" * 40, cert_path=CERT, diff="")
    longest = max(len(m) for m in re.findall(r"`+", body))
    assert longest >= 4
    runs = fences(out)
    assert runs, "the prompt fences its data"
    opener = next(r for r in runs if len(r) > longest)
    assert len(opener) >= 5, runs
    open_at = out.index(opener)
    close_at = out.index(opener, open_at + len(opener))
    assert body in out[open_at:close_at], "verbatim inside one fence"
    assert out.count(opener) == 2, "the same fence opens and closes it"


def test_subjects_of():
    doc = {"disposition": "verdict", "claims": [
        claim(subjects=["docs/install.md", "docs/old.md"]),
        claim(id="c2", subjects=["docs/old.md", GUARD]),
        claim(id="c3")]}
    doc["claims"][2].pop("subjects")
    assert cert_brief.subjects_of(doc) == ["docs/install.md", "docs/old.md", GUARD]
    assert cert_brief.subjects_of({"disposition": "verdict"}) == []


# --- the CLI surface ----------------------------------------------------------------------------

def test_cli(repo, tmp_path, capsys):
    path, base, head = repo
    claims = write_json(tmp_path / NAME, claims_doc())
    code = certify_cli.main(["brief", "--claims", str(claims), "--ref", "HEAD", "--base", base,
                             "--cert-path", CERT, "--repo", str(path)])
    assert code == 0
    printed = capsys.readouterr().out
    assert head in printed and CERT in printed
    assert "skills/_shared/certification-protocol.md" in printed
    assert claims.read_text(encoding="utf-8") in printed
    assert "+Install with the plugin route, then verify." in printed
    assert "DESIGN-SENTINEL" not in printed and "docs/old.md" not in printed


def test_cli_bad_ref_or_relative_cert_path(repo, tmp_path, capsys):
    path, base, _head = repo
    claims = write_json(tmp_path / NAME, claims_doc())
    for argv in (["brief", "--claims", str(claims), "--ref", "deadbeef", "--base", base,
                  "--cert-path", CERT, "--repo", str(path)],
                 ["brief", "--claims", str(claims), "--ref", "HEAD", "--base", "deadbeef",
                  "--cert-path", CERT, "--repo", str(path)],
                 ["brief", "--claims", str(claims), "--ref", "HEAD", "--base", base,
                  "--cert-path", "certify.py", "--repo", str(path)],
                 ["brief", "--claims", str(tmp_path / "absent.json"), "--ref", "HEAD",
                  "--base", base, "--cert-path", CERT, "--repo", str(path)]):
        assert certify_cli.main(argv) == 2
