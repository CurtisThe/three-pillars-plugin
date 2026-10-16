"""First-run skips the GitHub-only offers on a non-GitHub forge (Task 1.8).

design: forge-interface (Phase 1). On a Gitea (or unknown) origin BOTH GitHub-only
first-run helpers — `github_auth_check.check` (PR-author offer) and
`branch_protection_check.check` — answer `skip-non-github` before their `gh` and
`--auto` branches: no `github` block, no `branch_protection` block, no
`decisions.md` entry, no `gh api` command on stdout. The kind is recorded once
(Task 1.7's `forge_config`), so the next run settles cheap-path conditions 3 and 7
from the config read alone and the resolver is never consulted again. A
`no web base` resolve records nothing and prints the one setup line instead.
Hermetic: `tmp_path` repos, a `resolver` seam, no network, no `gh`, no `tea`.

Run with: python3 -m pytest skills/_shared/test_forge_first_run.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import branch_protection_check  # noqa: E402
import forge  # noqa: E402
import forge_config  # noqa: E402
import github_auth_check  # noqa: E402

GITEA_ORIGIN = "https://gitea.lan/home/lab.git"
SSH_ALIAS_ORIGIN = "gitea:scurtis/Homelab.git"
FIRST_RUN_MD = Path(__file__).resolve().parent / "first-run.md"


def _init_repo(tmp_path: Path, url: str = GITEA_ORIGIN) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    if url:
        subprocess.run(["git", "remote", "add", "origin", url], cwd=repo, check=True)
    return repo


def _config_path(repo: Path) -> Path:
    return repo / ".three-pillars" / "config.json"


def _write_config(repo: Path, data: dict) -> None:
    path = _config_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _raw(repo: Path) -> dict:
    path = _config_path(repo)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _info(kind="gitea", host="gitea.lan", web_base="https://gitea.lan", reason=""):
    """The `ForgeInfo` a resolve produced for this repo's origin."""
    api_base = f"{web_base}/api/v1" if web_base else ""
    return forge.ForgeInfo(kind, host, "home", "lab", web_base, api_base, reason)


def _resolver(info):
    """The `resolver` seam standing in for `forge.resolve`."""
    return lambda repo: info


def _forbidden_resolver(repo):
    raise AssertionError("resolver must not run once forge.kind is recorded")


# --- the skip, on both offers ---------------------------------------------------


def test_gitea_origin_skips_the_pr_author_offer_and_records_the_kind(
    tmp_path, monkeypatch
):
    """Gitea origin + `gh` present → `skip-non-github`, no `github` block written."""
    repo = _init_repo(tmp_path)
    monkeypatch.setattr(github_auth_check.shutil, "which", lambda name: "/usr/bin/gh")

    result = github_auth_check.check(repo, resolver=_resolver(_info()))

    assert result.action == "skip-non-github"
    assert result.config_updated is True
    cfg = _raw(repo)
    assert cfg["forge"]["kind"] == "gitea"
    assert "github" not in cfg


def test_gitea_origin_skips_branch_protection_under_auto_with_no_gh(tmp_path, capsys,
                                                                    monkeypatch):
    """No `gh`, `auto=True`: still no decisions entry, no `branch_protection` block,
    no `gh api` command — the forge answer comes before both branches."""
    repo = _init_repo(tmp_path)
    monkeypatch.setattr(branch_protection_check.shutil, "which", lambda name: None)
    decisions = tmp_path / "decisions.md"

    result = branch_protection_check.check(repo, auto=True, decisions_file=decisions,
                                           resolver=_resolver(_info()))

    captured = capsys.readouterr()
    assert result.action == "skip-non-github"
    assert result.config_updated is True
    assert captured.out == ""
    assert not decisions.exists()
    cfg = _raw(repo)
    assert "branch_protection" not in cfg
    assert cfg["forge"]["kind"] == "gitea"


def test_recorded_kind_settles_both_offers_from_the_config_read_alone(
    tmp_path, monkeypatch
):
    """A recorded `forge.kind` answers both conditions with no resolver call and
    no write of any kind."""
    repo = _init_repo(tmp_path)
    _write_config(repo, {"schema_version": 1,
                         "forge": {"kind": "gitea", "host": "gitea.lan"}})
    monkeypatch.setattr(github_auth_check.shutil, "which", lambda name: "/usr/bin/gh")

    auth = github_auth_check.check(repo, resolver=_forbidden_resolver)
    prot = branch_protection_check.check(repo, resolver=_forbidden_resolver)

    assert auth.action == "skip-non-github"
    assert prot.action == "skip-non-github"
    assert auth.config_updated is False
    assert prot.config_updated is False
    cfg = _raw(repo)
    assert cfg["forge"] == {"kind": "gitea", "host": "gitea.lan"}
    assert "github" not in cfg and "branch_protection" not in cfg


