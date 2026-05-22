"""Tests for skills/tp-run-full-design/scripts/run_tier_3_5.py.

The wrapper is invoked via stdin JSON and emits a single-line JSON
envelope on stdout. Tests run the wrapper as a Python module (rather than
shelling out) so subprocess.run can be monkeypatched on the module
itself — per detailed-design §Interfaces "subprocess monkeypatch is
preferred over PATH-shim".
"""
from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))


WORKER_SHA = "a1b2c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d"
WORKER_BRANCH = "candidate/demo-slug/single"


def _well_formed_worker_response(
    *,
    candidate_id: str = "single",
    branch: str = WORKER_BRANCH,
    sha: str = WORKER_SHA,
    omit: tuple[str, ...] = (),
    schema: str = "tp-run-full-design/candidate/v1",
) -> str:
    body = {
        "schema": schema,
        "candidate_id": candidate_id,
        "branch": branch,
        "sha": sha,
        "summary": "Demo candidate.",
        "test_results": {"passed": 3, "failed": 0, "skipped": 0, "raw": "3 passed"},
        "telemetry": {"duration_ms": 1200, "tokens_used": 5000, "tool_calls": 9},
    }
    for key in omit:
        body.pop(key, None)
    return f"scratch text\n\n```json\n{json.dumps(body)}\n```\n"


def _stdin_json(
    design_dir: Path,
    worktree_path: Path | None,
    *,
    candidate_id: str = "single",
    slug: str = "demo-slug",
    worker_response: str | None = None,
) -> str:
    return json.dumps(
        {
            "worker_response": worker_response or _well_formed_worker_response(candidate_id=candidate_id),
            "agent_meta": {
                "agentId": "agent-demo",
                "worktreePath": str(worktree_path) if worktree_path else None,
            },
            "design_dir": str(design_dir),
            "candidate_id": candidate_id,
            "slug": slug,
        }
    )


def test_happy_path_envelope(tmp_path):
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    stdin_text = _stdin_json(design_dir, worktree_path)

    ls_remote_stdout = f"{WORKER_SHA}\trefs/heads/{WORKER_BRANCH}\n".encode()

    # We need to also monkeypatch cleanup_worker_worktree to avoid actual
    # git worktree calls. The wrapper composes parse → write → cleanup →
    # git ls-remote. The cleanup helper itself calls subprocess.run; for
    # this test we want the worktree removal to no-op.
    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    ls_remote_calls: list = []
    cleanup_calls: list = []

    def fake_run(cmd, **kwargs):
        # First call(s) come from cleanup_worker_worktree (git worktree remove).
        # The ls-remote happens at the very end.
        if "ls-remote" in cmd:
            ls_remote_calls.append(cmd)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=ls_remote_stdout, stderr=b"")
        # The cleanup helper's git worktree remove — pretend it succeeds.
        cleanup_calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    stdout_buf = io.StringIO()
    with patch.object(run_tier_3_5.subprocess, "run", side_effect=fake_run):
        # cleanup_worker_worktree imports subprocess separately — patch its
        # subprocess too so the wrapper's git worktree call goes through fake_run.
        import cleanup_worker_worktree as cww
        with patch.object(cww.subprocess, "run", side_effect=fake_run):
            with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
                with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
                    try:
                        exit_code = run_tier_3_5.main()
                    except SystemExit as exc:
                        exit_code = exc.code

    output = stdout_buf.getvalue().strip()
    envelope = json.loads(output)

    assert exit_code == 0, f"happy path should exit 0; got {exit_code}, envelope={envelope!r}"
    assert envelope == {
        "status": "ok",
        "case": None,
        "event_token": "ok",
        "detail": None,
    }, f"unexpected envelope: {envelope!r}"

    # Four candidate artifact files written.
    candidate_dir = design_dir / "candidates" / "single"
    for name in ("branch.txt", "summary.md", "test-results.json", "telemetry.json"):
        assert (candidate_dir / name).exists(), f"missing artifact: {name}"

    # ls-remote was called exactly once with the expected branch ref.
    assert len(ls_remote_calls) == 1, f"expected exactly 1 ls-remote call, got {ls_remote_calls!r}"
    assert ls_remote_calls[0][:3] == ["git", "ls-remote", "origin"]
    assert WORKER_BRANCH in ls_remote_calls[0][-1] or ls_remote_calls[0][-1] == WORKER_BRANCH


