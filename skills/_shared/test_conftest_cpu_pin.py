"""test_conftest_cpu_pin.py — the repo-root conftest pins pytest to the launcher's cores.

design: run-tooling-footguns (Task 1.1; Trap 1)

The launcher exports `CLAUDE_LAUNCHER_HARNESS_CPUS` (a cpu list such as `4-7,12-15`) to design runs.
The repo-root `conftest.py` reads it in `pytest_configure`, calls `os.sched_setaffinity(0, cpus)` in
the xdist controller and in each worker, and caps the xdist worker count at the pinned core count.
Unset, empty, malformed, a missing `sched_setaffinity` or a refused call is "no pin": the run goes
ahead as before and prints at most one warning line.

Most tests call the pure parse/cap/apply functions with an injected `setaffinity`, so this test
session is never pinned. One end-to-end test runs a real probe pytest, pinned to two of the cores the
session already holds, and reads what each worker saw.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFTEST = REPO_ROOT / "conftest.py"
ENV = "CLAUDE_LAUNCHER_HARNESS_CPUS"
_PROBE = "test_probe_pin_state"
_PROBE_OUT_ENV = "TP_CPU_PIN_PROBE_OUT"


@pytest.fixture(scope="module")
def cf():
    """The repo-root conftest.py, loaded under a unique name (not pytest's own import of it)."""
    if not CONFTEST.is_file():  # dev-only: a consumer repo has no repo-root conftest.py
        pytest.skip("no repo-root conftest.py in this tree")
    spec = importlib.util.spec_from_file_location("_cpu_pin_conftest_probe", CONFTEST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Recorder:
    """A stand-in for os.sched_setaffinity that records its calls."""

    def __init__(self, error: Exception | None = None):
        self.calls: list[tuple[int, frozenset[int]]] = []
        self.error = error

    def __call__(self, pid, cpus):
        if self.error is not None:
            raise self.error
        self.calls.append((pid, frozenset(cpus)))


def _config(workers: int = 8, *, worker: bool = False) -> SimpleNamespace:
    cfg = SimpleNamespace(option=SimpleNamespace(tx=["popen"] * workers, numprocesses=workers))
    if worker:
        cfg.workerinput = {"workerid": "gw0"}
    return cfg


# ---------------------------------------------------------------------------
# parse: the cpu list
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("4-7", {4, 5, 6, 7}),
    ("5", {5}),
    (" 3 ", {3}),
    ("0,2-3", {0, 2, 3}),
    ("4-7,12-15,20-23,28-31", {4, 5, 6, 7, 12, 13, 14, 15, 20, 21, 22, 23, 28, 29, 30, 31}),
    ("4-5,5-6", {4, 5, 6}),
])
def test_valid_cpu_list_parses_to_those_cores(cf, raw, expected):
    cpus, warning = cf.parse_cpu_pin(raw)
    assert cpus == frozenset(expected)
    assert warning is None


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_or_empty_is_no_pin_and_silent(cf, raw):
    assert cf.parse_cpu_pin(raw) == (None, None)


@pytest.mark.parametrize("raw", [
    "abc", "7-4", "4-", "-3", "1,,2", "4-7,x", "1.5", "4--7", "-1", "0x4",
    "0-99999999999", "99999999999999999999",
])
def test_malformed_is_no_pin_with_exactly_one_warning_line(cf, raw):
    cpus, warning = cf.parse_cpu_pin(raw)
    assert cpus is None
    assert isinstance(warning, str) and warning.strip() and "\n" not in warning


# ---------------------------------------------------------------------------
# cap: the worker count never exceeds the pinned core count
# ---------------------------------------------------------------------------

def test_worker_count_is_capped_at_four_for_cores_4_to_7(cf):
    cpus, _ = cf.parse_cpu_pin("4-7")
    assert cf.cap_workers(8, cpus) == 4


@pytest.mark.parametrize("requested, pinned", [(8, 4), (4, 4), (2, 4), (1, 16), (32, 1)])
def test_cap_never_exceeds_the_pin_or_the_request(cf, requested, pinned):
    assert cf.cap_workers(requested, frozenset(range(pinned))) == min(requested, pinned)


def test_no_pin_leaves_the_worker_count_alone(cf):
    assert cf.cap_workers(8, None) == 8


# ---------------------------------------------------------------------------
# apply: the affinity call sits behind the pure functions
# ---------------------------------------------------------------------------

def test_apply_pins_the_process_to_the_parsed_cores(cf):
    rec = _Recorder()
    cpus, warning = cf.apply_cpu_pin({ENV: "4-7"}, rec)
    assert cpus == frozenset({4, 5, 6, 7}) and warning is None
    assert rec.calls == [(0, frozenset({4, 5, 6, 7}))]


@pytest.mark.parametrize("value", [None, "", "not-a-list"])
def test_apply_with_unset_empty_or_malformed_never_calls_affinity(cf, value):
    rec = _Recorder()
    env = {} if value is None else {ENV: value}
    cpus, warning = cf.apply_cpu_pin(env, rec)
    assert cpus is None and rec.calls == []
    assert warning is None or "\n" not in warning


def test_apply_without_sched_setaffinity_is_no_pin_with_one_warning(cf):
    cpus, warning = cf.apply_cpu_pin({ENV: "4-7"}, None)
    assert cpus is None
    assert isinstance(warning, str) and "\n" not in warning


