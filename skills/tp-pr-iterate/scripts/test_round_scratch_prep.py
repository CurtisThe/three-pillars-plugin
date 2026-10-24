"""The golden — pin today's `prepare` manifest bytes, keys unset.

design: cheap-tier-review-prep (Task 1.4)

Before any hook/prep code lands, pin exactly what `prepare` writes when no
`prep_dir` is involved: with fixed angles, base, head and `now`, the on-disk
`angles.json` must be byte-for-byte the manifest this test rebuilds from the
same pieces (`build_prompt` per angle, same key order, `indent=2`, the same
trailing newline). `prep_dir=None` (or omitted) must be accepted and change
nothing — the prompt ends exactly where `build_prompt` ends and no `R/prep/`
dir exists. It fails today because `prep_dir` is an unknown keyword.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import angles  # noqa: E402
import angle_tree  # noqa: E402
import agent_ref  # noqa: E402
import round_plan  # noqa: E402
import review_instructions  # noqa: E402
import review_prep  # noqa: E402
import round_scratch as rs  # noqa: E402
from repo_config_load import load_repo_config  # noqa: E402

PR = "https://github.com/o/r/pull/42"
NOW = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
BASE = "b0"
HEAD = "h1"
EFFORT = "high"
STATE = "iterate-state.42.v1.json"
LOG = "iterate-log.42.md"

# Fixed angles (not `angles.DEFAULT_ANGLES`, so the golden is self-contained and
# independent of any default drift). No `skipped` key → the conditional
# `{"skipped": …}` spread is absent.
ANGLES = [
    {"name": "correctness-leak", "role": "confirmer", "model": "opus",
     "prompt": "Hunt fail-closed/correctness leaks: a path to a wrong result."},
    {"name": "edge-cases", "role": "finder", "model": "sonnet",
     "prompt": "Hunt edge cases in loop-added code and test quality."},
]


def _golden(round_dir: Path, root: Path) -> str:
    """Rebuild the manifest from today's pieces, exactly as `prepare` writes it.

    Same keys, same order, `indent=2`, and the same trailing `"\n"` the
    writer appends.
    """
    instructions_present = (
        review_instructions.status(".", load_repo_config(".").config) == "present")
    round_no = 1  # first round in a fresh root → ordinal r1
    ordinal = "r1"
    started_at = NOW.isoformat()
    agent = angles.review_agent(round_no)
    ref = agent_ref.resolve(agent, None)
    entries = []
    written = json.loads((round_dir / "angles.json").read_text(encoding="utf-8"))["angles"]
    execs = {e["name"]: e["exec_dir"] for e in written}  # random mkdtemp paths: read back
    trees = {e["name"]: e["tree_dir"] for e in written}  # None here: HEAD is not a commit
    for a in ANGLES:
        reply = str(round_dir / a["name"] / rs.REPLY)
        entries.append({
            "name": a["name"], "role": a["role"], "model": a["model"],
            "agent": agent, "agent_ref": ref,
            "dispatch_model": angles.model_policy.agent_alias(a["model"]),
            "tier": angles.tier(a), "reply_path": reply, "exec_dir": execs[a["name"]],
            "tree_dir": trees[a["name"]],
            **({"skipped": a["skipped"]} if a.get("skipped") else {}),
            "prompt": angles.build_prompt(a, base=BASE, head=HEAD, effort=EFFORT,
                                          reply_path=reply, round_dir=str(round_dir),
                                          put_script=str(rs._HERE / "round_scratch.py"),
                                          instructions_present=instructions_present)
            + rs._EXEC_NOTE.format(exec_dir=execs[a["name"]])
            + angle_tree.note(execs[a["name"]], trees[a["name"]]),
        })
    manifest = {
        "pr_url": PR, "round": round_no, "ordinal": ordinal, "base": BASE, "head": HEAD,
        "effort": EFFORT, "started_at": started_at,
        "paths": {"proof_root": str(root),
                  "state_path": str(Path(root / STATE).absolute()),
                  "log_path": str(Path(root / LOG).absolute())},
        "angles": entries,
    }
    return json.dumps(manifest, indent=2) + "\n"


def _call(root, **kw):
    kw.setdefault("angles", ANGLES)
    return rs.prepare(root, PR, kw.pop("angles"), base=BASE, head=HEAD, effort=EFFORT,
                      state_path=str(root / STATE), log_path=str(root / LOG), now=NOW, **kw)


def test_golden_no_prep_dir(tmp_path):
    # Omit `prep_dir` entirely…
    r = _call(tmp_path)
    written = (r / "angles.json").read_text(encoding="utf-8")
    assert written == _golden(r, tmp_path)

    # …and pass `prep_dir=None` explicitly: identical bytes, nothing new.
    r2 = _call(tmp_path / "none", prep_dir=None)
    written2 = (r2 / "angles.json").read_text(encoding="utf-8")
    assert written2 == _golden(r2, tmp_path / "none")

    # Every prompt is exactly what `build_prompt` returns (so it ends exactly
    # where `build_prompt` ends — no prep suffix).
    instr = (review_instructions.status(".", load_repo_config(".").config) == "present")
    for e in json.loads(written)["angles"]:
        a = next(x for x in ANGLES if x["name"] == e["name"])
        assert e["prompt"] == angles.build_prompt(
            a, base=BASE, head=HEAD, effort=EFFORT, reply_path=e["reply_path"],
            instructions_present=instr) + rs._EXEC_NOTE.format(exec_dir=e["exec_dir"]
            ) + angle_tree.note(e["exec_dir"], e["tree_dir"])
    # No prep dir was created anywhere under the round.
    assert not (r / "prep").exists()
    assert not (r2 / "prep").exists()


def test_angle_named_prep_refused(tmp_path):
    angle = {"name": "prep", "role": "finder", "model": "sonnet", "prompt": "x"}
    with pytest.raises(ValueError, match="unsafe angle name"):
        _call(tmp_path, angles=[angle])
    assert not (tmp_path / "rounds").exists()


def _prep_dir(tmp_path, head=HEAD, accepted=None):
    """A prep work dir `W` with `meta.json` and (optionally) `accepted/` drafts."""
    w = tmp_path / "W"
    w.mkdir()
    (w / "meta.json").write_text(json.dumps({"head": head}), encoding="utf-8")
    if accepted:
        adir = w / "accepted"
        adir.mkdir()
        for filename, obj in accepted.items():
            (adir / filename).write_text(json.dumps(obj), encoding="utf-8")
    return w


def _instr():
    return (review_instructions.status(".", load_repo_config(".").config) == "present")


def _base_prompt(name, reply_path, exec_dir, tree_dir=None):
    a = next(x for x in ANGLES if x["name"] == name)
    return angles.build_prompt(a, base=BASE, head=HEAD, effort=EFFORT,
                               reply_path=reply_path, instructions_present=_instr()
                               ) + rs._EXEC_NOTE.format(exec_dir=exec_dir
                                                        ) + angle_tree.note(exec_dir, tree_dir)


def test_accepted_slice_adds_one_line(tmp_path):
    w = _prep_dir(tmp_path, accepted={
        "review_slice--correctness-leak.json":
            {"hunks": [{"file": "a.py", "hunk": "@@ -1 +1 @@\n-x\n+y\n"}]}})
    root = tmp_path / "proof"
    r = _call(root, prep_dir=w)
    manifest = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    golden = json.loads(_golden(r, root))
    assert list(manifest) == list(golden)
    for e, ge in zip(manifest["angles"], golden["angles"]):
        assert list(e) == list(ge)
    suffix = "\n\n" + review_prep.PREP_LINE.format(
        path=r / "prep" / "correctness-leak.md")
    cl = next(e for e in manifest["angles"] if e["name"] == "correctness-leak")
    assert cl["prompt"] == _base_prompt("correctness-leak", cl["reply_path"], cl["exec_dir"],
                                         cl["tree_dir"]) + suffix
    assert (r / "prep" / "correctness-leak.md").is_file()
    ec = next(e for e in manifest["angles"] if e["name"] == "edge-cases")
    assert ec["prompt"] == _base_prompt("edge-cases", ec["reply_path"], ec["exec_dir"],
                                        ec["tree_dir"])


def test_empty_prep_dir_prompts_unchanged(tmp_path):
    w = _prep_dir(tmp_path)
    root = tmp_path / "proof"
    r = _call(root, prep_dir=w)
    assert (r / "angles.json").read_text(encoding="utf-8") == _golden(r, root)


def test_skipped_angle_gets_no_line(tmp_path):
    skipped_angles = [dict(a) for a in ANGLES]
    for a in skipped_angles:
        if a["name"] == "edge-cases":
            a["skipped"] = "local backend absent"
    w = _prep_dir(tmp_path, accepted={
        "review_refs--_.json":
            {"refs": [{"path": "a.py", "line": 1, "note": "n"}]}})
    root = tmp_path / "proof"
    r = _call(root, angles=skipped_angles, prep_dir=w)
    manifest = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    suffix = "\n\n" + review_prep.PREP_LINE.format(
        path=r / "prep" / "correctness-leak.md")
    cl = next(e for e in manifest["angles"] if e["name"] == "correctness-leak")
    assert cl["prompt"].endswith(suffix)
    ec = next(e for e in manifest["angles"] if e["name"] == "edge-cases")
    assert ec["prompt"] == _base_prompt("edge-cases", ec["reply_path"], ec["exec_dir"],
                                        ec["tree_dir"])
    assert not (r / "prep" / "edge-cases.md").exists()


def test_cli_prep_dir_matches_kwarg(tmp_path, monkeypatch):
    """`main(["prepare", …, "--prep-dir", W])` ≡ `prepare(..., prep_dir=W)`.

    The flag defaults to `None`, which must give the golden's bytes. Both sides
    use the identical angle dict (via the same `--config` file / `load_angles`
    result) and a frozen clock (`rs.datetime` → `NOW`) so the only difference
    is the root path.

    `load_angles` enforces the review floor (Claude angles on `opus`), so the
    config uses the same two angles on `opus`, not the module's `ANGLES`. Since
    4.6 the CLI delegates the round to `round_plan.plan`, so the kwarg reference
    delegates the same way: the same angles, the plan's `base`, its keys as `meta`.
    """
    cfg = {"review": {"angles": [dict(a, model="opus") for a in ANGLES]}}
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    p = round_plan.plan(cfg, root=tmp_path / "plan", pr_url=PR, pr_base=BASE,
                        head=HEAD, repo=".", rulings_path="r.md")
    declared, pbase, pmeta = p["angles"], p["base"], {
        k: p[k] for k in ("mode", "pr_base", "security", "diff_lines")}

    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(rs, "datetime", _Fixed)
    slice_draft = {
        "review_slice--correctness-leak.json":
            {"hunks": [{"file": "a.py", "hunk": "@@ -1 +1 @@\n-x\n+y\n"}]}}

    # The CLI side.
    cli = tmp_path / "cli"
    cli.mkdir()
    _prep_dir(cli, accepted=slice_draft)
    root = cli / "proof"
    rc = rs.main(["prepare", "--root", str(root), "--pr-url", PR, "--base", BASE,
                  "--head", HEAD, "--effort", EFFORT, "--state", str(root / STATE),
                  "--log", str(root / LOG), "--config", str(cfg_path),
                  "--prep-dir", str(cli / "W"), "--rulings", "r.md"])
    assert rc == 0
    r = root / "rounds" / "42" / "r1"

    # The kwarg side.
    kcli = tmp_path / "kw"
    kcli.mkdir()
    _prep_dir(kcli, accepted=slice_draft)
    kroot = kcli / "proof"
    rk = rs.prepare(kroot, PR, declared, base=pbase, head=HEAD, effort=EFFORT,
                    state_path=str(kroot / STATE), log_path=str(kroot / LOG),
                    now=NOW, prep_dir=kcli / "W", meta=pmeta)
    assert rk == kroot / "rounds" / "42" / "r1"

    # Same manifest bytes up to the root path; the prep line is present and
    # each side's `R/prep/` matches in file set and bytes.
    cli_text = (r / "angles.json").read_text(encoding="utf-8")
    kw_text = (rk / "angles.json").read_text(encoding="utf-8")
    cli_execs = [e["exec_dir"] for e in json.loads(cli_text)["angles"]]
    kw_execs = [e["exec_dir"] for e in json.loads(kw_text)["angles"]]
    for ce, ke in zip(cli_execs, kw_execs):  # random mkdtemp per call
        cli_text = cli_text.replace(ce, ke)
    assert cli_text.replace(str(cli), str(kcli)) == kw_text
    suffix = "\n\n" + review_prep.PREP_LINE.format(
        path=r / "prep" / "correctness-leak.md")
    cl = next(e for e in json.loads(cli_text)["angles"]
              if e["name"] == "correctness-leak")
    assert cl["prompt"].endswith(suffix)
    cli_prep = {p.relative_to(r / "prep").as_posix() for p in (r / "prep").rglob("*")
                if p.is_file()}
    kw_prep = {p.relative_to(rk / "prep").as_posix() for p in (rk / "prep").rglob("*")
               if p.is_file()}
    assert cli_prep == kw_prep
    for rel in sorted(cli_prep):
        if rel.endswith(".md"):
            assert (r / "prep" / rel).read_bytes() == (rk / "prep" / rel).read_bytes()

    # The default: no `--prep-dir` → the prep-free bytes, no `R/prep/` dir.
    # `_golden` is pinned to `ANGLES` (a `sonnet` finder `load_angles` refuses),
    # so the reference is `prepare(..., prep_dir=None)` on the same angles.
    plain = tmp_path / "plain"
    prow = plain / "proof"
    assert rs.main(["prepare", "--root", str(prow), "--pr-url", PR, "--base", BASE,
                    "--head", HEAD, "--effort", EFFORT, "--state", str(prow / STATE),
                    "--log", str(prow / LOG), "--config", str(cfg_path),
                    "--rulings", "r.md"]) == 0
    rp = prow / "rounds" / "42" / "r1"
    assert not (rp / "prep").exists()

    ref = tmp_path / "ref"
    rroot = ref / "proof"
    rr = rs.prepare(rroot, PR, declared, base=pbase, head=HEAD, effort=EFFORT,
                    state_path=str(rroot / STATE), log_path=str(rroot / LOG),
                    now=NOW, prep_dir=None, meta=pmeta)
    ref_text = (rr / "angles.json").read_text(encoding="utf-8")
    plain_text = (rp / "angles.json").read_text(encoding="utf-8")
    for re_, pe in zip(json.loads(ref_text)["angles"], json.loads(plain_text)["angles"]):
        ref_text = ref_text.replace(re_["exec_dir"], pe["exec_dir"])  # random mkdtemp
    assert ref_text.replace(str(rroot), str(prow)) == plain_text

    # Fail-open through the CLI: a missing prep dir never refuses the round.
    nope = tmp_path / "nope"
    assert rs.main(["prepare", "--root", str(nope / "proof"), "--pr-url", PR,
                    "--base", BASE, "--head", HEAD, "--effort", EFFORT,
                    "--state", str(nope / "proof" / STATE), "--log", str(nope / "proof" / LOG),
                    "--config", str(cfg_path), "--prep-dir", str(tmp_path / "missing-W"),
                    "--rulings", "r.md"]) == 0