@pytest.mark.parametrize(
    "case_id, worker_response, worktree_path_arg, ls_remote_stdout, expected_case, expected_token_prefix, expected_exit",
    [
        # Case (a): worker-noop — worktreePath is None.
        ("a", None, None, b"", "a", "worker-noop", 2),
        # Case (b): no fenced JSON block in worker_response.
        ("b", "Just some prose; no JSON block here.", "worktree", b"", "b", "no-candidate-block", 2),
        # Case (e): ls-remote returns a different SHA than parsed.
        ("e", None, "worktree",
         f"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\trefs/heads/{WORKER_BRANCH}\n".encode(),
         "e", "sha-mismatch", 2),
    ],
)
def test_non_retryable_failures(
    tmp_path, case_id, worker_response, worktree_path_arg, ls_remote_stdout,
    expected_case, expected_token_prefix, expected_exit,
):
    design_dir = tmp_path / "design"
    design_dir.mkdir()

    if worktree_path_arg is None:
        worktree_path = None
    else:
        worktree_path = tmp_path / worktree_path_arg
        worktree_path.mkdir()

    stdin_text = _stdin_json(
        design_dir,
        worktree_path,
        worker_response=worker_response,
    )

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    def fake_run(cmd, **kwargs):
        if "ls-remote" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=ls_remote_stdout, stderr=b"")
        # cleanup git worktree remove — succeed.
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    stdout_buf = io.StringIO()
    import cleanup_worker_worktree as cww
    with patch.object(run_tier_3_5.subprocess, "run", side_effect=fake_run):
        with patch.object(cww.subprocess, "run", side_effect=fake_run):
            with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
                with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
                    try:
                        exit_code = run_tier_3_5.main()
                    except SystemExit as exc:
                        exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == expected_exit, (
        f"case ({case_id}): expected exit {expected_exit}, got {exit_code}; envelope={envelope!r}"
    )
    assert envelope["status"] == "escalate", (
        f"case ({case_id}): status should be escalate; got {envelope!r}"
    )
    assert envelope["case"] == expected_case, (
        f"case ({case_id}): envelope case mismatch; got {envelope!r}"
    )
    assert envelope["event_token"].startswith(expected_token_prefix), (
        f"case ({case_id}): event_token should start with {expected_token_prefix!r}; got {envelope!r}"
    )


def test_stdin_malformed_json_escalates(tmp_path):
    """If stdin is not valid JSON, the wrapper must escalate (exit 2),
    not crash with Python's default exit 1 (case-c retry collision).
    event_token = 'stdin-invalid', case = None."""
    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    stdout_buf = io.StringIO()
    with patch.object(run_tier_3_5.sys, "stdin", io.StringIO("not-json{")):
        with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
            try:
                exit_code = run_tier_3_5.main()
            except SystemExit as exc:
                exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2, (
        f"malformed stdin must exit 2 (escalate), not 1 (retry); "
        f"got {exit_code}; envelope={envelope!r}"
    )
    assert envelope["status"] == "escalate"
    assert envelope["case"] is None
    assert envelope["event_token"] == "stdin-invalid"
    assert "JSONDecodeError" in envelope["detail"]


def test_stdin_missing_required_key_escalates(tmp_path):
    """Missing top-level required keys (design_dir, slug) must escalate
    with event_token 'stdin-invalid', not exit 1."""
    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    # Valid JSON, but missing both `design_dir` and `slug`.
    stdin_text = json.dumps({"worker_response": "irrelevant", "agent_meta": {}})

    stdout_buf = io.StringIO()
    with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
        with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
            try:
                exit_code = run_tier_3_5.main()
            except SystemExit as exc:
                exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2
    assert envelope["status"] == "escalate"
    assert envelope["case"] is None
    assert envelope["event_token"] == "stdin-invalid"
    assert "KeyError" in envelope["detail"]


