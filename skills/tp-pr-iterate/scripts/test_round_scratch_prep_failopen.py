"""The hook is fail-open (D11): a prep failure never refuses the round.

design: cheap-tier-review-prep (Task 4.3)

A missing `prep_dir`, a `meta.json` naming another head, an unparseable
`meta.json`, or a `render`/`move_work` that raises must each leave `prepare`
returning normally (the golden `angles.json` bytes, CLI rc 0) and writing
exactly one `[cheap-tier] prep not applied: <why>` line to the loop log —
never a `prepare-refused`. Without a `prep_dir`, no log line is written at
all, and a log write that itself fails (e.g. the log path is a directory)
still leaves `prepare` returning the golden bytes.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_prep  # noqa: E402
from test_round_scratch_prep import LOG, _call, _golden, _prep_dir  # noqa: E402

PFX = "[cheap-tier] prep not applied: "


def _failopen(root, r, contains=None) -> list[str]:
    """`prepare` returned a round dir with the golden bytes and exactly one log line."""
    assert r.is_dir()
    assert (r / "angles.json").read_text(encoding="utf-8") == _golden(r, root)
    lines = [ln for ln in (root / LOG).read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith(PFX), lines
    if contains is not None:
        assert contains in lines[0], lines
    return lines


def test_missing_prep_dir(tmp_path):
    root = tmp_path / "proof"
    r = _call(root, prep_dir=tmp_path / "nope")
    _failopen(root, r, "FileNotFoundError")


def test_foreign_head(tmp_path):
    w = _prep_dir(tmp_path, head="other")
    root = tmp_path / "proof"
    r = _call(root, prep_dir=w)
    _failopen(root, r, "other")
    assert w.is_dir()  # NOT moved


def test_unparseable_meta(tmp_path):
    w = _prep_dir(tmp_path)
    (w / "meta.json").write_text("{not json", encoding="utf-8")
    root = tmp_path / "proof"
    r = _call(root, prep_dir=w)
    _failopen(root, r, "JSONDecodeError")


def test_render_oserror(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(review_prep, "render", boom)
    w = _prep_dir(tmp_path, accepted={
        "review_slice--correctness-leak.json":
            {"hunks": [{"file": "a.py", "hunk": "@@ -1 +1 @@\n-x\n+y\n"}]}})
    root = tmp_path / "proof"
    r = _call(root, prep_dir=w)
    _failopen(root, r, "OSError")


def test_move_work_valueerror(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad")
    monkeypatch.setattr(review_prep, "move_work", boom)
    w = _prep_dir(tmp_path)
    root = tmp_path / "proof"
    r = _call(root, prep_dir=w)
    _failopen(root, r, "ValueError")


def test_render_keyerror(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise KeyError("k")
    monkeypatch.setattr(review_prep, "render", boom)
    w = _prep_dir(tmp_path)
    root = tmp_path / "proof"
    r = _call(root, prep_dir=w)
    _failopen(root, r, "KeyError")


def test_no_prep_dir_writes_no_log(tmp_path):
    root = tmp_path / "proof"
    r = _call(root)
    assert (r / "angles.json").read_text(encoding="utf-8") == _golden(r, root)
    log = root / LOG
    assert not log.exists() or log.read_text(encoding="utf-8") == ""


def test_log_write_failure_still_returns(tmp_path):
    root = tmp_path / "proof"
    (root / LOG).mkdir(parents=True)  # open(..., "a") -> IsADirectoryError
    r = _call(root, prep_dir=tmp_path / "nope")
    assert (r / "angles.json").read_text(encoding="utf-8") == _golden(r, root)
