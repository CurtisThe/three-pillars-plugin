"""test_pr_iterate_proof_prose.py — the out-of-tree proof root in the prose (1.7).

design: review-proof-out-of-tree (Task 1.7; split from test_pr_iterate_skill_md.py,
which is at the file-size cap)

`round-topology.md` §Path authority names `proof_root.py` and the per-worktree
git-dir location (and no longer calls the root "gitignored"); its round tail
delivers the envelope with `put --slot tail`. Write instructions only: no sentence
in the shipped docs or the confirmer agent definitions pairs a write verb (write,
save, the Write / Edit tool) with a proof-root target (`reply_path`, `reply.md`,
`envelope.json`, `angles.json`, `findings.json`, `R/…`, `<proof_root>`) unless it
names `put`, or its subject is a script (a leading `name.py` / `fn(` code span).
Read instructions are not checked here.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

SKILLS = Path(__file__).resolve().parents[2]
AGENTS = SKILLS.parent / "agents"
TOPOLOGY = SKILLS / "tp-pr-iterate" / "round-topology.md"
RUN_FULL_DESIGN_SKILL = SKILLS / "tp-run-full-design" / "SKILL.md"
DOCS = (TOPOLOGY, SKILLS / "tp-pr-iterate" / "SKILL.md",
        SKILLS / "tp-pr-iterate" / "proof-of-review.md",
        RUN_FULL_DESIGN_SKILL,
        AGENTS / "tp-review-confirmer.md", AGENTS / "tp-review-confirmer-deep.md")
DIRECT_WRITES = ("writes its full reply to its", "Write the full reply",
                 "writes its reply to its own", "Each angle writes only its own",
                 "It writes `R/tail/envelope.json`", "writes `R/tail/envelope.json`")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n\s*\n|\n\s*(?:[-*]|\d+\.|\|)\s|\n#+\s")
# A verb, not a slash-list of tool names ("Read/Write/Edit" names tools, it instructs nothing).
_WRITE = re.compile(r"(?<![/\w])(?:writ(?:e|es|ing|ten)|wrote|sav(?:e|es|ed|ing))(?![/\w])"
                    r"|\b(?:Write|Edit) tool\b", re.IGNORECASE)
_TARGET = re.compile(r"reply_path|reply\.md|envelope\.json|angles\.json|findings\.json"
                     r"|<proof_root>|(?<![\w/.])R/|review-proof/")
_PUT = re.compile(r"\bput\b")
_SCRIPT_SUBJECT = re.compile(r"^[\W_]*`[^`]*(?:\.py\b|\()")

PARAPHRASES = (  # each must be flagged
    "Each angle saves its whole reply straight to its `reply_path` with the Write tool.",
    "Write the full reply to `R/<angle>/reply.md`.",
    "It writes `R/tail/envelope.json` and returns it.",
    "The tail saves the envelope under `<proof_root>/rounds/<pr>/` using the Edit tool.",
    "Then, with the Edit tool, fill in `angles.json`.",
)
ALLOWED = (  # each must pass
    "Each pipes its full reply into its prompt's `put` command (it lands at its `reply_path`).",
    "`round_scratch.py prepare` writes them into each round's `angles.json` manifest.",
    "`reproduce.py` writes `R/tail/findings.json` and appends note lines.",
    "Scripts do all proof-root I/O: nobody uses a file tool (Read/Write/Edit) on a path.",
    "The orchestrator reads `R/angles.json` through Bash, never the Read tool.",
)


def direct_write_sentences(text: str) -> "list[str]":
    """Sentences of `text` that tell a writer to put a proof-root file there itself."""
    out = []
    for raw in _SENTENCE.split(text):
        s = " ".join(raw.split())
        if _WRITE.search(s) and _TARGET.search(s) and not _PUT.search(s) \
                and not _SCRIPT_SUBJECT.search(s):
            out.append(s)
    return out


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def _read(path: Path) -> str:
    if path == RUN_FULL_DESIGN_SKILL:
        return skill_text.read_skill_text("tp-run-full-design")
    return path.read_text(encoding="utf-8")


def test_path_authority_names_the_resolver_and_the_git_dir():
    auth = _section(TOPOLOGY.read_text(encoding="utf-8"), "## Path authority")
    assert "proof_root.py" in auth and "git-dir" in auth
    assert "outside the working tree" in auth
    assert "gitignored" not in auth
    reads = " ".join(auth.split())
    assert "reads `R/angles.json`" in reads and "`R/tail/findings.json` through Bash" in reads
    assert "never the Read tool" in reads


def test_round_tail_delivers_the_envelope_through_put():
    one_round = _section(TOPOLOGY.read_text(encoding="utf-8"), "## One round")
    assert "put --slot tail" in one_round
    assert "round_scratch.py put" in one_round


def test_no_write_instruction_names_a_proof_root_target_without_put():
    for doc in DOCS:
        text = _read(doc)
        hits = [p for p in DIRECT_WRITES if p in text] + direct_write_sentences(text)
        assert not hits, f"{doc.name}: direct proof-root write instruction {hits}"


@pytest.mark.parametrize("sentence", PARAPHRASES)
def test_write_guard_flags_a_paraphrased_direct_write(sentence):
    assert direct_write_sentences(f"Intro line.\n\n{sentence} Next one.\n") == [sentence]


@pytest.mark.parametrize("sentence", ALLOWED)
def test_write_guard_passes_put_script_and_read_sentences(sentence):
    assert direct_write_sentences(sentence) == []


def test_proof_doc_artifact_layout_is_the_out_of_tree_root():
    text = (SKILLS / "tp-pr-iterate" / "proof-of-review.md").read_text(encoding="utf-8")
    layout = _section(text, "## Artifact layout")
    assert "<proof_root>" in layout and "git-dir" in layout and "gitignored" not in layout