def test_agent_meta_missing_escalates_stdin_invalid(tmp_path):
    """A missing `agent_meta` key is a stdin contract violation (the
    orchestrator failed to wire the field), NOT case (a) worker-noop —
    which is reserved for the orchestrator explicitly signaling
    'worker didn't run' via worktreePath: null inside agent_meta."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()

    stdin_text = json.dumps(
        {
            "worker_response": "irrelevant",
            "design_dir": str(design_dir),
            "candidate_id": "single",
            "slug": "demo-slug",
        }
    )

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    stdout_buf = io.StringIO()
    with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
        with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
            try:
                exit_code = run_tier_3_5.main()
            except SystemExit as exc:
                exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2
    assert envelope["status"] == "escalate"
    assert envelope["case"] is None, (
        f"missing agent_meta is contract violation, NOT case a; got {envelope!r}"
    )
    assert envelope["event_token"] == "stdin-invalid"
    assert "agent_meta" in envelope["detail"]


def test_worktree_path_key_missing_escalates_stdin_invalid(tmp_path):
    """If `agent_meta` is present but lacks a `worktreePath` key entirely,
    that's a stdin contract violation — NOT case (a) worker-noop. Case
    (a) requires the orchestrator to explicitly set worktreePath=null."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()

    stdin_text = json.dumps(
        {
            "worker_response": "irrelevant",
            "agent_meta": {"agentId": "agent-demo"},  # no worktreePath at all
            "design_dir": str(design_dir),
            "candidate_id": "single",
            "slug": "demo-slug",
        }
    )

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    stdout_buf = io.StringIO()
    with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
        with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
            try:
                exit_code = run_tier_3_5.main()
            except SystemExit as exc:
                exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2
    assert envelope["status"] == "escalate"
    assert envelope["case"] is None, (
        f"missing worktreePath key is contract violation, NOT case a; got {envelope!r}"
    )
    assert envelope["event_token"] == "stdin-invalid"
    assert "worktreePath" in envelope["detail"]


@pytest.mark.parametrize(
    "agent_meta_value",
    [
        "not-a-dict",       # string
        ["list", "of", "things"],  # list
        42,                 # int
    ],
)
def test_agent_meta_non_dict_escalates(tmp_path, agent_meta_value):
    """agent_meta must be a dict. A non-dict value (string, list, int)
    would crash downstream `.get()` / `["worktreePath"]` access outside
    the stdin guard, exit 1 by default — case-c retry collision. Reject
    inside the guard with event_token=stdin-invalid."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()

    stdin_text = json.dumps(
        {
            "worker_response": "irrelevant",
            "agent_meta": agent_meta_value,
            "design_dir": str(design_dir),
            "candidate_id": "single",
            "slug": "demo-slug",
        }
    )

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    stdout_buf = io.StringIO()
    with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
        with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
            try:
                exit_code = run_tier_3_5.main()
            except SystemExit as exc:
                exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2, (
        f"non-dict agent_meta must exit 2; got {exit_code}; envelope={envelope!r}"
    )
    assert envelope["status"] == "escalate"
    assert envelope["case"] is None
    assert envelope["event_token"] == "stdin-invalid"
    assert "agent_meta must be an object" in envelope["detail"]


@pytest.mark.parametrize(
    "worker_response_value, should_escalate",
    [
        # Literal null in stdin — coerced to "" so parser sees empty
        # input and returns case (b) no-candidate-block, NOT stdin-invalid.
        (None, False),
        # Non-string truthy values (number, list, dict) are contract
        # violations and must escalate as stdin-invalid before reaching
        # the parser.
        (42, True),
        (["array"], True),
        ({"obj": True}, True),
    ],
)
def test_worker_response_type_validation(
    tmp_path, worker_response_value, should_escalate,
):
    """worker_response must be a string. `null` is coerced to ""
    (lenient — parser handles empty input). Non-string truthy values
    must escalate stdin-invalid before the parser sees them."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    stdin_text = json.dumps(
        {
            "worker_response": worker_response_value,
            "agent_meta": {"agentId": "agent-demo", "worktreePath": str(worktree_path)},
            "design_dir": str(design_dir),
            "candidate_id": "single",
            "slug": "demo-slug",
        }
    )

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    stdout_buf = io.StringIO()
    import cleanup_worker_worktree as cww
    with patch.object(run_tier_3_5.subprocess, "run", side_effect=fake_run):
        with patch.object(cww.subprocess, "run", side_effect=fake_run):
            with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
                with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
                    try:
                        exit_code = run_tier_3_5.main()
                    except SystemExit as exc:
                        exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2, f"all bad inputs must exit 2; got {envelope!r}"
    if should_escalate:
        assert envelope["event_token"] == "stdin-invalid"
        assert "worker_response must be a string" in envelope["detail"]
    else:
        # Null coerced to "" → parser returns case (b) no-candidate-block.
        assert envelope["event_token"] == "no-candidate-block", (
            f"null worker_response should be coerced to empty string and "
            f"reach the parser as case (b); got {envelope!r}"
        )


