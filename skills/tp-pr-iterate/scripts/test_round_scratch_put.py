"""test_round_scratch_put.py — `round_scratch.py put`, script-mediated delivery (1.4).

Sub-agents never file-write under the proof root: an angle reply or the tail envelope
is piped through Bash into `put`, which computes its own target (`R/<angle>/reply.md`,
`R/tail/envelope.json`) and refuses an unlisted or skipped slot, a symlinked target, an
escaping slot name or a missing manifest (exit 2, nothing written). The prompt's quoted
heredoc carries `$`, backticks and pytest source to the file byte-exact.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import angles  # noqa: E402
import round_scratch as rs  # noqa: E402
from proof_root_itest import snapshot  # noqa: E402
from test_round_scratch_tail import _good  # noqa: E402

PR = "https://github.com/o/r/pull/42"
SCRIPT = HERE / "round_scratch.py"
TAG = "TP_REPLY_EOF"
NASTY = ("Findings for $HOME and `whoami` and $(id -u) \\n kept.\n\n"
         "```python\ndef test_x(tmp_path):\n    s = f\"${tmp_path}\"\n"
         "    assert '\\\\' in r\"\\\\\"\n```\n\n```json\n[]\n```")


def _round(tmp_path) -> Path:
    root = tmp_path / "proof"
    return rs.prepare(root, PR, angles.DEFAULT_ANGLES, base="b0", head="h1", effort="high",
                      state_path=str(root / "s.json"), log_path=str(root / "l.md"))


def _put(rd, slot, data: bytes) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "put", "--round-dir", str(rd),
                           "--slot", slot], input=data, capture_output=True, check=False)


def _name(i=0) -> str:
    return angles.DEFAULT_ANGLES[i]["name"]


def _manifest(rd) -> dict:
    return json.loads((Path(rd) / "angles.json").read_text(encoding="utf-8"))


def test_put_writes_stdin_to_the_computed_reply_slot_only(tmp_path):
    rd = _round(tmp_path)
    m = _manifest(rd)
    m["angles"][0]["reply_path"] = str(tmp_path / "decoy.md")  # never trusted
    (rd / "angles.json").write_text(json.dumps(m), encoding="utf-8")
    before = snapshot(tmp_path)
    p = _put(rd, _name(), b"reply bytes\n")
    assert p.returncode == 0, p.stdout + p.stderr
    target = rd / _name() / "reply.md"
    assert target.read_bytes() == b"reply bytes\n"
    assert snapshot(tmp_path) - before == set([str(target)])


def test_prompt_heredoc_round_trips_byte_exact_through_bash(tmp_path):
    rd = _round(tmp_path)
    prompt = _manifest(rd)["angles"][1]["prompt"]
    cmd = next(ln for ln in prompt.splitlines() if ln.startswith("python3 "))
    script = f"{cmd}\n{NASTY}\n{TAG}\n"
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stdout + p.stderr
    assert (rd / _name(1) / "reply.md").read_text(encoding="utf-8") == NASTY + "\n"
    assert rs.read_replies(rd)[1] == NASTY + "\n"


def test_symlinked_target_is_refused_and_nothing_written(tmp_path):
    rd = _round(tmp_path)
    victim = tmp_path / "victim.md"
    os.symlink(victim, rd / _name() / "reply.md")
    p = _put(rd, _name(), b"x")
    assert p.returncode == 2 and "refused" in json.loads(p.stdout)
    assert not victim.exists()


@pytest.mark.parametrize("link", ["sibling", "dangling", "outside"])
@pytest.mark.parametrize("slot", ["angle", "tail"])
def test_symlink_inside_the_round_dir_is_refused_and_nothing_written(tmp_path, slot, link):
    # The slot's target is a symlink: to another slot's existing reply (containment alone
    # passes this one), to a sibling that has not replied yet (dangling: following it would
    # create that reply), or to a file outside R. An angle reply and the tail envelope alike.
    rd = _round(tmp_path)
    name, leaf = (_name(), "reply.md") if slot == "angle" else ("tail", "envelope.json")
    dest = tmp_path / "outside.md" if link == "outside" else rd / _name(1) / "reply.md"
    if link == "sibling":
        dest.write_bytes(b"B's own reply\n")
    os.symlink(dest, rd / name / leaf)
    before = snapshot(tmp_path)
    p = _put(rd, name, b"clobber")
    assert p.returncode == 2 and "refused" in json.loads(p.stdout)
    if link == "sibling":
        assert dest.read_bytes() == b"B's own reply\n", "put wrote through an in-R symlink"
    else:
        assert not dest.exists(), "put followed a dangling symlink"
    assert snapshot(tmp_path) == before


def test_symlinked_slot_dir_is_refused(tmp_path):
    rd = _round(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (rd / _name()).rmdir()
    os.symlink(outside, rd / _name())
    assert _put(rd, _name(), b"x").returncode == 2
    assert list(outside.iterdir()) == []


def test_escaping_slot_name_is_refused(tmp_path):
    rd = _round(tmp_path)
    before = snapshot(tmp_path)
    for slot in ("../x", "..", "/etc/x", "a/b"):
        assert _put(rd, slot, b"x").returncode == 2, slot
    assert snapshot(tmp_path) == before


def test_escaping_name_listed_in_the_manifest_is_still_refused(tmp_path):
    # The manifest lists the escaping names and their dirs exist: only put's own
    # name check and containment check stand between put and `<R>/../x/reply.md`.
    rd = _round(tmp_path)
    (rd.parent / "x").mkdir()
    (rd / "a").mkdir()
    m = _manifest(rd)
    m["angles"] += [dict(m["angles"][0], name=n) for n in ("../x", "a/../../x")]
    (rd / "angles.json").write_text(json.dumps(m), encoding="utf-8")
    before = snapshot(tmp_path)
    for slot in ("../x", "a/../../x"):
        p = _put(rd, slot, b"x")
        assert p.returncode == 2 and "refused" in json.loads(p.stdout), slot
    assert snapshot(tmp_path) == before


def test_tail_slot_writes_the_envelope_that_tail_check_reads(tmp_path):
    rd = _round(tmp_path)
    p = _put(rd, "tail", json.dumps(_good()).encode("utf-8"))
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads((rd / "tail" / "envelope.json").read_text(encoding="utf-8")) == _good()
    assert rs.tail_check(rd) is None


def test_unknown_skipped_or_missing_manifest_is_refused(tmp_path):
    rd = _round(tmp_path)
    assert _put(rd, "not-an-angle", b"x").returncode == 2
    (rd / "not-an-angle").mkdir()  # an unlisted slot whose dir DOES exist under R
    p = _put(rd, "not-an-angle", b"x")
    assert p.returncode == 2 and "refused" in json.loads(p.stdout)
    assert list((rd / "not-an-angle").iterdir()) == []
    m = _manifest(rd)
    m["angles"][2]["skipped"] = "local backend absent"
    (rd / "angles.json").write_text(json.dumps(m), encoding="utf-8")
    assert _put(rd, _name(2), b"x").returncode == 2
    assert not (rd / _name(2) / "reply.md").exists()
    bare = tmp_path / "bare"
    (bare / "tail").mkdir(parents=True)
    assert _put(bare, "tail", b"x").returncode == 2
    assert not (bare / "tail" / "envelope.json").exists()


def test_build_prompt_names_the_exact_put_command():
    a = angles.DEFAULT_ANGLES[0]
    p = angles.build_prompt(a, base="b0", head="h1", effort="high",
                            reply_path="/r/x/reply.md", round_dir="/r",
                            put_script="/fw/round_scratch.py")
    want = f"python3 /fw/round_scratch.py put --round-dir /r --slot {a['name']} <<'{TAG}'"
    assert want in p.splitlines()
    assert TAG in p.splitlines()
    assert "to `/r/x/reply.md`" not in p and "Write the full reply" not in p
    assert "Write tool" in p


def test_prepare_threads_the_round_dir_and_absolute_script(tmp_path):
    rd = _round(tmp_path)
    for e in _manifest(rd)["angles"]:
        cmd = f"python3 {SCRIPT} put --round-dir {rd} --slot {e['name']} <<'{TAG}'"
        assert cmd in e["prompt"].splitlines()
