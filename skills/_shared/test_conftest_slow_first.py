"""test_conftest_slow_first.py — the repo-root conftest puts an xdist worker's slowest tests first.

design: ci-local-speed-part2 (Task 1.7; Scope 1, Behavior 1)

`skills/_shared/slow_first.py` reads a previous head's junit report. The repo-root
`conftest.py` feeds it to `slow_first.order` in `pytest_collection_modifyitems`, but only in an
xdist worker (`config.workerinput`) and only when `CI_LOCAL_DURATIONS_DIR` names a directory
holding that report. Every worker reads the same file, so all workers collect the same order, as
xdist requires; the controller does not collect and the serial `-n0` pass keeps file order.
No durations dir, a missing or broken report, or no worker input leaves the order unchanged and
raises nothing.

Most tests call the hook directly with a stand-in config. One end-to-end test runs a real probe
pytest with a durations dir written for it and reads the order the worker executed the probe in.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFTEST = REPO_ROOT / "conftest.py"
DURATIONS_ENV = "CI_LOCAL_DURATIONS_DIR"
_PROBE = "test_probe_slow_first_order"
_PROBE_OUT_ENV = "TP_SLOW_FIRST_PROBE_OUT"


@pytest.fixture(scope="module")
def cf():
    """The repo-root conftest.py, loaded under a unique name (not pytest's own import of it)."""
    if not CONFTEST.is_file():  # dev-only: a consumer repo has no repo-root conftest.py
        pytest.skip("no repo-root conftest.py in this tree")
    spec = importlib.util.spec_from_file_location("_slow_first_conftest_probe", CONFTEST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _items():
    return [SimpleNamespace(nodeid=f"a.py::test_{n}") for n in ("first", "second", "third")]


def _worker_config(workercount: int = 1) -> SimpleNamespace:
    return SimpleNamespace(workerinput={"workerid": "gw0", "workercount": workercount})


def _serial_config() -> SimpleNamespace:
    return SimpleNamespace()


def _write_durations(tmp_path: Path, timings: dict[str, float]) -> Path:
    """A `pytest-main.xml` in a fresh dir under `tmp_path` with one testcase per key."""
    d = tmp_path / "durations"
    d.mkdir(exist_ok=True)
    cases = "".join(f'<testcase classname="a" name="test_{name}" time="{s}"/>'
                    for name, s in timings.items())
    (d / "pytest-main.xml").write_text(f'<testsuite>{cases}</testsuite>', encoding="utf-8")
    return d


def _modify(cf, config, items):
    """Run the collection hook, or stand in for its absence (file order)."""
    hook = getattr(cf, "pytest_collection_modifyitems", None)
    if hook is None:  # no hook at all: collection order is file order, by definition
        return None
    return hook(None, config, items)


def _nodeids(items) -> list[str]:
    return [it.nodeid for it in items]


# ---------------------------------------------------------------------------
# the hook: a worker with durations reorders; everything else does not
# ---------------------------------------------------------------------------

def test_a_worker_with_durations_gets_the_slowest_first(cf, tmp_path, monkeypatch):
    d = _write_durations(tmp_path, {"third": 9.0, "first": 1.0})
    monkeypatch.setenv(DURATIONS_ENV, str(d))
    items = _items()
    cf.pytest_collection_modifyitems(None, _worker_config(1), items)
    assert _nodeids(items) == ["a.py::test_third", "a.py::test_first", "a.py::test_second"]


def test_a_serial_pass_keeps_the_input_order(cf, tmp_path, monkeypatch):
    d = _write_durations(tmp_path, {"third": 9.0, "first": 1.0})
    monkeypatch.setenv(DURATIONS_ENV, str(d))
    items = _items()
    assert _modify(cf, _serial_config(), items) is None
    assert _nodeids(items) == ["a.py::test_first", "a.py::test_second", "a.py::test_third"]


@pytest.mark.parametrize("setup", ["unset", "missing", "broken"])
def test_no_variable_a_missing_dir_or_an_unparsable_report_changes_nothing(
        cf, tmp_path, monkeypatch, setup):
    if setup == "unset":
        monkeypatch.delenv(DURATIONS_ENV, raising=False)
        d = None
    elif setup == "missing":
        d = tmp_path / "no-such-dir"
        monkeypatch.setenv(DURATIONS_ENV, str(d))
    else:
        d = tmp_path / "broken"
        d.mkdir()
        (d / "pytest-main.xml").write_text("<testsuite><test", encoding="utf-8")
        monkeypatch.setenv(DURATIONS_ENV, str(d))
    items = _items()
    assert _modify(cf, _worker_config(1), items) is None
    assert _nodeids(items) == ["a.py::test_first", "a.py::test_second", "a.py::test_third"]


def test_a_failing_order_call_keeps_file_order_and_says_so(cf, tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import slow_first
    finally:
        sys.path.remove(str(Path(__file__).resolve().parent))

    def boom(*_a, **_k):
        raise RuntimeError("order exploded")

    monkeypatch.setattr(slow_first, "order", boom)
    monkeypatch.setenv(DURATIONS_ENV, str(_write_durations(tmp_path, {"third": 9.0})))
    items = _items()
    assert _modify(cf, _worker_config(2), items) is None
    assert _nodeids(items) == ["a.py::test_first", "a.py::test_second", "a.py::test_third"]
    assert len(capsys.readouterr().err.strip().splitlines()) == 1


def test_few_known_among_many_new_collects_without_error(cf, tmp_path, monkeypatch):
    d = tmp_path / "durations"
    d.mkdir()
    cases = "".join(f'<testcase classname="a" name="test_k{i}" time="{100 - i}"/>' for i in range(3))
    (d / "pytest-main.xml").write_text(f"<testsuite>{cases}</testsuite>", encoding="utf-8")
    monkeypatch.setenv(DURATIONS_ENV, str(d))
    items = [SimpleNamespace(nodeid=f"a.py::test_k{i}") for i in range(3)]
    items += [SimpleNamespace(nodeid=f"b.py::test_u{i}") for i in range(37)]
    before = sorted(_nodeids(items))
    cf.pytest_collection_modifyitems(None, _worker_config(4), items)
    assert sorted(_nodeids(items)) == before, "the hook lost or duplicated a collected test"


# ---------------------------------------------------------------------------
# end to end: a real probe pytest reads a durations dir written for it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("p", ["p1", "p2", "p3"])
@pytest.mark.skipif(not os.environ.get(_PROBE_OUT_ENV), reason="probe: run by the outer test")
def test_probe_slow_first_order(request, p):
    with open(os.environ[_PROBE_OUT_ENV], "a", encoding="utf-8") as fh:
        fh.write(request.node.nodeid + "\n")


@pytest.mark.skipif(not CONFTEST.is_file(), reason="needs the dev-only repo-root conftest.py")
def test_real_run_deals_the_slowest_probe_first(tmp_path):
    rel = Path(__file__).relative_to(REPO_ROOT)
    probe_ids = [f"{rel}::{_PROBE}[{p}]" for p in ("p1", "p2", "p3")]
    d = tmp_path / "durations"
    d.mkdir()
    cases = "".join(
        f'<testcase classname="{rel.with_suffix("").as_posix().replace("/", ".")}" '
        f'name="{_PROBE}[{p}]" time="{s}"/>'
        for p, s in (("p3", "9.0"), ("p1", "1.0"))  # p2 absent from the report
    )
    (d / "pytest-main.xml").write_text(f"<testsuite>{cases}</testsuite>", encoding="utf-8")
    out = tmp_path / "probe.txt"
    # os.environ is already free of repo-local git vars: the repo-root conftest popped them.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST_XDIST") and k != "PYTEST_ADDOPTS"}
    env.update({DURATIONS_ENV: str(d), _PROBE_OUT_ENV: str(out)})
    r = subprocess.run(
        [sys.executable, "-m", "pytest", f"{rel}::{_PROBE}",
         "-n", "1", "-q", "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "bt")],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert out.is_file(), "the probe never ran (skipped?):\n" + r.stdout[-2000:]
    recorded = out.read_text(encoding="utf-8").splitlines()
    assert recorded == [probe_ids[2], probe_ids[0], probe_ids[1]], recorded
