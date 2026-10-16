"""test_child_sandbox.py — merging the Bash-sandbox block into an attempt worktree.

design: strata-classifier-cost-followups (Task 2.1)

Real tmp repos built with `git init` + one commit + `git worktree add` under
``tmp_path``, and an explicit ``env`` dict on every call — never the session's
TMPDIR or HOME. The fixture git calls run with the repo-local git env scrubbed
(``task_scope._git_env``) so nothing here reads the ambient repository.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import child_sandbox
from attempt_fixture import commit, git

SETTINGS = ".claude/settings.local.json"


def _wt(tmp_path: Path, name: str = "att") -> Path:
    """A linked worktree ``<tmp>/repo-wt/<name>`` of a one-commit tmp repo.

    The repo's ``core.excludesFile`` is pinned to the null device: a developer's
    ``$HOME/.config/git/ignore`` already lists the settings path, so
    ``git check-ignore`` would exit 0 for a reason the test does not control and
    the ``info/exclude`` append would be skipped (or unobservable).
    """
    repo = tmp_path / "repo"
    if not repo.exists():
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit(repo, {"README.md": "demo\n"}, "base")
        git(repo, "config", "core.excludesFile", os.devnull)
    wt = tmp_path / "repo-wt" / name
    git(repo, "worktree", "add", "-q", "-b", f"tp-attempt/demo/{name}", str(wt))
    return wt


def _common(wt: Path) -> str:
    return str(Path(git(wt, "rev-parse", "--git-common-dir")).resolve())


def _read(wt: Path) -> dict:
    return json.loads((wt / SETTINGS).read_text(encoding="utf-8"))


def test_no_existing_file_writes_the_block(tmp_path):
    wt = _wt(tmp_path)
    tmpdir = tmp_path / "t"
    tmpdir.mkdir()
    env = {"TMPDIR": str(tmpdir)}

    ok, why = child_sandbox.merge_settings(wt, env)

    assert (ok, why) == (True, "")
    # tp-allow-fragile: the closed sandbox block design.md §Phase B B1 + Task 2.1
    # Green specify verbatim; the dispatcher note adds the denyWrite pair.
    assert _read(wt) == {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": False,
            "network": {"allowedDomains": ["pypi.org", "files.pythonhosted.org"]},
            "filesystem": {
                "allowWrite": [_common(wt), str(tmpdir)],
                "denyWrite": [os.path.join(_common(wt), "hooks"),
                              os.path.join(_common(wt), "config")],
            },
        }
    }


def test_allow_write_is_common_dir_then_tmpdir(tmp_path):
    wt = _wt(tmp_path)
    tmpdir = tmp_path / "t"
    tmpdir.mkdir()
    common = _common(wt)
    assert Path(common).name == ".git"  # the seat's, not the worktree's
    assert not common.startswith(str(wt))

    child_sandbox.merge_settings(wt, {"TMPDIR": str(tmpdir)})
    assert _read(wt)["sandbox"]["filesystem"]["allowWrite"] == [common, str(tmpdir)]
    assert child_sandbox.write_paths(wt, {"TMPDIR": str(tmpdir)}) == [common, str(tmpdir)]
    assert child_sandbox.write_paths(wt, {}) == [common]


def test_tmpdir_inside_the_worktree_is_not_granted(tmp_path):
    # The worktree is already writable; a TMPDIR inside it needs no grant.
    wt = _wt(tmp_path, "inside")
    child_sandbox.merge_settings(wt, {"TMPDIR": str(wt / "tmp")})
    assert _read(wt)["sandbox"]["filesystem"]["allowWrite"] == [_common(wt)]


def test_tmpdir_under_tmp_is_granted_like_any_other_path(tmp_path):
    # Live proof: "/tmp is in the sandbox's default write set" is false, so a
    # TMPDIR under it must be granted like any other out-of-tree path.
    wt = _wt(tmp_path, "undertmp")
    child_sandbox.merge_settings(wt, {"TMPDIR": os.path.join(os.sep + "tmp", "x")})
    assert _read(wt)["sandbox"]["filesystem"]["allowWrite"] == [_common(wt),
                                                                os.path.join(os.sep + "tmp", "x")]
    assert child_sandbox.write_paths(wt, {"TMPDIR": os.path.join(os.sep + "tmp", "x")}) == [
        _common(wt), os.path.join(os.sep + "tmp", "x")]


def test_deny_paths_are_hooks_and_config(tmp_path):
    wt = _wt(tmp_path)
    common = _common(wt)
    assert child_sandbox.deny_paths(wt) == [os.path.join(common, "hooks"),
                                            os.path.join(common, "config")]


def test_existing_file_is_merged_never_replaced(tmp_path):
    wt = _wt(tmp_path)
    (wt / ".claude").mkdir(parents=True)
    (wt / SETTINGS).write_text(
        '{"permissions": {"allow": ["Bash(ls)"]},'
        ' "sandbox": {"network": {"allowedDomains": ["example.org"]}}}',
        encoding="utf-8")

    ok, why = child_sandbox.merge_settings(wt, {})

    assert (ok, why) == (True, "")
    data = _read(wt)
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    assert data["sandbox"]["enabled"] is True
    assert data["sandbox"]["failIfUnavailable"] is False
    assert data["sandbox"]["network"]["allowedDomains"] == [
        "example.org", "pypi.org", "files.pythonhosted.org"]
    # tp-allow-fragile: the closed PyPI host set design.md §Phase B B1 names.
    assert data["sandbox"]["network"]["allowedDomains"][1:] == [
        "pypi.org", "files.pythonhosted.org"]


def test_existing_write_lists_are_unioned_existing_first(tmp_path):
    wt = _wt(tmp_path)
    (wt / ".claude").mkdir(parents=True)
    (wt / SETTINGS).write_text(
        '{"sandbox": {"filesystem": {"allowWrite": ["/srv/keep"],'
        ' "denyWrite": ["/srv/keep-deny"]}}}', encoding="utf-8")
    tmpdir = tmp_path / "t"
    tmpdir.mkdir()

    child_sandbox.merge_settings(wt, {"TMPDIR": str(tmpdir)})

    fs = _read(wt)["sandbox"]["filesystem"]
    assert fs["allowWrite"] == ["/srv/keep", _common(wt), str(tmpdir)]
    assert fs["denyWrite"] == ["/srv/keep-deny", os.path.join(_common(wt), "hooks"),
                               os.path.join(_common(wt), "config")]


def test_merge_is_idempotent(tmp_path):
    wt = _wt(tmp_path)
    tmpdir = tmp_path / "t"
    tmpdir.mkdir()
    env = {"TMPDIR": str(tmpdir)}

    assert child_sandbox.merge_settings(wt, env) == (True, "")
    first = (wt / SETTINGS).read_bytes()
    assert child_sandbox.merge_settings(wt, env) == (True, "")
    assert (wt / SETTINGS).read_bytes() == first


def test_unparsable_existing_file_is_left_untouched(tmp_path):
    wt = _wt(tmp_path)
    (wt / ".claude").mkdir(parents=True)
    (wt / SETTINGS).write_text("{not json", encoding="utf-8")

    ok, why = child_sandbox.merge_settings(wt, {})

    assert ok is False
    assert why
    assert (wt / SETTINGS).read_text(encoding="utf-8") == "{not json"


def test_settings_local_stays_out_of_git_status(tmp_path):
    wt = _wt(tmp_path)

    assert child_sandbox.merge_settings(wt, {}) == (True, "")
    assert SETTINGS not in git(wt, "status", "--porcelain", "-uall").split()
    exclude = Path(git(wt, "rev-parse", "--git-path", "info/exclude"))
    assert exclude.read_text(encoding="utf-8").count(SETTINGS) == 1

    # Already ignored (nothing appended), and a second merge leaves one entry.
    assert child_sandbox.merge_settings(wt, {}) == (True, "")
    assert exclude.read_text(encoding="utf-8").count(SETTINGS) == 1
    assert SETTINGS not in git(wt, "status", "--porcelain", "-uall").split()


# --- prepare names a TMPDIR the child can write (Task 2.6, live proof) --------

def test_prepare_sets_and_grants_a_tmpdir_when_env_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(child_sandbox, "available", lambda *a, **k: (True, ""))
    wt = _wt(tmp_path, "unset")
    env = {"TP_CHILD_SANDBOX": "on"}

    state, warns = child_sandbox.prepare(wt, "S1", {"strata_spawn": {"sandbox": "on"}}, env)

    assert (state, warns) == ("sandboxed", [])
    # Live proof: with ``TMPDIR`` unset the child had no writable temp dir at all
    # (pytest then wrote ``pytest-of-<user>/`` into the attempt), so `prepare`
    # names one — the same realpath the child inherits from this env dict.
    assert env["TMPDIR"] == os.path.realpath(tempfile.gettempdir())
    assert env["TMPDIR"] in _read(wt)["sandbox"]["filesystem"]["allowWrite"]


def test_prepare_grants_a_tmpdir_it_did_not_have_to_set(tmp_path, monkeypatch):
    monkeypatch.setattr(child_sandbox, "available", lambda *a, **k: (True, ""))
    wt = _wt(tmp_path, "kept")
    tmpdir = tmp_path / "t"
    tmpdir.mkdir()
    env = {"TP_CHILD_SANDBOX": "on", "TMPDIR": str(tmpdir)}

    state, warns = child_sandbox.prepare(wt, "S1", {"strata_spawn": {"sandbox": "on"}}, env)

    assert (state, warns) == ("sandboxed", [])
    assert env["TMPDIR"] == str(tmpdir)
    assert _read(wt)["sandbox"]["filesystem"]["allowWrite"][1:] == [str(tmpdir)]


def test_prepare_leaves_env_untouched_when_the_child_is_not_sandboxed(tmp_path,
                                                                      monkeypatch):
    monkeypatch.setattr(child_sandbox, "available", lambda *a, **k: (True, ""))
    # Switch off: no grant, and no invented TMPDIR either.
    off = _wt(tmp_path, "offenv")
    env_off: dict = {}
    assert child_sandbox.prepare(off, "S1", {"strata_spawn": {"sandbox": "off"}},
                                 env_off)[0] == "off"
    assert env_off == {}
    # A non-S1 site: its cwd is not an attempt worktree, so nothing is decided for it.
    skipped = _wt(tmp_path, "skipenv")
    env_skipped: dict = {}
    assert child_sandbox.prepare(skipped, "S3", {"strata_spawn": {"sandbox": "on"}},
                                 env_skipped)[0] == "skipped"
    assert env_skipped == {}
    # Unavailable: the child runs unsandboxed, so its env stays as the caller left it.
    unavail = _wt(tmp_path, "unavailenv")
    monkeypatch.setattr(child_sandbox, "available", lambda *a, **k: (False, "no bwrap"))
    env_unavail: dict = {}
    assert child_sandbox.prepare(unavail, "S1", {"strata_spawn": {"sandbox": "on"}},
                                 env_unavail)[0] == "unavailable"
    assert env_unavail == {}
