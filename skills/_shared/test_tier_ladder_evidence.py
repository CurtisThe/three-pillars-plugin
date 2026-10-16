"""test_tier_ladder_evidence.py — Task 2.7: evidence flags on `next`; dispatch/stuck/flag lines."""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ladder_entry  # noqa: E402
import local_route_log  # noqa: E402

CLI = str(HERE / "tier_ladder.py")
PLAN = """# Plan

## Phase 1: x

### Task 1.1: t
**File**: `a.py` (new)
**Test**: t
**Targets**: `test_a.py` (new)
**Red**: r
**Green**: g
"""


def run(*args):
    return subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True)


def start(tmp_path, tier, route='{"schema": "tp-local-route/v1", "state": "routed", "reason": "ok", "base_url": null, "checked_at": "t"}'):
    rec = tmp_path / "rec.json"
    args = ["start", "--task", "1.1", "--tier", tier, "--record", str(rec),
            "--root", str(tmp_path)]
    if route:
        args += ["--route", route]
    assert run(*args).returncode == 0
    return rec


def w(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_hook_failed_size_split_goes_opus_medium(tmp_path):
    rec = start(tmp_path, "sonnet-medium", route=None)
    reply = w(tmp_path, "reply.txt", "file-size-guard: x.py exceeds 500 lines\n"
              '{"task_id": "1.1", "sha": null, "claimed": "hook-failed"}')
    check = w(tmp_path, "c.json", json.dumps({"reason": "no commit"}))
    plan = w(tmp_path, "plan.md", PLAN)
    r = run("next", "--record", str(rec), "--outcome", "FAIL", "--check-json", check,
            "--scan", w(tmp_path, "s.json", json.dumps({"flags": ["big-turn"], "tokens": 5,
                                                       "wall_s": 9})),
            "--reply-json", reply, "--plan", plan, "--phase", "1", "--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["rung"] == "opus-medium"
    v = json.loads(rec.read_text(encoding="utf-8"))["verdicts"][0]
    assert v["class"] == "deterministic:size-split" and v["stuck"] == "deterministic"
    assert v["flags"] == ["big-turn"] and v["tokens"] == 5 and v["wall_s"] == 9


def test_reply_banner_lines_become_permission_refused_flags(tmp_path):
    """Task 1.6: the reply's leading `permission-refused:` lines become one flag per rule."""
    reply = w(tmp_path, "r.txt", "permission-refused: Bash(rm -rf build)\n"
              "permission-refused: WebFetch\n"
              '{"task_id": "1.1", "sha": "abc", "claimed": "red"}')
    assert ladder_entry.build_evidence("1.1", reply=reply)["flags"] == [
        "permission-refused: Bash(rm -rf build)", "permission-refused: WebFetch"]
    # a scan's flags come first; the refusal flags are appended after them
    scan = w(tmp_path, "s.json", json.dumps({"flags": ["big-turn"]}))
    assert ladder_entry.build_evidence("1.1", scan=scan, reply=reply)["flags"] == [
        "big-turn", "permission-refused: Bash(rm -rf build)", "permission-refused: WebFetch"]
    # the banner only counts as the reply's LEADING block (permission_refusal.parse_lines)
    quoted = w(tmp_path, "q.txt", '{"task_id": "1.1", "claimed": "red"}\n'
               'permission-refused: Bash(rm -rf build)')
    assert "flags" not in ladder_entry.build_evidence("1.1", reply=quoted)


def test_hook_failed_reply_still_gives_only_the_hook_tail(tmp_path):
    """The existing hook-failed handling is unchanged by the refusal flags."""
    reply = w(tmp_path, "h.txt", "file-size-guard: x.py exceeds 500 lines\n"
              '{"task_id": "1.1", "sha": null, "claimed": "hook-failed"}')
    ev = ladder_entry.build_evidence("1.1", reply=reply)
    assert ev["hook_tail"] == "file-size-guard: x.py exceeds 500 lines"
    assert "flags" not in ev


def test_watch_json_puts_gen_served_in_verdict_and_entry(tmp_path):
    rec = start(tmp_path, "local-medium")
    watch = w(tmp_path, "p.json", json.dumps({
        "gen": {"local_requests": 3, "max": 900, "p50": 400, "at_cap": 1},
        "served": {"local_requests": 3, "turns": 4}, "elapsed_s": 12}))
    assert run("next", "--record", str(rec), "--outcome", "PASS", "--watch-json", watch,
               "--root", str(tmp_path)).returncode == 0
    v = json.loads(rec.read_text(encoding="utf-8"))["verdicts"][0]
    assert v["gen"]["max"] == 900 and v["served"]["turns"] == 4
    entry = run("entry", "--record", str(rec)).stdout
    assert "flag: gen-stats local_requests=3/4 n_gen_max=900 n_gen_p50=400 at_cap=1" in entry


def test_no_stats_and_w_shaped_file_are_unavailable(tmp_path):
    rec = start(tmp_path, "local-medium")
    wshape = w(tmp_path, "W.json", json.dumps({"armed": True, "ceiling": 24000}))
    r = run("next", "--record", str(rec), "--outcome", "PASS", "--watch-json", wshape,
            "--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "flag: gen-stats unavailable" in run("entry", "--record", str(rec)).stdout


def test_unreadable_files_are_ignored(tmp_path):
    rec = start(tmp_path, "local-medium")
    bad = str(tmp_path / "nope.json")
    r = run("next", "--record", str(rec), "--outcome", "PASS", "--check-json", bad,
            "--scan", bad, "--reply-json", bad, "--watch-json", bad, "--plan", bad,
            "--phase", "1", "--root", str(tmp_path))
    assert r.returncode == 0, r.stderr


def test_dispatch_line_and_order(tmp_path):
    rec = start(tmp_path, "local-medium")
    for outcome in ("unavailable", "FAIL"):
        assert run("next", "--record", str(rec), "--outcome", outcome, "--reason", "boom",
                   "--root", str(tmp_path)).returncode == 0
    entry = run("entry", "--record", str(rec)).stdout.splitlines()
    disp = [ln for ln in entry if ln.startswith("[dispatch]")]
    assert disp[0].startswith("[dispatch] task 1.1 → tp-task-worker-local-medium (")
    assert ", medium, routed/ok) — task_start: unavailable" in disp[0]
    assert "tp-task-worker-sonnet-medium" in disp[1] and "— fallback: FAIL" in disp[1]
    assert entry.index(disp[0]) > entry.index("**Red-at-base**: n/a")


def test_opus_dispatch_spawns_its_variant(tmp_path):
    rec = start(tmp_path, "opus-medium", route=None)
    assert run("next", "--record", str(rec), "--outcome", "PASS",
               "--root", str(tmp_path)).returncode == 0
    entry = run("entry", "--record", str(rec)).stdout
    assert "→ tp-task-worker-opus-medium (opus, medium," in entry and "inline" not in entry


def test_stuck_line_and_telemetry_keys(tmp_path):
    rec = start(tmp_path, "sonnet-medium", route=None)
    reply = w(tmp_path, "r.txt", 'file-size-guard\n{"claimed": "hook-failed"}')
    run("next", "--record", str(rec), "--outcome", "FAIL", "--reply-json", reply,
        "--root", str(tmp_path))
    entry = run("entry", "--record", str(rec)).stdout
    assert "stuck: deterministic size-split" in entry
    tel = json.loads(run("telemetry", "--record", str(rec)).stdout)
    v = tel["verdicts"][0]
    for k in ("rung", "class", "fingerprint", "stuck", "flags", "tokens", "wall_s", "gen",
              "served", "model", "why"):
        assert k in v
    assert "stuck: deterministic" in ladder_entry.to_decision_entry(tel)


def test_new_lines_do_not_match_route_regexes(tmp_path):
    rec = start(tmp_path, "local-medium")
    run("next", "--record", str(rec), "--outcome", "PASS", "--root", str(tmp_path))
    entry = run("entry", "--record", str(rec)).stdout
    extra = "\n".join(ln for ln in entry.splitlines()
                      if ln.startswith(("[dispatch]", "stuck:", "flag:")))
    assert extra
    for pat in (local_route_log.CHECK_RE, local_route_log.END_RE, local_route_log.FLOOR_RE):
        assert not re.search(pat, extra, re.M)
