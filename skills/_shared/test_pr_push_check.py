"""pr_push_check: a push to a merged PR is skipped; every other state or failure pushes."""
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import forge  # noqa: E402
import pr_push_check  # noqa: E402

URL = "https://github.com/o/r/pull/42"


def _stub(state):
    seen = []

    def _read(repo, number):
        seen.append(number)
        return forge.Result.ok({"number": number, "head": "b", "head_sha": "s",
                                "state": state, "url": URL})
    _read.seen = seen
    return _read


def test_merged_skips_push_case_insensitive():
    for state in ("MERGED", "merged"):
        stub = _stub(state)
        rc, line = pr_push_check.check(".", URL, pr_read=stub)
        assert rc == 1, (
            f"PR #42 merged expected to skip the push for state {state!r}: rc={rc!r} line={line!r}")
        assert line == "PR #42 merged: push skipped, tail left for the seat", (
            f"PR #42 merged line wrong for state {state!r}: {line!r}")
        assert stub.seen == [42], (
            f"PR #42 merged check read PRs {stub.seen!r} for state {state!r}")


def test_open_and_closed_push_silently():
    for state in ("OPEN", "CLOSED", "open"):
        assert pr_push_check.check(".", URL, pr_read=_stub(state)) == (0, "")


def test_degraded_result_pushes_with_reason():
    def _read(repo, number):
        return forge.Result.degraded("unsupported forge")
    rc, line = pr_push_check.check(".", URL, pr_read=_read)
    assert rc == 0
    assert line == "PR state unknown (unsupported forge): pushing"


def test_malformed_url_exits_2_via_cli():
    r = subprocess.run([sys.executable, str(_HERE / "pr_push_check.py"), "--repo", ".",
                        "--pr-url", "https://github.com/o/r/pull/abc"],
                       capture_output=True, text=True)
    assert r.returncode == 2
