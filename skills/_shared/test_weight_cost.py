"""Tests for weight_cost.cost_table (design weight-class-lean-default, Task 1.3)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import weight_cost  # noqa: E402
import weight_class  # noqa: E402


def _design(root, name, klass, cache_line=None):
    d = root / "three-pillars-docs" / "completed-tp-designs" / name
    d.mkdir(parents=True)
    (d / "design.md").write_text(f"---\nweight-class: {klass}\n---\n# {name}\n")
    body = "# decisions\n"
    if cache_line:
        body += cache_line + "\n"
    (d / "decisions.md").write_text(body)


def _line(read, write):
    return (f"[cache] orchestrator turns=5 read={read}M write={write}M "
            f"gaps>300s=0 gap_write=0.00M; w turns=1 read=1.00M write=0.50M "
            f"gaps>300s=0 gap_write=0.00M")


def _rows(text):
    return {ln.split()[0]: ln for ln in text.splitlines() if ln.strip()}


def test_median_of_three_measured(tmp_path):
    # sums: 10+2+1.5=13.5 ; 20+4+1.5=25.5 ; 30+6+1.5=37.5 -> median 25.5
    for i, (r, w) in enumerate([(10, 2), (20, 4), (30, 6)]):
        _design(tmp_path, f"d{i}", "light", _line(f"{r:.2f}", f"{w:.2f}"))
    rows = _rows(weight_cost.cost_table(tmp_path))
    assert "25.5" in rows["light"]
    assert "measured n=3" in rows["light"]


def test_fewer_than_three_falls_back_to_estimate(tmp_path):
    for i in range(2):
        _design(tmp_path, f"d{i}", "full", _line("10.00", "1.00"))
    rows = _rows(weight_cost.cost_table(tmp_path))
    assert "estimate" in rows["full"]
    assert "measured" not in rows["full"]


def test_designs_without_cache_line_not_counted(tmp_path):
    for i in range(3):
        _design(tmp_path, f"d{i}", "just-do-it")
    rows = _rows(weight_cost.cost_table(tmp_path))
    assert "estimate" in rows["just-do-it"]


def test_empty_repo_prints_static_table(tmp_path):
    out = weight_cost.cost_table(tmp_path)
    rows = _rows(out)
    assert set(rows) == {"just-do-it", "light", "full", "spike"}
    for k in ("just-do-it", "light", "full"):
        assert "estimate" in rows[k] and "Mtok" in rows[k]
    assert "no figure (experiment)" in rows["spike"]


def test_cli_cost_prints_table(tmp_path, capsys):
    rc = weight_class.main(["cost", "--root", str(tmp_path)])
    assert rc == 0
    assert "no figure (experiment)" in capsys.readouterr().out
