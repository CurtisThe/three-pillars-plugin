"""cert_once should-run: a light design that is not a safety gate skips the certifier.

design: light-run-ceremony-diet 1.2 (B1). Examples come from the design's scope
list, not from the implementation (skills/_shared/test-fragility.md): with
`--light` at Slot 8 the certifier runs only for a design that declares
`safety-gate: true` or whose diff touches a gate path, and runs once. Without
`--light` the behaviour is exactly today's (the full-path guard).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cert_once  # noqa: E402

GATE_DECLARED = "---\nweight-class: light\nsafety-gate: true\n---\n\n# design\n"
PLAIN_LIGHT = "---\nweight-class: light\n---\n\n# design\n"


def _design(tmp_path, text=PLAIN_LIGHT):
    d = tmp_path / "design"
    d.mkdir()
    (d / "design.md").write_text(text, encoding="utf-8")
    return d


def _git(repo, *args):
    cmd = ["git", "-C", str(repo), "-c", "commit.gpgsign=false",
           "-c", "core.hooksPath=/dev/null", "-c", "user.name=t",
           "-c", "user.email=t@example.com", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def _repo_with_change(tmp_path, changed_file):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    target = repo / changed_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", changed_file)
    _git(repo, "commit", "-q", "-m", "change")
    return repo, base


def _cli(d, repo, base, *extra):
    return ["should-run", "--design-dir", str(d), "--light",
            "--base", base, "--head", "HEAD", "--repo", str(repo), *extra]


# (a) function


def test_light_non_gate_diff_skips(tmp_path):
    d = _design(tmp_path)
    assert cert_once.should_run(d, 8, light=True, changed=["src/app.py"]) is False


def test_light_gate_path_diff_runs(tmp_path):
    d = _design(tmp_path)
    assert cert_once.should_run(
        d, 8, light=True, changed=["skills/_shared/delete_fence_py.py"]) is True
    assert cert_once.should_run(
        d, 8, light=True, changed=["skills/_shared/deterministic_gate.py"]) is True


def test_light_declared_gate_runs_once(tmp_path):
    d = _design(tmp_path, GATE_DECLARED)
    assert cert_once.should_run(d, 8, light=True, changed=["src/app.py"]) is True
    cert_once.mark(d)
    assert cert_once.should_run(d, 8, light=True, changed=["src/app.py"]) is False


def test_light_gate_path_diff_runs_once(tmp_path):
    d = _design(tmp_path)
    changed = ["skills/_shared/deterministic_gate.py"]
    assert cert_once.should_run(d, 8, light=True, changed=changed) is True
    cert_once.mark(d)
    assert cert_once.should_run(d, 8, light=True, changed=changed) is False


# (b) CLI on a tmp git repo


def test_cli_light_non_gate_diff_skips_with_reason(tmp_path, capsys):
    d = _design(tmp_path)
    repo, base = _repo_with_change(tmp_path, "src/app.py")
    code = cert_once.main(_cli(d, repo, base))
    assert code == 1
    assert capsys.readouterr().out == "should-run: skip (not a safety gate)\n"


def test_cli_light_gate_diff_runs_then_skips_after_mark(tmp_path, capsys):
    d = _design(tmp_path)
    repo, base = _repo_with_change(tmp_path, "skills/_shared/deterministic_gate.py")
    assert cert_once.main(_cli(d, repo, base)) == 0
    assert capsys.readouterr().out == "should-run: run\n"
    cert_once.mark(d)
    assert cert_once.main(_cli(d, repo, base)) == 1
    assert capsys.readouterr().out == "should-run: skip\n"


def test_cli_light_unreadable_diff_runs(tmp_path):
    d = _design(tmp_path)
    repo, _ = _repo_with_change(tmp_path, "src/app.py")
    code = cert_once.main(_cli(d, repo, "no-such-ref"))
    assert code == 0


def test_cli_light_without_base_exits_two_unless_declared(tmp_path):
    plain = _design(tmp_path)
    assert cert_once.main(["should-run", "--design-dir", str(plain), "--light"]) == 2
    declared = tmp_path / "declared"
    declared.mkdir()
    (declared / "design.md").write_text(GATE_DECLARED, encoding="utf-8")
    assert cert_once.main(["should-run", "--design-dir", str(declared), "--light"]) == 0


# (c) full-path guard: no --light, today's exit codes and stdout byte for byte


def test_full_path_fresh_dir_runs_exact_stdout(tmp_path, capsys):
    for text in (None, PLAIN_LIGHT, GATE_DECLARED):
        d = tmp_path / ("d%d" % len(list(tmp_path.iterdir())))
        d.mkdir()
        if text is not None:
            (d / "design.md").write_text(text, encoding="utf-8")
        assert cert_once.main(["should-run", "--design-dir", str(d)]) == 0
        assert capsys.readouterr().out == "should-run: run\n"


def test_full_path_marked_dir_skips_exact_stdout(tmp_path, capsys):
    for text in (None, PLAIN_LIGHT, GATE_DECLARED):
        d = tmp_path / ("m%d" % len(list(tmp_path.iterdir())))
        d.mkdir()
        if text is not None:
            (d / "design.md").write_text(text, encoding="utf-8")
        cert_once.mark(d)
        assert cert_once.main(["should-run", "--design-dir", str(d)]) == 1
        assert capsys.readouterr().out == "should-run: skip\n"


def test_slot4_light_still_skips_without_base(tmp_path, capsys):
    d = _design(tmp_path, GATE_DECLARED)
    code = cert_once.main(["should-run", "--design-dir", str(d), "--slot", "4", "--light"])
    assert code == 1
    assert capsys.readouterr().out == "should-run: skip\n"
