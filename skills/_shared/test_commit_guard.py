"""test_commit_guard.py — `commit_guard.apply` install (Task 5.3).

The commit guard lands a versioned sentinel block right after the shebang of
`pre-commit` and `commit-msg`, keeps every foreign line byte-identical, is
idempotent, rewrites a stale block in place, and refuses non-executable or
non-shell hooks without touching them. `record_tp_root` writes the
`<git-common-dir>/three-pillars/tp-root` pointer; `commit_guard_settings`
merges the `--no-verify` deny rules into `.claude/settings.json` idempotently
and never removes user entries; `apply` persists the opted-in sub-asks and
`applied_at` through `repo_config_load.update_config`.

House rules: real tmp_path git repos, GIT_* env scrubbed, HOME isolated,
`{"schema_version": 1}` committed first. Stdlib + pytest only; shipped test.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV.update({
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
})


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME: apply() runs git through
    subprocess with the ambient os.environ."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, env=CLEAN_ENV,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _commit_config_first(repo: Path) -> None:
    (repo / ".three-pillars").mkdir(parents=True)
    (repo / ".three-pillars" / "config.json").write_text(
        '{"schema_version": 1}\n', encoding="utf-8")
    _git(["add", ".three-pillars/config.json"], repo)
    _git(["commit", "-q", "-m", "seed config"], repo)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    _commit_config_first(repo)
    return repo


def _hooks_dir(repo: Path) -> Path:
    raw = subprocess.run(["git", "-C", str(repo), "rev-parse",
                          "--path-format=absolute", "--git-path", "hooks"],
                         check=True, capture_output=True, text=True,
                         env=CLEAN_ENV).stdout.strip()
    return Path(raw)


def _config(repo: Path) -> dict:
    return json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))


def _guard(repo: Path):
    from skills._shared import commit_guard  # noqa: PLC0415
    commit_guard.apply(str(repo))


def _begin_marker() -> str:
    from skills._shared import commit_guard  # noqa: PLC0415
    return f"# three-pillars: commit-guard BEGIN v{commit_guard.BODY_VERSION}\n"


def _end_marker() -> str:
    return "# three-pillars: commit-guard END\n"


def test_absent_hooks_created_with_shebang_block_and_executable(tmp_path):
    from skills._shared import commit_guard  # noqa: PLC0415
    repo = _repo(tmp_path)
    commit_guard.apply(str(repo))
    hooks = _hooks_dir(repo)
    for name in ("pre-commit", "commit-msg"):
        hook = hooks / name
        assert hook.exists(), f"{name} not created"
        assert os.access(str(hook), os.X_OK), f"{name} not executable"
        text = hook.read_text(encoding="utf-8")
        assert text.splitlines()[0] == "#!/bin/sh"
        assert _begin_marker() in text
        assert _end_marker() in text
        assert f'_tp_commit_guard {name} "$@" || exit $?' in text


def test_foreign_hooks_keep_every_foreign_line_block_after_shebang(tmp_path):
    from skills._shared import commit_guard  # noqa: PLC0415
    repo = _repo(tmp_path)
    hooks = _hooks_dir(repo)
    cases = {
        "pre-commit": ("#!/bin/sh", "# user note: first line\n"
                                   "echo user-hook-ran\n"
                                   "test -s \"$1\" 2>/dev/null || true\n"),
        "commit-msg": ("#!/usr/bin/env bash", "# user note\n"
                                             "echo $1 > /dev/null\n"),
    }
    for name, (shebang, body) in cases.items():
        (hooks / name).write_text(shebang + "\n" + body, encoding="utf-8")
        (hooks / name).chmod(0o755)
    commit_guard.apply(str(repo))
    for name, (shebang, body) in cases.items():
        text = (hooks / name).read_text(encoding="utf-8")
        # the block sits right after the shebang, before the foreign lines:
        # an `exec`/`exit` foreign hook never returns to an appended block
        assert text.startswith(shebang + "\n" + _begin_marker()), name
        assert text.endswith(body), name
        assert os.access(str(hooks / name), os.X_OK)


def test_hook_ending_in_exec_gets_the_block_before_it(tmp_path):
    repo = _repo(tmp_path)
    hooks = _hooks_dir(repo)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    _guard(repo)
    text = (hooks / "pre-commit").read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n" + _begin_marker())
    assert text.endswith("exec true\n")
    assert text.index(_end_marker()) < len(text) - len("exec true\n")


def test_current_sentinel_is_a_no_op(tmp_path):
    from skills._shared import commit_guard  # noqa: PLC0415
    repo = _repo(tmp_path)
    _guard(repo)
    hooks = _hooks_dir(repo)
    before = {n: (hooks / n).read_bytes() for n in ("pre-commit", "commit-msg")}
    modes = {n: (hooks / n).stat().st_mode for n in before}
    _guard(repo)  # second apply: idempotent
    for n in before:
        assert (hooks / n).read_bytes() == before[n], f"{n} changed by re-apply"
        assert (hooks / n).stat().st_mode == modes[n], f"{n} mode changed by re-apply"


def test_stale_block_replaced_in_place_foreign_lines_kept(tmp_path):
    repo = _repo(tmp_path)
    hooks = _hooks_dir(repo)
    for name, body in (("pre-commit", "echo a\n"), ("commit-msg", "echo b\n")):
        hook = hooks / name
        hook.write_text("#!/bin/sh\n"
                        "# three-pillars: commit-guard BEGIN v999999\n"
                        "# stale guard body\n"
                        "# three-pillars: commit-guard END\n"
                        + body, encoding="utf-8")
        hook.chmod(0o755)
    _guard(repo)
    for name in ("pre-commit", "commit-msg"):
        lines = (hooks / name).read_text(encoding="utf-8").splitlines()
        assert "stale guard body" not in lines
        assert f"BEGIN v{999999}" not in "\n".join(lines)
        assert "commit-guard BEGIN" in lines[1]
        assert "commit-guard END" in lines[-2]
        assert lines[-1] == ("echo a" if name == "pre-commit" else "echo b")


def test_non_executable_hook_refused_mode_untouched(tmp_path):
    from skills._shared import commit_guard  # noqa: PLC0415
    repo = _repo(tmp_path)
    hooks = _hooks_dir(repo)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho off\n", encoding="utf-8")
    hook.chmod(0o644)
    with pytest.raises(commit_guard.Refused):
        commit_guard.apply(str(repo))
    assert (hooks / "pre-commit").read_text(encoding="utf-8") == "#!/bin/sh\necho off\n"
    assert (hooks / "pre-commit").stat().st_mode & 0o111 == 0
    assert not (hooks / "commit-msg").exists(), "no hook may be written"


def test_non_shell_shebang_refused(tmp_path):
    from skills._shared import commit_guard  # noqa: PLC0415
    repo = _repo(tmp_path)
    hooks = _hooks_dir(repo)
    hook = hooks / "pre-commit"
    hook.write_text("#!/usr/bin/env python3\nprint('x')\n", encoding="utf-8")
    hook.chmod(0o755)
    with pytest.raises(commit_guard.Refused):
        commit_guard.apply(str(repo))
    assert (hooks / "pre-commit").read_text(encoding="utf-8") == "#!/usr/bin/env python3\nprint('x')\n"
    assert not (hooks / "commit-msg").exists()


def test_tp_commit_guard_sh_sha_pinned_to_body_sha256(tmp_path):
    from skills._shared import commit_guard  # noqa: PLC0415
    import skills._shared.commit_guard_settings as settings  # noqa: PLC0415,F401
    body = (Path(__file__).resolve().parent / "hooks" / "tp-commit-guard.sh").read_bytes()
    assert hashlib.sha256(body).hexdigest() == commit_guard.BODY_SHA256
    assert settings.DENY_RULES


def test_record_tp_root_changed_then_unchanged(tmp_path):
    from skills._shared import commit_guard  # noqa: PLC0415
    repo = _repo(tmp_path)
    assert commit_guard.record_tp_root(str(repo), "/srv/three-pillars") is True
    common = subprocess.run(["git", "-C", str(repo), "rev-parse",
                             "--path-format=absolute", "--git-common-dir"],
                            check=True, capture_output=True, text=True,
                            env=CLEAN_ENV).stdout.strip()
    pointer = Path(common) / "three-pillars" / "tp-root"
    assert pointer.read_text(encoding="utf-8") == "/srv/three-pillars"
    assert commit_guard.record_tp_root(str(repo), "/srv/three-pillars") is False
    assert commit_guard.record_tp_root(str(repo), "/srv/other") is True
    assert pointer.read_text(encoding="utf-8") == "/srv/other"


def _settings(repo: Path) -> Path:
    return repo / ".claude" / "settings.json"


def _merge(repo: Path) -> None:
    import skills._shared.commit_guard_settings as settings  # noqa: PLC0415
    settings.merge_deny(str(repo))


def test_merge_deny_creates_file_with_both_entries_and_keeps_user_entries(tmp_path):
    repo = _repo(tmp_path)
    settings_file = _settings(repo)
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(json.dumps({
        "permissions": {
            "deny": ["Bash(rm -rf:*)"],
            "allow": ["Read(//etc/hosts)"],
        },
        "model": "opus",
    }) + "\n", encoding="utf-8")
    _merge(repo)
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["permissions"]["deny"] == [
        "Bash(rm -rf:*)",
        "Bash(git commit --no-verify:*)",
        "Bash(git commit -n:*)",
    ]
    assert data["permissions"]["allow"] == ["Read(//etc/hosts)"]
    assert data["model"] == "opus"


def test_merge_deny_idempotent_and_absent_file(tmp_path):
    repo = _repo(tmp_path)
    _merge(repo)
    first = _settings(repo).read_bytes()
    _merge(repo)
    assert _settings(repo).read_bytes() == first
    data = json.loads(first.decode("utf-8"))
    assert data["permissions"]["deny"].count("Bash(git commit --no-verify:*)") == 1
    assert data["permissions"]["deny"].count("Bash(git commit -n:*)") == 1


def test_apply_persists_subasks_applied_at_and_records_tp_root(tmp_path):
    from skills._shared import commit_guard  # noqa: PLC0415
    repo = _repo(tmp_path)
    commit_guard.apply(str(repo), file_size=True, deny_no_verify=True)
    data = _config(repo)
    assert data["commit_guard"]["applied_at"]
    assert data["commit_guard"]["file_size"] is True
    assert data["commit_guard"]["deny_no_verify"] is True
    common = subprocess.run(["git", "-C", str(repo), "rev-parse",
                             "--path-format=absolute", "--git-common-dir"],
                            check=True, capture_output=True, text=True,
                            env=CLEAN_ENV).stdout.strip()
    assert (Path(common) / "three-pillars" / "tp-root").exists()
    assert _settings(repo).exists()
    commit_guard.apply(str(repo))  # a plain apply: the defaults, not "unset"
    data = _config(repo)
    assert data["commit_guard"]["applied_at"]
    assert data["commit_guard"]["file_size"] is False
    assert data["commit_guard"]["deny_no_verify"] is False
