"""cert_gap — the PR certification block and the `tp:cert-gap` label.

design: certifier-lean (Task 1.6; Behaviors 3, 6). `block` renders one bullet per gap,
note and lint-dropped claim; `apply_label` goes through the forge adapter, and every
non-`ok` outcome (a degraded adapter result, an unavailable bot identity) or an absent
gap leaves the block as the only record and prints one line. Pure formatter plus one
adapter call behind an injected seam — tiered dev, no repo, no network.
"""

from __future__ import annotations

import json

import pytest

import cert_gap
import certify_cli
import forge
import github_pr_author

GAP_KEY = "records/impl-audit.claims.json#g1"
NOTE_KEY = "records/impl-audit.claims.json#n1"

# Exactly the shape `cert_claim_lint.lint` emits: `dropped` is the whole dropped
# claim dicts, `lines` an ordered list of "<id>: <reason>" strings.
LINT = {"dropped": [{"id": "c9", "guard": "missing.py", "subjects": ["a.py"]}],
        "lines": ["c9: guard-absent"]}


def route(gaps=(), notes=()):
    """A dict shaped exactly like `cert_route.decide`'s return."""
    return {"route": "cert-gap" if gaps else "proceed", "escalate": None, "retry": None,
            "cert_fix": None, "gaps": list(gaps), "notes": list(notes),
            "retry_with_advice": False, "continue_verdict": "pass-with-notes"}


ONE_GAP = [{"key": GAP_KEY, "file": "records/impl-audit.claims.json", "id": "g1",
            "reasons": ["no-result", "budget"]}]
ONE_NOTE = [{"key": NOTE_KEY, "file": "records/impl-audit.claims.json", "id": "n1",
             "status": "not-binding", "reasons": ["red-guard-holds"]}]


def bullets(text):
    lines = text.splitlines()
    assert lines[0].startswith("#### "), lines[0]
    return [ln for ln in lines[1:] if ln.startswith("- ")]


# --- the PR block (Behavior 3) -------------------------------------------------------------

def test_block_lists_each_item_once():
    text = cert_gap.block(route(ONE_GAP, ONE_NOTE), LINT)
    items = bullets(text)
    assert len(items) == 3, items
    gap_line = next(ln for ln in items if "g1" in ln)
    assert GAP_KEY in gap_line and "no-result" in gap_line and "budget" in gap_line
    note_line = next(ln for ln in items if "n1" in ln)
    assert NOTE_KEY in note_line and "not-binding" in note_line
    lint_line = next(ln for ln in items if "c9" in ln)
    assert "`c9`" in lint_line and "{" not in lint_line, lint_line
    assert "guard-absent" in lint_line, lint_line


def test_block_with_nothing_lists_one_bullet():
    items = bullets(cert_gap.block(route()))
    assert len(items) == 1, items


def test_dropped_claim_multiple_reasons_join_in_order():
    lint = {"dropped": [{"id": "c1", "guard": "g.py", "subjects": ["a.py"]}],
            "lines": ["file: cap", "c1: guard-absent", "c10: subjects-absent",
                      "c1: no-subjects"]}
    items = bullets(cert_gap.block(route(), lint))
    assert items == ["- dropped claim `c1`: guard-absent; no-subjects"], items


def test_dropped_claim_no_matching_line_falls_back():
    lint = {"dropped": [{"id": "c9"}], "lines": ["c10: guard-absent"]}
    items = bullets(cert_gap.block(route(), lint))
    assert items == ["- dropped claim `c9`: dropped by the claim lint"], items


def test_dropped_claim_bare_id_string_still_works():
    lint = {"dropped": ["c9"], "lines": ["c9: guard-absent"]}
    items = bullets(cert_gap.block(route(), lint))
    assert items == ["- dropped claim `c9`: guard-absent"], items


# --- the label through the forge adapter (Behavior 6) --------------------------------------

class Recorder:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def __call__(self, repo, number, name, **kw):
        self.calls.append((repo, number, name))
        if self.exc is not None:
            raise self.exc
        return self.result


def test_label_ok():
    fake = Recorder(forge.Result.ok({}))
    line = cert_gap.apply_label("o/r", 7, route(ONE_GAP), label_add=fake)
    assert line.startswith("cert-gap: labelled"), line
    assert fake.calls == [("o/r", 7, cert_gap.LABEL)]


def test_label_degraded_is_one_skipped_line():
    degrade = 'label "tp:cert-gap" does not exist in o/r'
    fake = Recorder(forge.Result.degraded(degrade))
    line = cert_gap.apply_label("o/r", 7, route(ONE_GAP), label_add=fake)
    assert "\n" not in line and line.startswith("cert-gap: label skipped"), line
    assert degrade in line
    assert cert_gap.block(route(ONE_GAP)) == cert_gap.block(route(ONE_GAP))


def test_label_bot_unavailable_is_skipped():
    fake = Recorder(exc=github_pr_author.BotAuthUnavailable("no bot token"))
    line = cert_gap.apply_label("o/r", 7, route(ONE_GAP), label_add=fake)
    assert line.startswith("cert-gap: label skipped"), line


def test_real_adapter_on_an_unsupported_forge():
    info = forge.ForgeInfo("other", "git.example.com", "o", "r", "", "", "unknown host")
    line = cert_gap.apply_label("o/r", 7, route(ONE_GAP), info=info)
    assert line.startswith("cert-gap: label skipped"), line


def test_no_gaps_no_call():
    fake = Recorder(forge.Result.ok({}))
    assert cert_gap.apply_label("o/r", 7, route(), label_add=fake) == "cert-gap: none"
    assert fake.calls == []


# --- the CLI surface -----------------------------------------------------------------------

def test_cli(tmp_path, capsys, monkeypatch):
    route_file = tmp_path / "route.json"
    route_file.write_text(json.dumps(route(ONE_GAP, ONE_NOTE)), encoding="utf-8")
    lint_file = tmp_path / "lint.json"
    lint_file.write_text(json.dumps(LINT), encoding="utf-8")

    assert certify_cli.main(["gap-block", "--route", str(route_file),
                             "--lint", str(lint_file)]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("#### "), printed
    assert len(bullets(printed)) == 3

    monkeypatch.setattr(forge, "label_add",
                        Recorder(forge.Result.degraded("labels unsupported here")))
    assert certify_cli.main(["gap-label", "--route", str(route_file),
                             "--pr", "7", "--repo", "o/r"]) == 0
    out = capsys.readouterr().out
    assert out.strip().startswith("cert-gap: label skipped"), out

    assert certify_cli.main(["gap-block", "--route", str(tmp_path / "nope.json")]) == 2
