"""Tests for allowlist_mine: per-prefix calls and denials from transcripts, deny set screened out."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from allowlist_mine import main, mine, render  # noqa: E402

DENY1 = ("Permission for this action was denied by the Claude Code auto mode classifier. "
         "Reason: [Modify Shared Resources].")
DENY2 = ("Permission for this action was denied by the Claude Code auto mode classifier. "
         "Reason: Blocked by classifier.")
RULING = 'python3 "$TP_ROOT"/skills/_shared/ruling_cli.py show x --token SECRET123'
HEREDOC = "git commit -m \"$(cat <<'EOF'\nfeat: x\nrm -rf y\nEOF\n)\""


def _transcript(path, calls):
    recs = []
    for n, (cmd, text, is_err) in enumerate(calls):
        name, inp = ("Bash", {"command": cmd}) if cmd != "Write" else ("Write", {"file_path": "/var/x"})
        recs.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{n}", "name": name, "input": inp}]}})
        recs.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{n}", "is_error": is_err, "content": text}]}})
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return str(path)


def _fixture(tmp_path):
    f1 = _transcript(tmp_path / "a.jsonl",
                     [("git status", "ok", False)] * 3
                     + [(RULING, DENY1, False), (RULING, "ok", False)]
                     + [("gh pr merge 5", DENY1, False)] * 2 + [("gh pr merge 5", "ok", False)] * 4)
    f2 = _transcript(tmp_path / "b.jsonl", [
        ("TP_ROOT=/xyzzy python3 skills/_shared/launch_design_run.py y", DENY2, False),
        ("git -C /home/u/r-wt/q status", "ok", False),
        ("git fetch origin", "fatal: Permission denied (publickey)", True),
        ('rm "unterminated', "ok", False),
        (HEREDOC, "ok", False),
        ("Write", DENY1, False)])
    return [f1, f2]


def test_counts_per_prefix(tmp_path):
    r = mine(_fixture(tmp_path))
    by = {e["prefix"]: e for e in r["prefixes"]}
    e = by["python3 skills/_shared/ruling_cli.py"]
    assert (e["calls"], e["denials"], e["framework"]) == (2, 1, True)
    assert (by["git status"]["calls"], by["git status"]["denials"]) == (3, 0)
    fw = [e["framework"] for e in r["prefixes"]]
    assert fw == sorted(fw, reverse=True)


def test_every_denial_listed_with_reason(tmp_path):
    d = mine(_fixture(tmp_path))["denials"]
    assert {"prefix": "python3 skills/_shared/ruling_cli.py", "reason": "Modify Shared Resources"} in d
    assert {"prefix": "python3 skills/_shared/launch_design_run.py", "reason": "Blocked by classifier"} in d
    assert {"prefix": "Write", "reason": "Modify Shared Resources"} in d
    assert not any(x["prefix"] == "git fetch" for x in d)


def test_deny_set_never_in_output(tmp_path):
    r = mine(_fixture(tmp_path))
    assert "merge" not in json.dumps(r)
    assert "merge" not in render(r)
    assert r["screened"] == {"calls": 6, "denials": 2}


def test_unparseable_never_a_candidate(tmp_path):
    r = mine(_fixture(tmp_path))
    assert r["unparseable"] == {"calls": 2, "denials": 0}
    assert "rm" not in json.dumps(r["prefixes"])
    cand = render(r).split("candidates")[1].split("denials")[0]
    assert "rm" not in cand
    assert "feat" not in json.dumps(r)


def test_env_prefixed_and_git_c_reported_apart(tmp_path):
    r = mine(_fixture(tmp_path))
    assert r["env_prefixed"] == [
        {"prefix": "python3 skills/_shared/launch_design_run.py", "calls": 1, "denials": 1}]
    assert r["git_c"] == [{"prefix": "git -C status", "calls": 1, "denials": 0}]
    names = [e["prefix"] for e in r["prefixes"]]
    assert "git -C status" not in names
    assert "python3 skills/_shared/launch_design_run.py" not in names


def test_root_forms_counted(tmp_path):
    assert mine(_fixture(tmp_path))["root_forms"] == {"tp-root-text": 2, "relative": 1}


def test_denial_regex_override(tmp_path, capsys):
    f = _fixture(tmp_path)
    assert main(["--transcripts", f[0], "--transcripts", f[1],
                 "--denial-regex", "NOPE", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["denials"] == []


def test_no_raw_args_in_output(tmp_path):
    r = mine(_fixture(tmp_path))
    for text in (json.dumps(r), render(r)):
        for raw in ("SECRET123", "/home/u/r-wt/q", "xyzzy"):
            assert raw not in text


def test_prefix_with_screened_args_dropped(tmp_path):
    f = _transcript(tmp_path / "c.jsonl",
                    [("python3 skills/_shared/x.py", "ok", False)] * 2
                    + [("python3 skills/_shared/x.py --force", "ok", False)])
    r = mine([f])
    assert not any(e["prefix"] == "python3 skills/_shared/x.py" for e in r["prefixes"])
    assert r["screened"]["calls"] == 3


def test_zero_denials_note(tmp_path):
    f = _transcript(tmp_path / "d.jsonl", [("git status", "ok", False)])
    assert "note: no denial matched DENIAL_RE" in render(mine([f]))


def test_main_json_flag(tmp_path, capsys):
    _fixture(tmp_path)
    assert main(["--transcripts", str(tmp_path / "*.jsonl"), "--json"]) == 0
    assert "prefixes" in json.loads(capsys.readouterr().out)
