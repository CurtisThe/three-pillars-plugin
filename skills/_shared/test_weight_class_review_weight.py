"""weight_class.read_review_weight — the review-weight key (review-convergence 5.1).

pr-loop §D5: a frontmatter ``review-weight`` in ``VALID_CLASSES`` wins; anything
else (missing key, unknown value, no design.md) falls back to ``read_class``.
The ``review-weight`` CLI subcommand prints just the weight, because callers
pass it straight to ``round_scratch.py prepare --review-weight``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from weight_class import main, read_review_weight  # noqa: E402


def _design(tmp_path, text):
    d = tmp_path / "some-design"
    d.mkdir()
    if text is not None:
        (d / "design.md").write_text(text, encoding="utf-8")
    return d


def test_review_weight_key_wins_over_weight_class(tmp_path):
    d = _design(tmp_path, "---\nweight-class: full\nreview-weight: light\n---\n# D\n")
    assert read_review_weight(d) == ("light", "review-weight")


def test_review_weight_missing_falls_back_to_weight_class(tmp_path):
    d = _design(tmp_path, "---\nweight-class: light\n---\n# D\n")
    assert read_review_weight(d) == ("light", "frontmatter")


def test_review_weight_bad_value_falls_back_to_weight_class(tmp_path):
    d = _design(tmp_path, "---\nweight-class: light\nreview-weight: bogus\n---\n# D\n")
    assert read_review_weight(d) == ("light", "frontmatter")


def test_review_weight_no_weight_class_fails_safe(tmp_path):
    d = _design(tmp_path, "---\nstatus: draft\n---\n# D\n")
    assert read_review_weight(d) == ("full", "default")


def test_review_weight_no_design_md_fails_safe(tmp_path):
    assert read_review_weight(_design(tmp_path, None)) == ("full", "default")


def test_cli_review_weight_prints_just_the_weight(tmp_path, capsys):
    d = _design(tmp_path, "---\nweight-class: full\nreview-weight: light\n---\n# D\n")
    rc = main(["review-weight", str(d)])
    # tp-allow-fragile: weight_class.py's main() is the printer under test; its stdout is its contract
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "light"


def test_cli_review_weight_prints_the_fallback(tmp_path, capsys):
    d = _design(tmp_path, "---\nweight-class: light\n---\n# D\n")
    rc = main(["review-weight", str(d)])
    # tp-allow-fragile: weight_class.py's main() is the printer under test; its stdout is its contract
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "light"
