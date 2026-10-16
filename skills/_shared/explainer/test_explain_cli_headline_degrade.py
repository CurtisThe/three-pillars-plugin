"""test_explain_cli_headline_degrade.py — `headline` with no drafted brief (plan Task 11.2, F2).

With the explainer on and no stored envelope, `headline` prints nothing on stdout, exits 0 and
prints one `explainer: ... — see ...` stderr line saying the brief is unavailable, so the PR
body gets no JSON error line. Assertions read lines and exit codes, never pinned markup
(skills/_shared/test-fragility.md).
"""
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_cli  # noqa: E402
from task_scope import _git_env  # noqa: E402 — git_env is dev-only

SLUG = "demo"
_ENV = _git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
_LINE = re.compile(r"^explainer: .+ — see .+$")


def _git(cwd, *args) -> str:
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                          *args], cwd=str(cwd), env=_ENV, check=True, capture_output=True,
                         text=True)
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    (root / "three-pillars-docs" / "tp-designs" / SLUG).mkdir(parents=True)
    return root


def _stderr_lines(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def test_headline_without_brief_degrades_in_process(repo, capsys):
    code = explain_cli.main(["--root", str(repo), "headline", "--slug", SLUG])
    cap = capsys.readouterr()
    assert code == 0
    assert cap.out == ""
    lines = _stderr_lines(cap.err)
    assert len(lines) == 1 and _LINE.match(lines[0])
    assert "brief unavailable" in lines[0]
    rest = "PR body rest"
    assert cap.out + rest == rest


def test_headline_without_brief_degrades_as_subprocess(repo):
    proc = subprocess.run(
        [sys.executable, str(_HERE / "explain_cli.py"), "--root", str(repo),
         "headline", "--slug", SLUG],
        capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout == ""
    lines = _stderr_lines(proc.stderr)
    assert len(lines) == 1 and _LINE.match(lines[0])
    assert "brief unavailable" in lines[0]
