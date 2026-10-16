"""test_operator_accept_pred.py — Behavior 16: an operator-accept stands on THIS head.

Hermetic: injected `runners={"self_login_fn","reviews_fn"}` with REST review
payloads (`user`/`state`/`commit_id`/`submitted_at`/`body`) — never a live gh call.
PASS only for the LATEST review of a HUMAN author that is APPROVED, current on the
head, and whose body accepts that exact sha. A bot author, the self login, a
COMMENTED / CHANGES_REQUESTED review, another head or a fetch failure is
INDETERMINATE — never FAIL, never a raise.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import operator_accept  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402

PR = "https://github.com/o/r/pull/1"
H = "0123456789abcdef0123456789abcdef01234567"
H2 = "aabbccddeeff00112233445566778899aabbccdd"
SELF = "curtisthebot"


def _runners(reviews, self_login=SELF):
    return {
        "self_login_fn": lambda: self_login,
        "reviews_fn": lambda url: reviews,
    }


def _review(login, state, commit_id, body, when="2026-10-01T00:00:00Z", rtype="User"):
    return {
        "user": {"login": login, "type": rtype},
        "state": state,
        "commit_id": commit_id,
        "submitted_at": when,
        "body": body,
    }


def _accept(sha=H, reason="gate lows are fine"):
    return f"tp-accept: {sha} {reason}"


def _pred(runners, head=H):
    return operator_accept.pred_operator_accept(PR, head, runners=runners)


def test_accept_on_head_passes_naming_author_sha_and_reason():
    r = _pred(_runners([_review("curtis", "APPROVED", H, _accept())]))
    assert r.verdict is GateVerdict.PASS
    assert r.name == "operator_accept"
    assert r.detail == f"operator-accept by curtis on {H[:7]}: gate lows are fine"


def test_accept_passes_for_its_own_head_only():
    reviews = [_review("curtis", "APPROVED", H, _accept(H))]
    assert _pred(_runners(reviews), head=H).verdict is GateVerdict.PASS
    assert _pred(_runners(reviews), head=H2).verdict is GateVerdict.INDETERMINATE


def test_accept_sha_other_than_head_is_indeterminate():
    r = _pred(_runners([_review("curtis", "APPROVED", H, _accept(H2))]))
    assert r.verdict is GateVerdict.INDETERMINATE
    assert r.detail == "no operator-accept on head"


def test_review_on_other_commit_is_indeterminate():
    r = _pred(_runners([_review("curtis", "APPROVED", H2, _accept(H2))]), head=H)
    assert r.verdict is GateVerdict.INDETERMINATE


def test_no_reviews_is_indeterminate():
    assert _pred(_runners([])).verdict is GateVerdict.INDETERMINATE


def test_body_without_accept_line_is_indeterminate():
    r = _pred(_runners([_review("curtis", "APPROVED", H, "looks good to me")]))
    assert r.verdict is GateVerdict.INDETERMINATE


def test_bot_author_never_counts():
    reviews = [
        _review("curtisthebot[bot]", "APPROVED", H, _accept(), rtype="Bot"),
        _review("someapp[bot]", "APPROVED", H, _accept(), rtype="Bot"),
    ]
    assert _pred(_runners(reviews)).verdict is GateVerdict.INDETERMINATE


def test_self_login_is_in_the_automation_set():
    r = _pred(_runners([_review(SELF, "APPROVED", H, _accept())]))
    assert r.verdict is GateVerdict.INDETERMINATE


def test_configured_automation_login_never_counts():
    runners = _runners([_review("ci-service", "APPROVED", H, _accept())])
    r = operator_accept.pred_operator_accept(
        PR, H, runners=runners,
        config={"review": {"automation_identities": ["ci-service"]}},
    )
    assert r.verdict is GateVerdict.INDETERMINATE


def test_commented_review_with_accept_body_is_indeterminate():
    r = _pred(_runners([_review("curtis", "COMMENTED", H, _accept())]))
    assert r.verdict is GateVerdict.INDETERMINATE


def test_changes_requested_with_accept_body_is_indeterminate():
    r = _pred(_runners([_review("curtis", "CHANGES_REQUESTED", H, _accept())]))
    assert r.verdict is GateVerdict.INDETERMINATE


def test_later_commented_review_supersedes_earlier_approved_accept():
    reviews = [
        _review("curtis", "APPROVED", H, _accept(), when="2026-10-01T00:00:00Z"),
        _review("curtis", "COMMENTED", H, "wait, revert that",
                when="2026-10-02T00:00:00Z"),
    ]
    assert _pred(_runners(reviews)).verdict is GateVerdict.INDETERMINATE


def test_latest_review_per_author_across_two_humans():
    reviews = [
        _review("ana", "COMMENTED", H, "needs work", when="2026-10-03T00:00:00Z"),
        _review("bo", "APPROVED", H, _accept(), when="2026-10-02T00:00:00Z"),
    ]
    r = _pred(_runners(reviews))
    assert r.verdict is GateVerdict.PASS
    assert r.detail.startswith("operator-accept by bo on")


def test_login_case_does_not_split_an_author():
    reviews = [
        _review("Curtis", "APPROVED", H, _accept(), when="2026-10-01T00:00:00Z"),
        _review("curtis", "CHANGES_REQUESTED", H, "", when="2026-10-02T00:00:00Z"),
    ]
    assert _pred(_runners(reviews)).verdict is GateVerdict.INDETERMINATE


def test_unresolvable_self_login_fails_closed():
    def boom():
        raise RuntimeError("gh api user failed")

    r = _pred({"self_login_fn": boom, "reviews_fn": lambda url: [
        _review("curtis", "APPROVED", H, _accept())]})
    assert r.verdict is GateVerdict.INDETERMINATE
    empty = _pred({"self_login_fn": lambda: "", "reviews_fn": lambda url: [
        _review("curtis", "APPROVED", H, _accept())]})
    assert empty.verdict is GateVerdict.INDETERMINATE


def test_reviews_fn_raising_is_indeterminate_never_raises():
    def boom(url):
        raise RuntimeError("gh api failed")

    r = _pred({"self_login_fn": lambda: SELF, "reviews_fn": boom})
    assert r.verdict is GateVerdict.INDETERMINATE
    assert r.detail == "no operator-accept on head"


def test_malformed_reviews_are_indeterminate():
    for bad in (None, {"nope": 1}, [{"user": None}]):
        runners = _runners(bad) if not isinstance(bad, dict) else \
            {"self_login_fn": lambda: SELF, "reviews_fn": lambda url: bad}
        assert _pred(runners).verdict is GateVerdict.INDETERMINATE


def test_never_returns_fail_verdict():
    for reviews in ([], [{"user": None}], [
            _review("curtis", "APPROVED", "not-a-sha", "tp-accept: xyz")]):
        r = _pred(_runners(reviews))
        assert r.verdict in (GateVerdict.PASS, GateVerdict.INDETERMINATE)


# ---- CLI: `operator_accept.py check` — exit 0 PASS / 1 not / 2 Gitea ------------


def _tmp_repo(tmp_path, url):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", url],
                   check=True)
    return tmp_path


def test_cli_check_exits_zero_on_accept(monkeypatch, tmp_path, capsys):
    import human_approval

    _tmp_repo(tmp_path, "https://github.com/o/r.git")
    monkeypatch.setattr(human_approval, "_build_live_runners",
                        lambda url: _runners([_review("curtis", "APPROVED", H,
                                                      _accept())]))
    rc = operator_accept.main(["check", "--pr-url", PR, "--head", H,
                               "--repo", str(tmp_path)])
    assert rc == 0
    assert "operator-accept by curtis" in capsys.readouterr().out


def test_cli_check_exits_one_without_accept(monkeypatch, tmp_path):
    _tmp_repo(tmp_path, "https://github.com/o/r.git")
    monkeypatch.setattr(operator_accept, "_build_live_runners",
                        lambda url: _runners([]))
    assert operator_accept.main(["check", "--pr-url", PR, "--head", H,
                                 "--repo", str(tmp_path)]) == 1


def test_cli_check_gitea_exits_two_with_named_line(tmp_path, capsys):
    _tmp_repo(tmp_path, "https://gitea.lan/o/r.git")
    cfg = tmp_path / ".three-pillars"
    cfg.mkdir()
    (cfg / "config.json").write_text('{"forge": {"kind": "gitea"}}',
                                     encoding="utf-8")
    rc = operator_accept.main(["check", "--pr-url", PR, "--head", H,
                               "--repo", str(tmp_path)])
    assert rc == 2
    assert capsys.readouterr().out.strip() == (
        "operator-accept unavailable on gitea (gitea-forge-adapter)")
