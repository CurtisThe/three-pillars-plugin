"""test_consumer_offers_refs.py — Task 6.4: the shipped consumer-offer + caps docs.

consumer-repo-parity, part E §First-run and §M1.

Pins, by token / path / key (never the surrounding prose):
  * `skills/_shared/consumer-offers.md` — the offer bodies (the gate-command offer
    and the commit-guard offer), every config key and CLI entry point the agent runs
    from Bash, the `.legacy` / `hot-patches.md` placements, and the absence of the
    `fable` token. Every `commit_guard.py <sub>` it names must be a subcommand the
    CLI actually accepts (parsed live from `commit_guard.py --help`).
  * `skills/_shared/file-size-caps.md` — the shipped source of the file-size caps.
    Names its enforcer (`file_size_guard.py`) and `--emit-grandfather`, carries the
    350/500-line and 35,000/50,000-char values, and cites neither `CLAUDE.md` nor a
    `§File Size Limits` token (this doc IS the caps; 9.6's scan must find it clean).
  * `skills/_shared/first-run.md` — the cheap-path now names condition 8, its
    per-clone `commit_guard.py status` check and refusal marker, and links the new
    offers doc. It must stay within 8 added lines (<= 226 total).

Stdlib only; reads only shipped files under `skills/`. The CLI subcommand set is
read live (a one-shot `commit_guard.py --help`), so the pin survives a CLI rename.
Run with: python3 -m pytest skills/_shared/test_consumer_offers_refs.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
FIRST_RUN = _SHARED / "first-run.md"
OFFERS = _SHARED / "consumer-offers.md"
CAPS = _SHARED / "file-size-caps.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _cg_subcommands() -> set:
    """The CLI subcommand set, parsed from `commit_guard.py --help`.

    Reads the argparse `{a,b,...}` positional-choices line and takes the
    braces' inner tokens. Live read, so the pin tracks a renamed CLI."""
    out = subprocess.run(
        [sys.executable, str(_SHARED / "commit_guard.py"), "--help"],
        capture_output=True, text=True, check=True,
    ).stdout
    m = re.search(r"\{([^{}]+)\}", out)
    assert m, "commit_guard.py --help: no {a,b,...} subcommand line"
    return {t for t in m.group(1).split(",") if t.strip()}


# ---------------------------------------------------------------------------
# consumer-offers.md — the offer bodies + every CLI / config entry point
# ---------------------------------------------------------------------------

def test_offers_doc_exists():
    assert OFFERS.exists()


def test_offers_names_the_offer_tokens():
    text = _text(OFFERS)
    for token in (
        "ci.gate_command",
        "ci_gate_run.py",
        "commit_guard.py apply",
        "--file-size",
        "--deny-no-verify",
        "commit_guard.py decline",
        "repo_config_load.py set",
        "commit_guard.declined",
        "commit_guard.offered_at",
        "commit_guard.file_size",
        "commit_guard.deny_no_verify",
        "commit-msg",
        "<hook>.legacy",
        "hot-patches.md",
        "commit-guard-manual",
    ):
        assert token in text, f"consumer-offers.md missing token: {token!r}"


def test_offers_names_no_fable_token():
    assert "fable" not in _text(OFFERS).lower(), (
        "consumer-offers.md must not contain the `fable` token (case-insensitive)")


def test_offers_commit_guard_subs_are_real_cli():
    """Every `commit_guard.py <sub>` it names is a subcommand the CLI accepts."""
    subs = set(re.findall(r"commit_guard\.py\s+([a-z][a-z0-9-]*)", _text(OFFERS)))
    assert subs, "consumer-offers.md: no `commit_guard.py <sub>` references found"
    cli = _cg_subcommands()
    for sub in subs:
        assert sub in cli, (
            f"consumer-offers.md names `commit_guard.py {sub}`, "
            f"which is not an accepted subcommand (CLI has {sorted(cli)})")


# ---------------------------------------------------------------------------
# file-size-caps.md — the shipped source of the caps
# ---------------------------------------------------------------------------

def test_caps_doc_exists():
    assert CAPS.exists()


def test_caps_names_the_enforcer_and_its_flags():
    text = _text(CAPS)
    assert "file_size_guard.py" in text, "file-size-caps.md must name file_size_guard.py"
    assert "--emit-grandfather" in text, "file-size-caps.md must name --emit-grandfather"


def test_caps_carries_the_cap_values():
    text = _text(CAPS)
    for token in ("350", "500", "35,000", "50,000"):
        assert token in text, f"file-size-caps.md missing cap value: {token!r}"


def test_caps_cites_no_claude_md_or_section_token():
    text = _text(CAPS)
    assert "CLAUDE.md" not in text, "file-size-caps.md must not cite CLAUDE.md"
    assert "§" not in text, "file-size-caps.md must not carry a `§` token (it IS the caps)"


# ---------------------------------------------------------------------------
# first-run.md — condition 8 woven into the cheap path
# ---------------------------------------------------------------------------

def test_first_run_under_line_cap():
    assert len(FIRST_RUN.read_text(encoding="utf-8").splitlines()) <= 226, (
        "first-run.md grew past the 8-line budget (<= 226 lines)")


def test_first_run_names_condition_8_and_its_clis():
    text = _text(FIRST_RUN)
    assert re.search(r"^8\. \*\*", text, re.M), "first-run.md cheap path must gain condition 8"
    for token in (
        "consumer-offers.md",
        "commit_guard.py status",
        "commit_guard.py refresh",
        "commit_guard.py record-tp-root",
        "commit-guard-declined",
        "commit-guard-manual",
    ):
        assert token in text, f"first-run.md condition 8 missing token: {token!r}"


def test_first_run_links_the_offers_doc():
    assert "Consumer offers" in _text(FIRST_RUN), (
        "first-run.md must route condition 8 failures to the Consumer offers section")


# ---------------------------------------------------------------------------
# size discipline for the new docs
# ---------------------------------------------------------------------------

def test_new_docs_under_soft_cap():
    for path in (OFFERS, CAPS):
        assert len(_text(path).splitlines()) <= 300, f"{path.name} over the 300-line soft cap"


def test_new_docs_cite_no_dev_repo_only_file():
    """Both docs ship to consumer repos: no dev-repo-only file is cited."""
    for path in (OFFERS, CAPS):
        text = _text(path)
        for token in ("framework-check.sh", ".pre-commit-config.yaml"):
            assert token not in text, f"{path.name} cites dev-repo-only {token!r}"
