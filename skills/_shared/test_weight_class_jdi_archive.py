"""The just-do-it bullet of weight-class.md archives before the merge OK."""

from pathlib import Path

WEIGHT_CLASS = Path(__file__).resolve().parent / "weight-class.md"


def _jdi_bullet() -> str:
    lines = WEIGHT_CLASS.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("- `just-do-it`"))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("- `")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_jdi_stop_path_archives_before_merge_ok() -> None:
    bullet = _jdi_bullet()
    assert "/tp-design-complete" in bullet
    assert "merge OK" in bullet
    assert bullet.index("/tp-design-complete") < bullet.index("merge OK")
