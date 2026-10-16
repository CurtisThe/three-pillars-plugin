"""test_kill_guard_heredoc.py — the kill guard's two modelled heredoc shapes.

design: no-kill-by-name (PR #237 review round 1). A quoted `$(cat <<'EOF' …)`
commit message or PR body that mentions a kill word is data and is allowed; a
script the same command writes from a heredoc and then runs is scanned. Payloads
and fixture strings only: no process is started or killed by these tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))

import kill_guard_hook as hook  # noqa: E402


def _decision(command, cwd):
    out, rc = hook.run({"tool_name": "Bash", "tool_input": {"command": command},
                        "cwd": str(cwd)})
    assert rc == 0
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"


def _hd(body):
    return "\"$(cat <<'EOF'\n%s\nEOF\n)\"" % body


@pytest.mark.parametrize("command", [
    "git commit -m " + _hd("fix: document why pkill -x claude is refused"),
    "gh pr create --title t --body " + _hd("## Summary\n- refuse killall and pkill"),
    "python3 \"$GHPA\" create --context manual -- --base master --head tp/x "
    "--title \"Complete design: x\" --body " + _hd("The guard refuses pgrep | xargs kill."),
])
def test_message_heredoc_mentioning_a_kill_word_is_allowed(command, tmp_path):
    assert _decision(command, tmp_path) == "allow"


@pytest.mark.parametrize("command", [
    "git commit -m " + _hd("fix") + " && pkill -x claude",
    "bash -c " + _hd("pkill -x claude"),
    "$(cat <<'EOF'\npkill -x claude\nEOF\n)",
    "python3 -c " + _hd("import os; os.system('pkill claude')"),
    "echo " + _hd("import os; os.system('pkill claude')") + " | python3",
    "C=$(cat <<'EOF'\npkill -x claude\nEOF\n); $C",
    "git commit -m \"$(cat <<EOF\nfix pkill\nEOF\n)\"",  # unquoted: the body expands
])
def test_heredoc_that_can_run_as_code_still_fails_closed(command, tmp_path):
    assert _decision(command, tmp_path) == "deny"


@pytest.mark.parametrize("command", [
    "cat > t.py <<'EOF'\nimport subprocess\nsubprocess.run([\"pkill\", \"-x\", \"claude\"])\n"
    "EOF\npython3 t.py",
    "cat <<'EOF' > t.sh\npkill -x claude\nEOF\nbash t.sh",
    "tee t.sh >/dev/null <<'EOF'\nkillall node\nEOF\nchmod +x t.sh && ./t.sh",
])
def test_script_written_and_run_in_one_command_is_denied(command, tmp_path):
    assert _decision(command, tmp_path) == "deny"


def test_written_body_is_scanned_even_over_a_clean_file_on_disk(tmp_path):
    (tmp_path / "t.py").write_text("print('old')\n", encoding="utf-8")
    command = ("cat > t.py <<'EOF'\nimport subprocess\nsubprocess.run([\"pkill\", \"x\"])\n"
               "EOF\npython3 t.py")
    assert _decision(command, tmp_path) == "deny"


@pytest.mark.parametrize("command", [
    "cat > fixture.txt <<'EOF'\npkill -x claude\nEOF\nls",
    "cat > t.py <<'EOF'\nCASES = ['pkill -x claude']\nprint(CASES)\nEOF\npython3 t.py",
])
def test_written_data_that_is_not_a_kill_is_allowed(command, tmp_path):
    assert _decision(command, tmp_path) == "allow"


def test_an_unparseable_source_does_not_drop_a_later_hit(tmp_path):
    (tmp_path / "bad.py").write_text('print "kill me"\n', encoding="utf-8")
    command = "python3 -c 'import os; os.kill(-1, 9)'; python3 bad.py"
    assert _decision(command, tmp_path) == "deny"
    command = "python3 bad.py; python3 -c 'import os; os.kill(-1, 9)'"
    assert _decision(command, tmp_path) == "deny"
