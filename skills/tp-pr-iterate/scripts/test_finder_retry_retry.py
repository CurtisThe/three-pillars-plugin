"""Task 1.10: `finder_retry.retry` re-plans one capped segment as two halves, once.

design: finder-cap-coverage (Behavior 2) — a capped first-attempt segment becomes
two half-size Strata entries (`<A>a`, `<A>b`), each with its own slot, reply path,
exec dir and prompt, keeping the parent's `fraction` and `rung`. What `retry`
refuses or answers instead (Sonnet, `uncovered`, exit 2) is in
`test_finder_retry_refuse.py`, which imports this module's fixtures.

The prompt under test is built exactly the way `round_scratch.prepare` builds one:
`angles.build_prompt` over `finder_segments.segment_prompt`, plus the exec note and
the angle-tree note. The diff arrives through the `diff_text=` seam, so no git repo
is needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import angle_tree  # noqa: E402
import angles  # noqa: E402
import finder_retry  # noqa: E402
import finder_segments as fs  # noqa: E402
import round_put  # noqa: E402
import round_scratch as rs  # noqa: E402

BASE, HEAD = "base1", "head1"
PARENT = "correctness-s2"
SEG_FILES = ["a.py", "b.py", "c.py", "d.py"]
HALF_A, HALF_B = ["a.py", "d.py"], ["b.py", "c.py"]  # split_segment's balanced cut


def _file(path, n, hunks=1, start_step=100):
    """A diff for one file: `n` added lines spread over `hunks` new-side hunks."""
    out = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}"]
    per = n // hunks
    for h in range(hunks):
        out.append(f"@@ -{h * start_step + 1},0 +{h * start_step + 1},{per} @@")
        out += [f"+{path} line {i}" for i in range(per)]
    return "\n".join(out)


DIFF = "\n".join(_file(p, n) for p, n in
                 (("a.py", 100), ("b.py", 80), ("c.py", 60), ("d.py", 40))) + "\n"
ONE_HUNK_DIFF = _file("one.py", 900) + "\n"


def _seg(files=SEG_FILES, sid="s2", **kw):
    return {"angle": "correctness", "id": sid, "of": 2, "files": list(files),
            "fraction": 0.8, "lines": 280, "ranges": None, "max_segments": 4, **kw}


def _parent_entry(round_dir, seg=None, *, exec_dir=None, tree_dir=None, **kw):
    """The entry exactly as `round_scratch.prepare` writes it, prompt included."""
    seg = seg or _seg()
    name = PARENT
    (round_dir / name).mkdir(parents=True, exist_ok=True)
    reply = str(round_dir / name / "reply.md")
    exec_dir = exec_dir or str(round_dir / "exec-parent")
    tree_dir = tree_dir if tree_dir is not None else f"{exec_dir}/tree"
    angle = {"name": name, "role": "finder", "model": "local", "advisory": True,
             "segment": seg,
             "prompt": fs.segment_prompt("Hunt correctness leaks.", seg, n=seg["of"],
                                         base=BASE, head=HEAD, whole=fs.manifest_text(DIFF))}
    prompt = angles.build_prompt(angle, base=BASE, head=HEAD, effort="xhigh",
                                 reply_path=reply, round_dir=str(round_dir),
                                 put_script=str(_HERE / "round_scratch.py"))
    prompt += rs._EXEC_NOTE.format(exec_dir=exec_dir) + angle_tree.note(exec_dir, tree_dir)
    return {"name": name, "role": "finder", "model": "local", "advisory": True,
            "agent": "tp-review-confirmer-deep-strata", "agent_ref": "x",
            "dispatch_model": "strata", "tier": "local", "reply_path": reply,
            "exec_dir": exec_dir, "tree_dir": tree_dir, "segment": seg,
            "prompt": prompt, **kw}


def _manifest(round_dir, entries, **top):
    (round_dir / "angles.json").write_text(
        json.dumps({"base": BASE, "head": HEAD, "angles": list(entries), **top},
                   indent=2) + "\n", encoding="utf-8")
    return entries


def _read(round_dir):
    return json.loads((round_dir / "angles.json").read_text(encoding="utf-8"))


def _entry(round_dir, name):
    return next(e for e in _read(round_dir)["angles"] if e["name"] == name)


def _retry(round_dir, name=PARENT, diff=DIFF):
    return finder_retry.retry(round_dir, name, diff_text=diff)


def _split_prompt(prompt):
    """(prompt before the SEGMENT block, the SEGMENT block)."""
    i = prompt.index("SEGMENT ")
    return prompt[:i], prompt[i:]


# --- the two halves land in the manifest ------------------------------------

def test_retry_appends_two_half_entries(tmp_path):
    parent = _parent_entry(tmp_path)
    _manifest(tmp_path, [parent])
    out = _retry(tmp_path)
    assert out["next"] == "retry"
    man = _read(tmp_path)
    assert [e["name"] for e in man["angles"]] == [PARENT, PARENT + "a", PARENT + "b"]
    a, b = _entry(tmp_path, PARENT + "a"), _entry(tmp_path, PARENT + "b")
    for half in (a, b):
        assert half["reply_path"] == str(tmp_path / half["name"] / "reply.md")
        assert (tmp_path / half["name"]).is_dir()  # its own slot dir exists
        assert half["reply_path"] != parent["reply_path"]
        assert half["exec_dir"] != parent["exec_dir"]
        assert Path(half["exec_dir"]).is_dir()
        assert half["tree_dir"] != parent["tree_dir"]
        assert half["segment"]["retry_of"] == PARENT
        assert half["segment"]["fraction"] == parent["segment"]["fraction"]
        assert half["attempt"] == 2
        assert half["rung"] == parent.get("rung")
        assert "skipped" not in half
    assert a["exec_dir"] != b["exec_dir"]
    assert [a["segment"]["files"], b["segment"]["files"]] == [HALF_A, HALF_B]
    after = _entry(tmp_path, PARENT)
    assert after["skipped"] == "retried"
    assert after["telemetry"]["outcome"] == "retried"


def test_halves_keep_the_parent_rung(tmp_path):
    parent = _parent_entry(tmp_path, rung="strata-xhigh")
    _manifest(tmp_path, [parent])
    _retry(tmp_path)
    for suffix in ("a", "b"):
        assert _entry(tmp_path, PARENT + suffix)["rung"] == "strata-xhigh"


def test_round_put_takes_the_halves_and_refuses_the_parent(tmp_path):
    _manifest(tmp_path, [_parent_entry(tmp_path)])
    _retry(tmp_path)
    assert round_put.target_for(tmp_path, PARENT + "a") == tmp_path / (PARENT + "a") / "reply.md"
    try:
        round_put.target_for(tmp_path, PARENT)
        raise AssertionError("the retried parent must not accept a reply")
    except round_put.PutRefused as exc:
        assert "retried" in str(exc)


# --- each half's prompt names only its own files ----------------------------

def test_half_prompt_names_only_its_own_files(tmp_path):
    _manifest(tmp_path, [_parent_entry(tmp_path)])
    _retry(tmp_path)
    a, b = _entry(tmp_path, PARENT + "a"), _entry(tmp_path, PARENT + "b")
    stem, block = _split_prompt(a["prompt"])
    listed = block.split("review only these files", 1)[1].split(". Run `git diff", 1)[0]
    listed = listed.split(":", 1)[1].split("(new-side", 1)[0]
    assert [p.strip() for p in listed.split(",")] == HALF_A
    pathspec = block.split(f"git diff {BASE}...{HEAD} -- ", 1)[1].split("`,")[0]
    assert pathspec.split() == HALF_A
    # half b's files reach half a's prompt only inside the whole-change manifest
    whole = fs.manifest_text(DIFF)
    assert whole in a["prompt"]
    assert not any(p in a["prompt"].replace(whole, "") for p in HALF_B)
    stem_b, block_b = _split_prompt(b["prompt"])
    tail_b = b["prompt"][b["prompt"].index("owns cross-segment judgement."):]
    assert f"--slot {PARENT}b" in tail_b and b["reply_path"] in tail_b
    assert f"{PARENT}a" not in b["prompt"]
    listed_b = block_b.split("review only these files", 1)[1].split(". Run `git diff", 1)[0]
    listed_b = listed_b.split(":", 1)[1].split("(new-side", 1)[0]
    assert [p.strip() for p in listed_b.split(",")] == HALF_B
    spec_b = block_b.split(f"git diff {BASE}...{HEAD} -- ", 1)[1].split("`,")[0]
    assert spec_b.split() == HALF_B


def test_half_prompt_carries_its_own_scratch_slot_paths_and_return_line(tmp_path):
    _manifest(tmp_path, [_parent_entry(tmp_path)])
    _retry(tmp_path)
    parent, a = _entry(tmp_path, PARENT), _entry(tmp_path, PARENT + "a")
    for old in (parent["reply_path"], parent["exec_dir"], parent["tree_dir"]):
        assert old not in a["prompt"]
    assert f"TP_SCRATCH: {tmp_path / (PARENT + 'a')}" in a["prompt"]
    assert f"--slot {PARENT + 'a'}" in a["prompt"]
    assert f"--slot {PARENT} " not in a["prompt"]  # the parent's slot token is gone
    assert f'reply_path="{a["reply_path"]}"' in a["prompt"]
    assert a["exec_dir"] in a["prompt"]
    assert "Exec dir" in a["prompt"]
    assert "private copy" in a["prompt"] or "No private copy" in a["prompt"]


def test_hunk_split_half_names_its_ranges_and_pathspec(tmp_path):
    seg = _seg(files=["big.py"], sid="s1")
    diff = _file("big.py", 60, hunks=3) + "\n"
    _manifest(tmp_path, [_parent_entry(tmp_path, seg=seg)])
    assert _retry(tmp_path, diff=diff)["next"] == "retry"
    a = _entry(tmp_path, PARENT + "a")
    assert a["segment"]["files"] == ["big.py"]
    assert a["segment"]["ranges"]
    _, block = _split_prompt(a["prompt"])
    assert f"(new-side lines {a['segment']['ranges'][0]}-{a['segment']['ranges'][1]} only)" in block