@pytest.mark.parametrize("error", [OSError(22, "Invalid argument"), ValueError("bad mask"), PermissionError()])
def test_apply_with_a_refused_call_is_no_pin_with_one_warning(cf, error):
    cpus, warning = cf.apply_cpu_pin({ENV: "4-7"}, _Recorder(error))
    assert cpus is None
    assert isinstance(warning, str) and "\n" not in warning


# ---------------------------------------------------------------------------
# pytest_configure: controller and worker
# ---------------------------------------------------------------------------

def test_controller_pins_and_caps_the_xdist_worker_list(cf, monkeypatch, capsys):
    rec = _Recorder()
    monkeypatch.setattr(os, "sched_setaffinity", rec)
    monkeypatch.setenv(ENV, "4-7")
    cfg = _config(8)
    cf.pytest_configure(cfg)
    assert rec.calls == [(0, frozenset({4, 5, 6, 7}))]
    assert cfg.option.tx == ["popen"] * 4
    assert cfg.option.numprocesses == 4
    assert capsys.readouterr().err == ""


def test_a_small_request_is_not_raised_to_the_pinned_count(cf, monkeypatch):
    monkeypatch.setattr(os, "sched_setaffinity", _Recorder())
    monkeypatch.setenv(ENV, "4-7")
    cfg = _config(2)
    cf.pytest_configure(cfg)
    assert cfg.option.tx == ["popen"] * 2 and cfg.option.numprocesses == 2


def test_each_worker_pins_itself_and_leaves_the_worker_list_alone(cf, monkeypatch, capsys):
    rec = _Recorder()
    monkeypatch.setattr(os, "sched_setaffinity", rec)
    monkeypatch.setenv(ENV, "4-7")
    cfg = _config(8, worker=True)
    cf.pytest_configure(cfg)
    assert rec.calls == [(0, frozenset({4, 5, 6, 7}))]
    assert cfg.option.tx == ["popen"] * 8
    assert capsys.readouterr().err == ""


def test_configure_without_the_variable_changes_nothing(cf, monkeypatch, capsys):
    rec = _Recorder()
    monkeypatch.setattr(os, "sched_setaffinity", rec)
    monkeypatch.delenv(ENV, raising=False)
    cfg = _config(8)
    cf.pytest_configure(cfg)
    assert rec.calls == [] and cfg.option.tx == ["popen"] * 8 and cfg.option.numprocesses == 8
    assert capsys.readouterr().err == ""


def test_configure_works_when_xdist_options_are_absent(cf, monkeypatch):
    monkeypatch.setattr(os, "sched_setaffinity", _Recorder())
    monkeypatch.setenv(ENV, "4-7")
    cf.pytest_configure(SimpleNamespace(option=SimpleNamespace()))


@pytest.mark.parametrize("setup", ["malformed", "missing", "refused"])
def test_configure_failure_to_pin_prints_one_line_in_the_controller_only(cf, monkeypatch, capsys, setup):
    monkeypatch.setenv(ENV, "nonsense" if setup == "malformed" else "4-7")
    if setup == "missing":
        monkeypatch.delattr(os, "sched_setaffinity")
    else:
        monkeypatch.setattr(os, "sched_setaffinity", _Recorder(OSError(22, "Invalid argument")))
    cfg = _config(8)
    cf.pytest_configure(cfg)
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1
    assert cfg.option.tx == ["popen"] * 8 and cfg.option.numprocesses == 8
    cf.pytest_configure(_config(8, worker=True))
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# end to end: a real probe pytest, pinned to two of the cores this session holds
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.environ.get(_PROBE_OUT_ENV), reason="probe: run by the outer test")
def test_probe_pin_state(request):
    info = getattr(request.config, "workerinput", {})
    record = {"workerid": info.get("workerid"), "workercount": info.get("workercount"),
              "affinity": sorted(os.sched_getaffinity(0))}
    with open(os.environ[_PROBE_OUT_ENV], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


@pytest.mark.skipif(not hasattr(os, "sched_getaffinity") or not CONFTEST.is_file(),
                    reason="needs CPU affinity and the dev-only repo-root conftest.py")
def test_real_run_pins_every_worker_and_caps_the_worker_count(tmp_path):
    held = sorted(os.sched_getaffinity(0))
    if len(held) < 3:
        pytest.skip("needs at least three cores to pin two of them")
    pinned = held[:2]
    out = tmp_path / "probe.jsonl"
    # os.environ is already free of repo-local git vars: the repo-root conftest popped them.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST_XDIST") and k != "PYTEST_ADDOPTS"}
    env.update({ENV: ",".join(str(c) for c in pinned), _PROBE_OUT_ENV: str(out)})
    r = subprocess.run(
        [sys.executable, "-m", "pytest", f"{Path(__file__).relative_to(REPO_ROOT)}::{_PROBE}",
         "-n", "4", "-q", "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "bt")],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert out.is_file(), "the probe never ran (skipped?):\n" + r.stdout[-2000:]
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert records, r.stdout[-2000:]
    assert all(rec["affinity"] == pinned for rec in records), records
    assert all(rec["workercount"] == len(pinned) for rec in records), records
