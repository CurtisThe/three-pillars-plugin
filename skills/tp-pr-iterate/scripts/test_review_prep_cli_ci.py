"""Tests for review_prep_cli `ci-logs` and `scaffold-targets`.

design: cheap-tier-review-prep (Task 6.4)

`ci-logs` is fail-open and capped: at most 3 failed-run logs, the last 200 kB
of each, argv calls with a 60 s timeout through the module's `RUNNER` seam.
`scaffold-targets` prints the Phase 5 target list (key, file, summary).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import review_prep_cli  # noqa: E402
import review_prep_scaffold  # noqa: E402

PR = "https://github.com/o/r/pull/1"
CAP = 200_000


def _run_cli(capsys, *argv):
    assert review_prep_cli.main(list(argv)) == 0
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _work(tmp_path):
    W = tmp_path / "W"
    W.mkdir()
    (W / "meta.json").write_text(json.dumps({"repo": str(tmp_path), "head": "h"}),
                                 encoding="utf-8")
    return W


def _config(tmp_path, obj):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def _run_check(i, name=None, conclusion="FAILURE"):
    return {"__typename": "CheckRun", "name": name or f"job {i}", "status": "COMPLETED",
            "conclusion": conclusion,
            "detailsUrl": f"https://github.com/o/r/actions/runs/{100 + i}/job/{i}"}


def _rollup(n_failed=5):
    checks = [_run_check(i) for i in range(n_failed)]
    checks.append(_run_check(90, "lint", "SUCCESS"))
    checks.append({"__typename": "StatusContext", "context": "ci/x", "state": "FAILURE",
                   "targetUrl": "https://example.com/build/1"})
    return {"statusCheckRollup": checks}


class FakeGh:
    """A runner seam: `gh pr view` -> the rollup, `gh run view <id>` -> a long log."""

    def __init__(self, rollup, bad_ids=()):
        self.rollup, self.bad_ids, self.calls = rollup, set(bad_ids), []

    def log_text(self, run_id):
        return "".join(f"{run_id}:{i:06d}\n" for i in range(25_000))[:250_000]

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if argv[1:3] == ["pr", "view"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.rollup), "")
        run_id = argv[3]
        if run_id in self.bad_ids:
            return subprocess.CompletedProcess(argv, 1, "", "run gone")
        return subprocess.CompletedProcess(argv, 0, self.log_text(run_id), "")


def test_ci_logs_not_expected_prints_empty_without_calling_gh(tmp_path, capsys, monkeypatch):
    W = _work(tmp_path)
    fake = FakeGh(_rollup())
    monkeypatch.setattr(review_prep_cli, "RUNNER", fake)
    cfg = _config(tmp_path, {"ci": {"expects_github_checks": False}})
    out = _run_cli(capsys, "ci-logs", "--work", str(W), "--pr-url", PR, "--config", cfg)
    assert out == {"logs": []}
    assert fake.calls == []


def test_ci_logs_gh_absent_is_fail_open(tmp_path, capsys, monkeypatch):
    W = _work(tmp_path)

    def no_gh(argv, **kwargs):
        raise OSError("no gh")

    monkeypatch.setattr(review_prep_cli, "RUNNER", no_gh)
    out = _run_cli(capsys, "ci-logs", "--work", str(W), "--pr-url", PR,
                   "--config", str(tmp_path / "missing.json"))
    assert out == {"logs": []}


def test_ci_logs_unparseable_config_defaults_to_expected(tmp_path, capsys, monkeypatch):
    W = _work(tmp_path)
    fake = FakeGh(_rollup(1))
    monkeypatch.setattr(review_prep_cli, "RUNNER", fake)
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    out = _run_cli(capsys, "ci-logs", "--work", str(W), "--pr-url", PR, "--config", str(bad))
    assert [e["check"] for e in out["logs"]] == ["job-0"]


def test_ci_logs_missing_meta_is_empty(tmp_path, capsys, monkeypatch):
    W = tmp_path / "W"
    W.mkdir()
    fake = FakeGh(_rollup())
    monkeypatch.setattr(review_prep_cli, "RUNNER", fake)
    out = _run_cli(capsys, "ci-logs", "--work", str(W), "--pr-url", PR,
                   "--config", str(tmp_path / "missing.json"))
    assert out == {"logs": []}
    assert fake.calls == []


def test_ci_logs_caps_count_and_size_and_skips_a_failed_run(tmp_path, capsys, monkeypatch):
    W = _work(tmp_path)
    fake = FakeGh(_rollup(5), bad_ids={"101"})  # the second failed check's run
    monkeypatch.setattr(review_prep_cli, "RUNNER", fake)
    out = _run_cli(capsys, "ci-logs", "--work", str(W), "--pr-url", PR,
                   "--config", str(tmp_path / "missing.json"))
    # a failed `gh run view` does not count: runs 100, 102, 103 are fetched; 104 is not
    assert [e["check"] for e in out["logs"]] == ["job-0", "job-2", "job-3"]
    for entry, run_id in zip(out["logs"], ("100", "102", "103")):
        path = Path(entry["path"])
        assert path == W / "ci" / f"{entry['check']}.log"
        data = path.read_bytes()
        assert len(data) == CAP
        assert data == fake.log_text(run_id).encode("utf-8")[-CAP:]
    assert not (W / "ci" / "job-1.log").exists()
    assert not (W / "ci" / "job-4.log").exists()
    assert all(kw["timeout"] == 60 for _argv, kw in fake.calls)
    assert all(kw["cwd"] == str(tmp_path) for _argv, kw in fake.calls)
    assert all(argv[0] == "gh" for argv, _kw in fake.calls)


def test_ci_logs_one_fetch_per_run_and_unique_slugs(tmp_path, capsys, monkeypatch):
    W = _work(tmp_path)
    shared = [_run_check(0, "build / test"), _run_check(0, "other"),  # one run id: one fetch
              _run_check(5, "build / test")]  # same slug, other run: made unique
    fake = FakeGh({"statusCheckRollup": shared})
    monkeypatch.setattr(review_prep_cli, "RUNNER", fake)
    out = _run_cli(capsys, "ci-logs", "--work", str(W), "--pr-url", PR,
                   "--config", str(tmp_path / "missing.json"))
    assert [e["check"] for e in out["logs"]] == ["build-test", "build-test-2"]
    assert len([a for a, _k in fake.calls if a[1:3] == ["run", "view"]]) == 2


def test_ci_logs_unparseable_gh_json_is_empty(tmp_path, capsys, monkeypatch):
    W = _work(tmp_path)

    def junk(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "not json", "")

    monkeypatch.setattr(review_prep_cli, "RUNNER", junk)
    assert review_prep_cli.main(["ci-logs", "--work", str(W), "--pr-url", PR,
                                 "--config", str(tmp_path / "missing.json")]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out) == {"logs": []}
    assert cap.err.count("[cheap-tier] ci-logs skipped: ") == 1  # logged, not swallowed


def test_ci_logs_tail_cut_inside_a_multibyte_char_reads_strict(tmp_path, capsys, monkeypatch):
    W = _work(tmp_path)
    fake = FakeGh(_rollup(1))
    fake.log_text = lambda run_id: "\u00e9" * 150_000 + "x"  # 300_001 bytes; the cut is mid-char
    monkeypatch.setattr(review_prep_cli, "RUNNER", fake)
    out = _run_cli(capsys, "ci-logs", "--work", str(W), "--pr-url", PR,
                   "--config", str(tmp_path / "missing.json"))
    text = Path(out["logs"][0]["path"]).read_text(encoding="utf-8")  # strict: no error
    assert text == "\u00e9" * 99_999 + "x"


def _build_round(tmp_path, n=1):
    rd = tmp_path / "proof" / "rounds" / "pr1" / "r2"
    log = tmp_path / "proof" / "iterate-log.1.md"
    found = [{"file": f"src/a{i or ''}.py", "line_range": [3, 5], "summary": f"boom{i or ''}",
              "class": "P", "blocking": True} for i in range(n)]
    rp = rd / "angle0" / "reply.md"
    rp.parent.mkdir(parents=True)
    rp.write_text("```json\n" + json.dumps({"findings": found}) + "\n```\n",
                  encoding="utf-8")
    manifest = {"pr_url": PR, "round": 2, "ordinal": "r2", "base": "BASE",
                "paths": {"proof_root": str(tmp_path / "proof"),
                          "state_path": str(tmp_path / "proof" / "s.json"),
                          "log_path": str(log)},
                "angles": [{"name": "angle0", "role": "confirmer", "model": "opus",
                            "tier": "claude", "reply_path": str(rp)}]}
    (rd / "angles.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return rd


def test_scaffold_targets_prints_key_file_summary(tmp_path, capsys):
    rd = _build_round(tmp_path)
    expected = review_prep_scaffold.targets(rd)
    assert len(expected) == 1
    out = _run_cli(capsys, "scaffold-targets", "--round-dir", str(rd))
    assert out == {"targets": [{"key": expected[0]["key"], "file": "src/a.py",
                                "summary": "boom"}]}


def test_open_target_lookup_writes_no_cap_lines(tmp_path, capsys):
    rd = _build_round(tmp_path, n=7)  # two over SCAFFOLD_CAP (impl-audit finding 5)
    log = tmp_path / "proof" / "iterate-log.1.md"
    picked = review_prep_scaffold.targets(rd, log=False)
    assert len(picked) == review_prep_scaffold.SCAFFOLD_CAP and not log.exists()
    for _ in range(3):  # one lookup per `open`: the cap is still applied, never logged
        assert review_prep_cli._scaffold_target(rd, picked[0]["key"]) == picked[0]
        assert review_prep_cli._scaffold_target(rd, "0" * 16) is None
        assert review_prep_cli._scaffold_target(rd, review_prep_scaffold._picked(rd)[5]["key"]) \
            is None  # over the cap
    assert not log.exists()
    _run_cli(capsys, "scaffold-targets", "--round-dir", str(rd))
    assert log.read_text(encoding="utf-8").count("[cheap-tier] scaffold-cap: ") == 2