# --- what gets recorded ---------------------------------------------------------


def test_web_base_from_a_tea_login_is_recorded_beside_the_kind(tmp_path):
    """A Gitea web base discovered from a matching `tea` login (not config) is
    written next to the kind, so Tier 6 `pr-create` needs no second lookup."""
    repo = _init_repo(tmp_path)
    info = _info(web_base="https://gitea.lan:30008")

    result = github_auth_check.check(repo, resolver=_resolver(info))

    assert result.action == "skip-non-github"
    block = _raw(repo)["forge"]
    assert block["kind"] == "gitea"
    assert block["web_base"] == "https://gitea.lan:30008"


def test_no_web_base_prints_one_setup_line_and_records_no_kind(tmp_path, capsys):
    """An ssh-config alias has no derivable web base: the offer is still skipped,
    nothing is recorded, and the operator gets exactly one actionable line."""
    repo = _init_repo(tmp_path, url=SSH_ALIAS_ORIGIN)
    info = _info(kind="other", host="gitea", web_base="",
                 reason=f"no web base — {forge.NO_WEB_BASE_LINE}")

    result = github_auth_check.check(repo, resolver=_resolver(info))

    err = capsys.readouterr().err
    assert result.action == "skip-non-github"
    assert result.config_updated is False
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "set forge.web_base in .three-pillars/config.json" in lines[0]
    assert forge_config.read_kind(_raw(repo)) is None


def test_operator_web_base_survives_the_kind_record(tmp_path, capsys):
    """After the operator sets `forge.web_base`, the resolver is consulted again,
    the kind lands in the operator's own block, and the web base stays put."""
    repo = _init_repo(tmp_path, url=SSH_ALIAS_ORIGIN)
    _write_config(repo, {"schema_version": 1,
                         "forge": {"web_base": "https://truenas.home.arpa:30008"}})
    info = _info(kind="gitea", host="gitea",
                 web_base="https://truenas.home.arpa:30008")

    result = github_auth_check.check(repo, resolver=_resolver(info))

    captured = capsys.readouterr()
    assert result.action == "skip-non-github"
    assert result.config_updated is True
    assert captured.err == ""
    block = _raw(repo)["forge"]
    assert block["kind"] == "gitea"
    assert block["web_base"] == "https://truenas.home.arpa:30008"


def test_unsupported_forge_records_other_and_prints_the_reason_once(tmp_path, capsys):
    """A probe that simply fails (GitLab, GHE) records `other` and prints the
    resolve reason on one stderr line at that moment — never the Gitea setup line."""
    repo = _init_repo(tmp_path, url="https://gitlab.com/acme/widget.git")
    info = _info(kind="other", host="gitlab.com", web_base="https://gitlab.com",
                 reason="unsupported forge: gitlab.com")

    result = branch_protection_check.check(repo, resolver=_resolver(info))

    captured = capsys.readouterr()
    assert result.action == "skip-non-github"
    assert captured.out == ""
    assert captured.err == "unsupported forge: gitlab.com\n"
    assert "forge.web_base" not in captured.err
    assert _raw(repo)["forge"]["kind"] == "other"
    assert "branch_protection" not in _raw(repo)


def test_recording_other_prints_the_github_remedy_for_an_enterprise_host(
    tmp_path, capsys
):
    """GHE https origin, no forge block: the reason (with the `forge.kind: github`
    hint) is shown when `other` is recorded, since later runs are silent."""
    repo = _init_repo(tmp_path, url="https://ghe.corp.com/o/r.git")
    info = _info(kind="other", host="ghe.corp.com", web_base="https://ghe.corp.com",
                 reason=f"unsupported forge: ghe.corp.com — {forge.GITHUB_HINT}")

    result = github_auth_check.check(repo, resolver=_resolver(info))

    err_lines = [l for l in capsys.readouterr().err.splitlines() if l.strip()]
    assert result.action == "skip-non-github"
    assert _raw(repo)["forge"]["kind"] == "other"
    assert err_lines == [info.reason]
    assert "set forge.kind: github" in err_lines[0]


# --- first-run.md prose follows the new action ----------------------------------


def _section(heading: str) -> str:
    text = FIRST_RUN_MD.read_text(encoding="utf-8")
    return text.split("\n" + heading, 1)[1].split("\n## ", 1)[0]


def test_cheap_path_conditions_3_and_7_accept_a_recorded_non_github_forge():
    section = _section("## Cheap-path early-exit")
    conds = section.splitlines()
    cond3 = next(line for line in conds if line.startswith("3. "))
    cond7 = next(line for line in conds if line.startswith("7. "))
    assert "forge.kind" in cond3
    assert "forge.kind" in cond7


def test_both_offer_sections_list_the_skip_non_github_action():
    assert "skip-non-github" in _section("## GitHub PR-author offer")
    assert "skip-non-github" in _section("## Branch-protection detection")
