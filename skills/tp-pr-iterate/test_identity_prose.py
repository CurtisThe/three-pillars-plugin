"""Doc contract: prose names the bot identity (review-proof-ambient-gh-identity 1.8)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))

import skill_text  # noqa: E402

SKILLS = Path(__file__).resolve().parents[1]
FILES = {
    "iterate": SKILLS / "tp-pr-iterate" / "SKILL.md",
    "topology": SKILLS / "tp-pr-iterate" / "round-topology.md",
    "full": SKILLS / "tp-run-full-design" / "SKILL.md",
    "merge": SKILLS / "tp-merge" / "SKILL.md",
}
IDENT = "github.pr_author_account"


def _text(key):
    if key == "full":
        return skill_text.read_skill_text("tp-run-full-design")
    return FILES[key].read_text(encoding="utf-8")


def _block(text, start_marker):
    """The bullet/paragraph beginning at the line containing start_marker."""
    lines = text.splitlines()
    idx = next(i for i, ln in enumerate(lines) if start_marker in ln)
    out = [lines[idx]]
    for ln in lines[idx + 1:]:
        if not ln.strip() or re.match(r"\s*- \*\*", ln):
            break
        out.append(ln)
    return "\n".join(out)


def test_merge_defines_trusted_identity():
    assert IDENT in _block(_text("merge"), "**review_proof_on_head**")


def test_iterate_names_identity():
    assert IDENT in _text("iterate")


def test_full_design_round_tail_names_identity():
    assert IDENT in _block(_text("full"), "**Round tail.**")


def test_topology_names_helper_and_terminals():
    t = _text("topology")
    for needle in ("proof_post.py", "proof-author-untrusted", "bot-auth-unavailable"):
        assert needle in t


def test_migration_line_present():
    assert any("re-run" in _text(k) for k in ("iterate", "topology"))


def test_no_hand_written_gh_token_prefix():
    for key in FILES:
        assert "GH_TOKEN=$(gh auth token" not in _text(key)
