"""Wiring tests (Phase 3): the `carry_handres` kwarg + fallback threaded through
`base_sync_cert.certify_link` / `find_certified_anchor` / `certified_noop_chain`, the new
`ChainResult.carry_paths`, and the REQUIRED `base_sync_cert.py` cap guard (task 3.4).

These call the PUBLIC entry points, so the independent-oracle precondition is seated
explicitly via the case-14 `_seat_oracle_on_base` shape — every certify/refuse is non-vacuous.
`carry_handres` defaults False ⇒ byte-identical behavior for existing callers (asserted).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_oracle  # noqa: E402
import file_size_guard  # noqa: E402
from base_sync_cert import (  # noqa: E402
    ChainResult,
    certified_noop_chain,
    certify_link,
    find_certified_anchor,
)
from base_sync_repo import (  # noqa: E402
    build_scenario,
    diverge_base_only,
    diverge_living_doc,
    force_merge_commit,
    make_certified_sync_merge,
)

KI = "three-pillars-docs/known_issues.md"
ARCH = "three-pillars-docs/architecture.md"
_SEED = "# Fixture Living Doc\n\n### Z0: seed entry\nseed body line.\n"
_HAND_KEEP_ALL = (
    "# Fixture Living Doc\n\n### Z0: seed entry\nseed body line.\n"
    "- **2026-01-01** — base-side change\n- **2026-01-02** — design-side change\n"
)


def _seat_oracle_on_base(s, monkeypatch) -> None:
    """Case-14 shape — see `test_base_sync_cert_attacks.py::_seat_oracle_on_base`."""
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)


def _kv(v: str) -> str:
    # Keeps the seed body and APPENDS one dated log entry (the same two lines `diverge_living_doc`
    # appends), so both sides' change is a pure insertion with an EMPTY diff3 base: a
    # `log-entry-insertion` the strict link resolves mechanically. Two `### Z1:` headings (the shape
    # before round 20) are an `id-renumber-collision`, which is gated and defers; replacing
    # `seed body line.` on both sides is a modify/modify no keep-both class admits.
    date = "2026-01-02" if v.startswith("design") else "2026-01-01"
    return f"{_SEED}- **{date}** — {v}\n"


def _establish(s, path: str, content: str) -> None:
    """Add `path` at the base branch and fast-forward design onto it (a shared ancestor)."""
    (s.origin_dir / path).parent.mkdir(parents=True, exist_ok=True)
    (s.origin_dir / path).write_text(content, encoding="utf-8")
    s.origin_git("add", "--", path)
    s.origin_git("commit", "--quiet", "-m", f"base: establish {path}")
    s.git("fetch", "--quiet", "origin", s.base_ref)
    s.git("merge", "--quiet", "--ff-only", f"origin/{s.base_ref}")


def _origin_set(s, path: str, content: str, msg: str) -> None:
    (s.origin_dir / path).write_text(content, encoding="utf-8")
    s.origin_git("add", "--", path)
    s.origin_git("commit", "--quiet", "-m", msg)


def _two_link_chain(s):
    """anchor h0 → link1 (STRICT-mechanical KI conflict) → link2 (hand-res ARCH carry). Both
    design-side changes are baked into h0 so the chain is a pure sequence of base-sync merges."""
    _establish(s, ARCH, _SEED)
    (s.repo_dir / KI).write_text(_kv("design-side change"), encoding="utf-8")
    (s.repo_dir / ARCH).write_text(_kv("design-side change"), encoding="utf-8")
    s.git("add", "--", KI, ARCH)
    s.git("commit", "--quiet", "-m", "design: bake side changes")
    h0 = s.head()
    _origin_set(s, KI, _kv("base-side change"), "base: advance KI")
    h1 = make_certified_sync_merge(s, path=KI)   # strict-mechanical link, conflicted_paths=(KI,)
    _origin_set(s, ARCH, _kv("base-side change"), "base: advance ARCH")
    h2 = force_merge_commit(s, {ARCH: _HAND_KEEP_ALL})   # hand-res link, carry=(ARCH,)
    return h0, h1, h2


# ============================================================
# Task 3.2: find_certified_anchor / certified_noop_chain + ChainResult.carry_paths
# ============================================================


def test_handres_chain_certifies_and_carry_paths_is_f3_exact(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    h0, _h1, h2 = _two_link_chain(s)
    _seat_oracle_on_base(s, monkeypatch)

    result = find_certified_anchor(str(s.repo_dir), h2, {h0}, base_ref=s.base_ref,
                                   carry_handres=True)
    assert result.certified is True
    assert result.anchor == h0
    assert result.links == 2
    # F3: ONLY the hand-res link's K aggregates. The STRICT link's own conflicted_paths (KI —
    # a mechanical no-op conflict) is NEVER mislabeled into carry_paths.
    assert result.carry_paths == (ARCH,)
    assert KI not in result.carry_paths


def test_handres_chain_non_carry_path_refuses(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    path = "skills/foo.py"
    _establish(s, path, "x = 0\n")
    (s.repo_dir / path).write_text("x = 3\n", encoding="utf-8")
    s.git("add", "--", path)
    s.git("commit", "--quiet", "-m", "design: bake foo.py change")
    h0 = s.head()
    _origin_set(s, path, "x = 2\n", "base: advance foo.py")
    h1 = force_merge_commit(s, {path: "x = 99  # hand-resolved\n"})
    _seat_oracle_on_base(s, monkeypatch)

    result = find_certified_anchor(str(s.repo_dir), h1, {h0}, base_ref=s.base_ref,
                                   carry_handres=True)
    assert result.certified is False
    assert result.reason == "non-carry path differs from clean mechanical merge"
    assert result.carry_paths == ()


def test_handres_chain_carry_false_fails_via_strict_only(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    h0, _h1, h2 = _two_link_chain(s)
    _seat_oracle_on_base(s, monkeypatch)

    strict = certified_noop_chain(str(s.repo_dir), h0, h2, base_ref=s.base_ref)   # default False
    assert strict.certified is False
    assert strict.reason == "resolved bytes do not match h1's committed blob"

    relaxed = certified_noop_chain(str(s.repo_dir), h0, h2, base_ref=s.base_ref,
                                   carry_handres=True)
    assert relaxed.certified is True
    assert relaxed.carry_paths == (ARCH,)


def test_handres_chain_cap_enforced_across_relaxed_links(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    h0, _h1, h2 = _two_link_chain(s)
    _seat_oracle_on_base(s, monkeypatch)

    result = find_certified_anchor(str(s.repo_dir), h2, {h0}, base_ref=s.base_ref,
                                   max_links=1, carry_handres=True)
    assert result.certified is False
    assert result.reason == "chain cap 1 exceeded — re-approve on the current head"


# ============================================================
# Task 3.4: base_sync_cert.py stays < 500 lines (REQUIRED cap guard)
# ============================================================


def test_base_sync_cert_under_cap():
    """The module started at 473/500 lines; Phase 3 added ONLY kwarg-threading + a 2-line
    fallback per entry point + one ChainResult field — ALL new logic lives in
    living_doc_carry.py. This pins that the split held and no logic leaked into the file."""
    from pathlib import Path

    lines, chars, _text = file_size_guard.measure(Path(__file__).with_name("base_sync_cert.py"))
    assert lines <= 500, f"base_sync_cert.py is {lines} lines (> 500 hard cap)"
    assert chars <= 50_000, f"base_sync_cert.py is {chars} chars (> 50k hard cap)"


# ============================================================
# Hardening: the carry fallback honors the module's never-raises contract
# ============================================================


def test_certify_link_fallback_fail_closed_on_broken_sibling(monkeypatch):
    """never-raises: if the living_doc_carry sibling cannot import (broken install / syntax
    error / a broken verify.py at its module load), certify_link(carry_handres=True) must return
    a fail-closed LinkCheck, NEVER propagate the exception. Oracle passes + strict fails so the
    carry fallback branch is the code under test."""
    import base_sync_cert
    from base_sync_cert import LinkCheck, certify_link

    monkeypatch.setattr(base_sync_cert, "_oracle_guard", lambda *a, **k: (True, ""))
    monkeypatch.setattr(base_sync_cert, "_certify_link_unchecked",
                        lambda *a, **k: LinkCheck(False, "strict refused"))
    # A `None` entry in sys.modules makes `import living_doc_carry` raise ImportError.
    monkeypatch.setitem(sys.modules, "living_doc_carry", None)

    lc = certify_link("/nonexistent", "h0", "h1", base_ref="main", carry_handres=True)
    assert lc.ok is False   # fail-closed, no exception escaped


def test_certify_link_carry_independently_never_raises(monkeypatch):
    """certify_link_carry is independently total — even its git-seam setup (the
    `import base_sync_cert` + `_make_default_git`) is inside the try, so an exception there yields
    a fail-closed LinkCheck rather than propagating."""
    import base_sync_cert
    import living_doc_carry

    def _boom(*a, **k):
        raise RuntimeError("git seam construction blew up")

    monkeypatch.setattr(base_sync_cert, "_make_default_git", _boom)
    lc = living_doc_carry.certify_link_carry("/nonexistent", "h0", "h1", base_ref="main")
    assert lc.ok is False


# ============================================================
# Task 3.1: certify_link carry_handres kwarg + fallback (single link)
# ============================================================


def test_certify_link_fallback_carry_true_certifies(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = force_merge_commit(s, {KI: _HAND_KEEP_ALL})
    _seat_oracle_on_base(s, monkeypatch)

    lc = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref, carry_handres=True)
    assert lc.ok is True, lc.reason
    assert lc.conflicted_paths == (KI,)


def test_certify_link_default_refuses_byte_exact(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = force_merge_commit(s, {KI: _HAND_KEEP_ALL})
    _seat_oracle_on_base(s, monkeypatch)

    lc = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref)   # default carry_handres=False
    assert lc.ok is False
    assert lc.reason == "resolved bytes do not match h1's committed blob"
    assert certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref, carry_handres=False) == lc


def test_certify_link_strict_certifiable_identical_under_both_flags(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    h1 = make_certified_sync_merge(s)   # a real strict-certifiable AUTO-SAFE link
    _seat_oracle_on_base(s, monkeypatch)

    lc_false = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref, carry_handres=False)
    lc_true = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref, carry_handres=True)
    assert lc_false.ok is True
    assert lc_false == lc_true   # zero behavior change: the fallback never fires on a strict pass