@pytest.mark.parametrize(
    "worktree_value, expected_event_token, expected_case",
    [
        # Empty string is treated leniently as case (a) — no real worktree.
        ("", "worker-noop", "a"),
        # Relative paths and non-string values must escalate to prevent
        # `cleanup_worker_worktree` from running git worktree remove
        # against the repo itself (Path(".") resolves to cwd).
        (".", "invalid-worktree-path", None),
        ("relative/path", "invalid-worktree-path", None),
        (42, "invalid-worktree-path", None),
        ({"not": "a string"}, "invalid-worktree-path", None),
    ],
)
def test_worktree_path_validation(
    tmp_path, worktree_value, expected_event_token, expected_case,
):
    """Defensively reject non-absolute/non-string worktreePath values."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()

    stdin_text = json.dumps(
        {
            "worker_response": _well_formed_worker_response(),
            "agent_meta": {"agentId": "agent-demo", "worktreePath": worktree_value},
            "design_dir": str(design_dir),
            "candidate_id": "single",
            "slug": "demo-slug",
        }
    )

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    stdout_buf = io.StringIO()
    with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
        with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
            try:
                exit_code = run_tier_3_5.main()
            except SystemExit as exc:
                exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2, f"worktree value {worktree_value!r} must escalate; got {envelope!r}"
    assert envelope["status"] == "escalate"
    assert envelope["case"] == expected_case
    assert envelope["event_token"] == expected_event_token


def test_ls_remote_nonzero_returncode_escalates_sha_check_failed(tmp_path):
    """If `git ls-remote` returns non-zero (auth, network, unknown remote)
    without raising, the wrapper must classify as sha-check-failed
    (wrapper-internal), NOT sha-mismatch (case e). Operational failures
    must not be misattributed to the worker."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    stdin_text = _stdin_json(design_dir, worktree_path)

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    def fake_run(cmd, **kwargs):
        if "ls-remote" in cmd:
            return subprocess.CompletedProcess(
                args=cmd, returncode=128,
                stdout=b"", stderr=b"fatal: could not read Username for 'https://github.com': No such device or address",
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    stdout_buf = io.StringIO()
    import cleanup_worker_worktree as cww
    with patch.object(run_tier_3_5.subprocess, "run", side_effect=fake_run):
        with patch.object(cww.subprocess, "run", side_effect=fake_run):
            with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
                with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
                    try:
                        exit_code = run_tier_3_5.main()
                    except SystemExit as exc:
                        exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2
    assert envelope["status"] == "escalate"
    assert envelope["case"] is None, (
        f"non-zero returncode must NOT be classified as case e; got {envelope!r}"
    )
    assert envelope["event_token"] == "sha-check-failed"
    assert "exited 128" in envelope["detail"]
    assert "could not read Username" in envelope["detail"]


def test_artifact_write_failure_escalates(tmp_path):
    """If write_candidate_artifacts raises, the wrapper must escalate (exit
    2) — not crash with the Python default exit 1, which is reserved for
    case (c) retry. event_token = 'artifact-write-failed', case = None."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    stdin_text = _stdin_json(design_dir, worktree_path)

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    def raising_write(**kwargs):
        raise OSError("disk full")

    stdout_buf = io.StringIO()
    with patch.object(run_tier_3_5, "write_candidate_artifacts", side_effect=raising_write):
        with patch.object(run_tier_3_5.subprocess, "run", side_effect=fake_run):
            with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
                with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
                    try:
                        exit_code = run_tier_3_5.main()
                    except SystemExit as exc:
                        exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2, (
        f"artifact-write failure must exit 2 (escalate), not 1 (retry); "
        f"got {exit_code}; envelope={envelope!r}"
    )
    assert envelope["status"] == "escalate"
    assert envelope["case"] is None, (
        f"wrapper-internal failure must have case=None to avoid colliding "
        f"with the a/b/c/e enum; got {envelope!r}"
    )
    assert envelope["event_token"] == "artifact-write-failed"
    assert "OSError" in envelope["detail"]
    assert "disk full" in envelope["detail"]


def test_cleanup_failure_escalates(tmp_path):
    """If cleanup_worker_worktree raises (lock-held retries are internal to
    the helper and self-log; an exception bubbling out means the retry was
    exhausted or the error was non-lock-held), the wrapper must escalate
    with exit 2, not exit 1."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    stdin_text = _stdin_json(design_dir, worktree_path)

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    def raising_cleanup(**kwargs):
        raise RuntimeError("worktree path vanished")

    stdout_buf = io.StringIO()
    with patch.object(run_tier_3_5, "cleanup_worker_worktree", side_effect=raising_cleanup):
        with patch.object(run_tier_3_5.subprocess, "run", side_effect=fake_run):
            with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
                with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
                    try:
                        exit_code = run_tier_3_5.main()
                    except SystemExit as exc:
                        exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2, (
        f"cleanup failure must exit 2 (escalate), not 1 (retry); "
        f"got {exit_code}; envelope={envelope!r}"
    )
    assert envelope["status"] == "escalate"
    assert envelope["case"] is None
    assert envelope["event_token"] == "cleanup-failed"
    assert "RuntimeError" in envelope["detail"]
    assert "worktree path vanished" in envelope["detail"]


def test_sha_check_subprocess_failure_escalates(tmp_path):
    """If git ls-remote itself raises (network error, git binary missing,
    decode failure), the wrapper must escalate with exit 2, not exit 1."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    stdin_text = _stdin_json(design_dir, worktree_path)

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    def fake_run(cmd, **kwargs):
        if "ls-remote" in cmd:
            raise FileNotFoundError("git: command not found")
        # cleanup git worktree remove — succeed.
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    stdout_buf = io.StringIO()
    import cleanup_worker_worktree as cww
    with patch.object(run_tier_3_5.subprocess, "run", side_effect=fake_run):
        with patch.object(cww.subprocess, "run", side_effect=fake_run):
            with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
                with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
                    try:
                        exit_code = run_tier_3_5.main()
                    except SystemExit as exc:
                        exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 2, (
        f"sha-check subprocess failure must exit 2 (escalate), not 1 (retry); "
        f"got {exit_code}; envelope={envelope!r}"
    )
    assert envelope["status"] == "escalate"
    assert envelope["case"] is None
    assert envelope["event_token"] == "sha-check-failed"
    assert "FileNotFoundError" in envelope["detail"]
    assert "git ls-remote" in envelope["detail"]


def test_retryable_failure(tmp_path):
    """Case (c): SchemaValidationError. The worker response includes the
    canonical v1 schema key but omits a required field (sha)."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    worker_response = _well_formed_worker_response(omit=("sha",))
    # Verify the schema field is the canonical v1 string (otherwise this
    # test would trip UnknownSchemaVersionError → case (b) instead).
    body = json.loads(worker_response.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert body["schema"] == "tp-run-full-design/candidate/v1", (
        "fixture must pin the canonical schema string"
    )

    stdin_text = _stdin_json(design_dir, worktree_path, worker_response=worker_response)

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    stdout_buf = io.StringIO()
    import cleanup_worker_worktree as cww
    with patch.object(run_tier_3_5.subprocess, "run", side_effect=fake_run):
        with patch.object(cww.subprocess, "run", side_effect=fake_run):
            with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
                with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
                    try:
                        exit_code = run_tier_3_5.main()
                    except SystemExit as exc:
                        exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 1, f"retryable should exit 1, got {exit_code}; envelope={envelope!r}"
    assert envelope["status"] == "retry", f"status should be retry; got {envelope!r}"
    assert envelope["case"] == "c", f"case should be 'c'; got {envelope!r}"
    assert envelope["event_token"] == "schema-validation-error", (
        f"event_token mismatch; got {envelope!r}"
    )
