"""Task 2.6: the Copilot head-delta check exempts the archived round-log files."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_readiness as rr  # noqa: E402
import round_log_carry  # noqa: E402

ARCH = "three-pillars-docs/completed-tp-designs"


def test_round_log_names_exempt():
    for name in ("decisions.md", "dispatch-telemetry.ndjson", "escape-ledger.ndjson"):
        assert rr._is_exempt_path(f"{ARCH}/demo/{name}") is True


def test_other_paths_not_exempt():
    for p in (
        f"{ARCH}/demo/design.md",
        f"{ARCH}/decisions.md",
        f"{ARCH}/a/b/decisions.md",
        "skills/x.py",
    ):
        assert rr._is_exempt_path(p) is False, p


def _git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
    )
    r = subprocess.run(
        ["git", *args], cwd=root, env=env, capture_output=True, text=True, check=True
    )
    return r.stdout.strip()


def _commit(root, files):
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a") as fh:
            fh.write(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "c")
    return _git(root, "rev-parse", "HEAD")


def test_log_commit_delta_is_exempt(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    log = f"{ARCH}/demo/decisions.md"
    h = _commit(tmp_path, {log: "a\n"})
    log_only = _commit(tmp_path, {log: "b\n"})
    mixed = _commit(tmp_path, {log: "c\n", "skills/x.py": "x=1\n"})
    monkeypatch.chdir(tmp_path)
    assert rr.review_exempt_delta(h, log_only) is True
    assert rr.review_exempt_delta(log_only, mixed) is False


def test_names_match_round_log_carry():
    assert rr._ROUND_LOG_NAMES == round_log_carry.ROUND_LOG_NAMES


RUL = "three-pillars-docs/escalations/rulings"


def test_ruling_file_exempt():
    assert rr._is_exempt_path(f"{RUL}/demo-20261011-abcdef.md") is True


def test_ruling_lookalikes_not_exempt():
    for p in (
        f"{RUL}/seat-20261011-abcdef.md",          # a seat ruling is nobody's design
        f"{RUL}/Demo-20261011-abcdef.md",          # non-ID_RE name
        f"{RUL}/demo-20261011-abcdef.txt",         # wrong suffix
        f"{RUL}/sub/demo-20261011-abcdef.md",      # nested path
        "three-pillars-docs/tp-designs/demo-20261011-abcdef.md",  # ruling shape, wrong dir
    ):
        assert rr._is_exempt_path(p) is False, p


def test_log_plus_ruling_delta_is_exempt(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    log = f"{ARCH}/demo/decisions.md"
    ruling = f"{RUL}/demo-20261011-abcdef.md"
    h = _commit(tmp_path, {log: "a\n"})
    flush = _commit(tmp_path, {log: "b\n", ruling: "r\n"})
    mixed = _commit(tmp_path, {ruling: "r2\n", "skills/x.py": "x=1\n"})
    monkeypatch.chdir(tmp_path)
    assert rr.review_exempt_delta(h, flush) is True
    assert rr.review_exempt_delta(flush, mixed) is False
