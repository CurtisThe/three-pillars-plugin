"""Tests for finalizer's structural-rewrite hint and the topology pipe.

design: review-convergence (Task 2.4, detailed-design-pr-loop §B)

A round-cap stop that carries `mix` (attached by `round_mix.attach`) tells the
finalizer *why* the loop is stuck, so the brief must carry the §B hint and name
the area to rewrite — and `round-topology.md` step 4 must pipe the stop through
`round_mix.py attach` before handing it to `finalizer_cli.py prepare --stop`.
A stop with no `mix` (or an unknown mix signal) leaves the brief byte-identical.
Oracle: example — exact hint text, exact area, asserted order in the doc.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
_SCRIPTS = Path(__file__).resolve().parents[1] / "tp-pr-iterate" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import finalizer as fin  # noqa: E402
import round_mix  # noqa: E402

T = 1_800_000_000.0
URL = "https://github.com/acme/widgets/pull/42"
TOPOLOGY = Path(__file__).resolve().parents[2] / "skills" / "tp-pr-iterate" / "round-topology.md"
HINT = ("Rewrite the named area as one change; any size is allowed (ruling 2). "
        "Resolved = the rewrite is committed and the loop runs a delta round on it.")


class FakeResolve:
    def __call__(self, agent):
        return f"three-pillars:{agent}"


def _stop(signal="round-cap", target=URL, **extra):
    return {"source": "pr-iterate", "signal": signal, "target": target,
            "head": "abc123", "detail": {"measured": 8, "limit": 6}, **extra}


def _brief(tmp_path, name, stop):
    """One dispatch's brief, each call on its own fresh ledger path.

    ``decisions_path`` is pinned so two briefs differ only in what the stop says.
    """
    out = fin.prepare(stop, tmp_path / name / "finalizer-ledger.json", resolve_fn=FakeResolve(),
                      now=T, decisions_path=tmp_path / "decisions.md", repo_root=tmp_path)
    assert out["status"] == "dispatch"
    return out["brief"]


def _step4(text):
    """Step 4 of the round topology, up to its blank line or the next heading."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("4. **Orchestrator.**"))
    out = []
    for line in lines[start:]:
        if not line.strip() or line.startswith("##"):
            break
        out.append(line)
    return "\n".join(out)


def _regression(file):
    return {"source": "code-review", "file": file, "line_range": [1, 1], "summary": "s",
            "verdict": "structural", "blocking": True, "origin": "regression"}


def _rounds(tmp_path):
    """A two-round fixture: each round's blockers are 2 regressions in `pkg/x`."""
    root = tmp_path / "rounds"
    for name, files in (("r1", ("pkg/x/a.py", "pkg/x/b.py")),
                        ("r2", ("pkg/x/a.py", "pkg/x/c.py"))):
        tail = root / name / "tail"
        tail.mkdir(parents=True, exist_ok=True)
        (tail / "findings.json").write_text(
            json.dumps([_regression(f) for f in files]), encoding="utf-8")
    return root


# --- the mix hint in the brief ------------------------------------------------

def test_mix_put_the_hint_and_the_area_in_the_brief(tmp_path):
    stop = _stop(mix={"signal": "structural-rewrite", "area": "pkg/x"})
    brief = _brief(tmp_path, "a", stop)
    assert HINT in brief, f"brief holds no structural-rewrite hint:\n{brief}"
    lines = [line for line in brief.splitlines() if HINT in line]
    assert len(lines) == 1
    assert "pkg/x" in lines[0]


def test_a_mix_without_an_area_names_the_default_area(tmp_path):
    brief = _brief(tmp_path, "b", _stop(mix={"signal": "structural-rewrite"}))
    assert HINT in brief
    assert [line for line in brief.splitlines() if HINT in line][0].startswith(
        "Structural-rewrite signal for area `.`:")


def test_no_mix_leaves_the_brief_without_the_hint(tmp_path):
    assert "Rewrite the named area" not in _brief(tmp_path, "c", _stop())


def test_an_unknown_mix_signal_leaves_the_brief_byte_identical(tmp_path):
    plain = _brief(tmp_path, "d", _stop())
    mixed = _brief(tmp_path, "e", _stop(mix={"signal": "mystery", "area": "pkg/x"}))
    assert mixed == plain


# --- round-topology.md step 4 pipes the stop through attach -------------------

def test_step4_attaches_the_mix_before_the_finalizer_prepare():
    step = _step4(TOPOLOGY.read_text(encoding="utf-8"))
    assert "round_mix.py attach" in step, f"step 4 never pipes the stop through attach:\n{step}"
    assert "finalizer_cli.py prepare" in step
    assert step.index("round_mix.py attach") < step.index("finalizer_cli.py prepare")


def test_step4_attach_names_the_stop_file_and_the_rounds_dir():
    step = _step4(TOPOLOGY.read_text(encoding="utf-8"))
    attach = step[step.index("round_mix.py attach"):step.index("finalizer_cli.py prepare")]
    assert "--stop-file" in attach and "--rounds-dir" in attach
    assert "--stop" in step[step.index("finalizer_cli.py prepare"):]


# --- composition: attach's output fed to prepare ------------------------------

def test_attach_over_a_two_round_fixture_gives_a_brief_with_the_hint_and_the_area(tmp_path):
    stop = round_mix.attach(_stop(), _rounds(tmp_path))
    assert "mix" in stop
    area = stop["mix"]["area"]
    assert area == "pkg/x"
    brief = _brief(tmp_path, "f", stop)
    assert HINT in brief and area in brief


def test_a_round_cap_stop_with_no_mix_gives_a_brief_with_no_hint(tmp_path):
    root = tmp_path / "rounds"
    (root / "r1" / "tail").mkdir(parents=True)
    (root / "r1" / "tail" / "findings.json").write_text(
        json.dumps([_regression("pkg/x/a.py"), _regression("pkg/x/b.py")]), encoding="utf-8")
    stop = round_mix.attach(_stop(), root)
    assert "mix" not in stop
    assert "Rewrite the named area" not in _brief(tmp_path, "g", stop)
