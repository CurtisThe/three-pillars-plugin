"""The A/B shadow prompt delivers into the shadow reply (PR #209 review r1).

`round_put.target_for` computes `R/<slot>/reply.md` itself and never trusts a
manifest's `reply_path`, so rewriting only the reply_path text in a shadow prompt
left its `put --round-dir R` line writing over the REAL angle's reply.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_prep_ab as ab  # noqa: E402
import round_put  # noqa: E402
import round_scratch as rs  # noqa: E402


def _round(tmp_path, name="edge-cases"):
    angles = [{"name": name, "role": "confirmer", "model": "opus", "prompt": "Hunt."}]
    return rs.prepare(tmp_path / "proof", "https://github.com/o/r/pull/42", angles,
                      base="b0", head="h1", effort="high",
                      state_path=str(tmp_path / "s.json"), log_path=str(tmp_path / "l.md"))


def _shadow_entry(r, tmp_path):
    w = tmp_path / "W"
    (w / "accepted").mkdir(parents=True)
    (w / "accepted" / "review_refs--_.json").write_text(
        json.dumps({"refs": [{"path": "a.py", "line": 1, "note": "n"}]}), encoding="utf-8")
    (w / "diff.patch").write_text("", encoding="utf-8")
    man = ab.shadow(r, w, {"review_refs": {"rung": "local-medium"}}, [])
    return json.loads(man.read_text(encoding="utf-8"))["angles"][0]


def _put_argv(prompt):
    line = next(l for l in prompt.splitlines() if " put --round-dir " in l)
    return shlex.split(line.split(" <<", 1)[0])


def test_shadow_put_command_targets_the_shadow_reply(tmp_path):
    r = _round(tmp_path, "correctness-leak")
    entry = _shadow_entry(r, tmp_path)
    argv = _put_argv(entry["prompt"])
    target = round_put.target_for(argv[argv.index("--round-dir") + 1],
                                  argv[argv.index("--slot") + 1])
    assert str(target) == entry["reply_path"], (target, entry["reply_path"])
    assert f"TP_SCRATCH: {Path(entry['reply_path']).parent}\n" in entry["prompt"]


def test_running_the_shadow_put_leaves_the_real_reply_untouched(tmp_path):
    r = _round(tmp_path)
    entry = _shadow_entry(r, tmp_path)
    proc = subprocess.run(_put_argv(entry["prompt"]), input=b'{"findings": []}',
                          capture_output=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (r / "edge-cases" / "reply.md").exists(), "shadow reply hit the real slot"
    assert Path(entry["reply_path"]).read_bytes() == b'{"findings": []}'
