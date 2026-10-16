"""test_consumer_offers_timeouts.py — first-run offer (d): local client
timeouts (m44-orphan-reaper, Phase 5).

Local-model runs need longer client timeouts in the repo's
`.claude/settings.json` `env`; the offer runs the shipped
`local_timeouts.py offer`, shows `plan.diff`, and writes only on a yes
(`apply`), recording a no (`decline`). A known client below the minimum
version gets a notice only; an unknown version still gets the offer.
`--auto` never writes. Pinned by token, not prose (the style of
`test_consumer_offers_handoffs.py`); the version floor and every
`local_timeouts.py <sub>` are read live from the shipped module.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
OFFERS = _SHARED / "consumer-offers.md"
FIRST_RUN = _SHARED / "first-run.md"

CLI = 'python3 "$TP_ROOT"/skills/_shared/local_timeouts.py'


def _offers() -> str:
    return OFFERS.read_text(encoding="utf-8")


def _offer_d() -> str:
    text = _offers()
    start = text.index("## Offer (d)")
    end = text.index("## Enforcer", start)
    return text[start:end]


def _lt():
    sys.path.insert(0, str(_SHARED))
    import local_timeouts

    return local_timeouts


def test_offer_d_heading_sits_after_offer_c_and_before_the_enforcer():
    text = _offers()
    assert "## Offer (d): local client timeouts" in text
    assert text.index("## Offer (c)") < text.index("## Offer (d)") < text.index("## Enforcer")


def test_offer_d_names_every_cli_step():
    body = _offer_d()
    for sub in ("offer", "apply", "decline"):
        assert f"{CLI} {sub}" in body, sub
    assert "--claude-version" in body


def test_offer_d_subs_are_real_cli():
    subs = set(re.findall(r"local_timeouts\.py\s+([a-z][a-z0-9-]*)", _offer_d()))
    assert {"offer", "apply", "decline"} <= subs
    out = subprocess.run([sys.executable, str(_SHARED / "local_timeouts.py"), "--help"],
                         capture_output=True, text=True, check=True).stdout
    m = re.search(r"\{([^{}]+)\}", out)
    assert m, "local_timeouts.py --help: no {a,b,...} subcommand line"
    cli = set(m.group(1).split(","))
    assert subs <= cli, sorted(subs - cli)


def test_offer_d_names_the_offer_json_and_config_record():
    body = _offer_d()
    for token in ("wanted", "settled", "version_ok", "plan.diff", "plan.add",
                  "plan.keep", "plan.creates_file", "local_implement.client_timeouts",
                  "applied_at", "declined", "values"):
        assert token in body, token


def test_offer_d_version_rules():
    body = _offer_d()
    floor = ".".join(map(str, _lt().MIN_CLAUDE_VERSION))
    assert floor in body, floor
    assert "version_ok: false" in body
    assert "nothing recorded" in body
    assert "version_ok: null" in body
    assert "unknown" in body
    assert "still offers" in body


def test_offer_d_shows_the_diff_and_kept_values():
    body = _offer_d()
    assert "plan.diff" in body
    assert "kept, your value" in body
    assert "next Claude Code session" in body


def test_offer_d_names_the_timeout_keys():
    body = _offer_d()
    for key in _lt().TIMEOUTS:
        assert key in body, key


def test_offer_d_yes_commits_settings_with_config():
    body = _offer_d()
    assert ".claude/settings.json" in body
    assert ".three-pillars/config.json" in body
    assert "commit" in body


def test_offer_d_malformed_settings_exits_2_and_writes_nothing():
    body = _offer_d()
    assert "exits 2" in body
    assert "nothing written" in body


def test_offer_d_values_in_place_does_not_prompt():
    body = _offer_d()
    assert "no prompt" in body


def test_offer_d_auto_rule():
    body = _offer_d()
    auto = body[body.index("**`--auto`**"):]
    for token in ("never writes", "[first-run]", "decisions.md", "plan.diff",
                  "logs nothing", "plan.add"):
        assert token in auto, token


def test_offer_d_claims_no_verified_inheritance():
    # D3 (env inheritance) is a live check not yet run: the prose may state
    # the expected behaviour but must not claim it was verified.
    assert "verified" not in _offer_d().lower()


def test_offers_doc_stays_under_soft_cap():
    assert len(_offers().splitlines()) <= 300


def _first_run_line(prefix: str) -> str:
    text = FIRST_RUN.read_text(encoding="utf-8")
    return next(line for line in text.splitlines() if line.startswith(prefix))


def test_first_run_condition_8_names_offer_d():
    # Offer (d) is settled by a config read plus at most one settings read:
    # the hot path never runs `claude --version` (or any subprocess) for it.
    cond8 = _first_run_line("8. **Consumer offers are settled**")
    for token in ("Offer (d)", "local_timeouts.settled", "local_implement.client_timeouts",
                  ".claude/settings.json", "no subprocess"):
        assert token in cond8, token
    routing = _first_run_line("If any condition fails")
    route8 = routing[routing.index("condition 8 failing"):]
    assert "offer (d)" in route8 and "Consumer offers" in route8
    text = FIRST_RUN.read_text(encoding="utf-8")
    section = text[text.index("## Consumer offers"):text.index("## Old-layout detection")]
    assert "Offer (d)" in section


def test_first_run_auto_row_for_offer_d():
    row = _first_run_line("| Local client timeouts")
    for token in ("never writes", ".claude/settings.json", "[first-run]", "plan.diff",
                  "plan.add", "| Medium |"):
        assert token in row, token


def test_local_dispatch_names_timeouts_status():
    # D8: timeout drift is reported by the --local preflight, not on the
    # first-run hot path. Step 1 runs `local_timeouts.py status` and shows its
    # `line` unless the state is `applied` or `not-wanted`.
    text = (_SHARED / "local-dispatch.md").read_text(encoding="utf-8")
    step1 = text[text.index("1. **Permission**:"):text.index("2. **Override warning**")]
    assert "python3 <TP>/skills/_shared/local_timeouts.py status" in step1
    for token in ("`line`", "`applied`", "`not-wanted`"):
        assert token in step1, token
    assert len(text.splitlines()) <= 260



def test_local_dispatch_timeouts_precede_the_cheap_tier_branch():
    # Audit m3: the Timeouts check applies to both branches, so it sits ahead
    # of the `CHEAP_TIER:` branch text, not inside it.
    text = (_SHARED / "local-dispatch.md").read_text(encoding="utf-8")
    step1 = text[text.index("1. **Permission**:"):text.index("2. **Override warning**")]
    assert step1.index("**Timeouts** (both branches)") < step1.index("**`CHEAP_TIER:` branch**")
