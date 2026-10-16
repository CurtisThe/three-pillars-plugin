"""Guard: the `models` config docs + no stray `claude-sonnet-4-6` pins (Task 7.7).

`repo-config.md` names `models.design_run`, `model_policy.py` and `opus[1m]` as
the shipped design-run default; every `fable` mention in it sits inside the `design_run`
rare-exception entry (never a default, never an example). No file under
`skills/` still names the old hardcoded `claude-sonnet-4-6` id — dispatch sites
now read their model from `skills/_shared/model_policy.py`'s roles. `test_*.py`
files are excluded from the token sweep: they use model ids as literal data.
"""
from __future__ import annotations

from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parent.parent  # skills/
REPO_CONFIG_MD = Path(__file__).resolve().parent / "repo-config.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_repo_config_names_models_design_run_and_policy():
    text = _read(REPO_CONFIG_MD)
    assert "models.design_run" in text
    assert "model_policy.py" in text
    assert "opus" in text
    assert "defaults `sonnet[1m]`" in text  # the design_run default (seat ruling 13)


def test_repo_config_fable_confined_to_design_run_entry():
    text = _read(REPO_CONFIG_MD)
    for line in text.splitlines():
        if "fable" in line.lower():
            assert "design_run" in line, (
                "every fable mention in repo-config.md must sit inside the "
                f"design_run rare-exception entry; offending line: {line!r}"
            )


def test_repo_config_no_fenced_block_mentions_fable():
    text = _read(REPO_CONFIG_MD)
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            assert "fable" not in stripped.lower(), (
                "no fenced example config in repo-config.md may set/mention fable"
            )


def _iter_skill_files():
    exts = {".md", ".py", ".json", ".sh"}
    for path in SKILLS_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in exts:
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix == ".py" and path.name.startswith("test_"):
            continue
        yield path


def test_no_claude_sonnet_4_6_token_in_shipped_skills():
    offenders = []
    for path in _iter_skill_files():
        try:
            text = _read(path)
        except UnicodeDecodeError:
            continue
        if "claude-sonnet-4-6" in text:
            offenders.append(str(path.relative_to(SKILLS_ROOT)))
    assert not offenders, f"stale claude-sonnet-4-6 token found in: {offenders}"
