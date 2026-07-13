"""Tests for collision_advisory.py's config-threading fix (pr-author-bot-account).

Today `collision_advisory.py` calls `single_account_collision_live(config={})`
— the committed `review.automation_identities` are invisible to the warning,
so a machine account that is a repo collaborator reads as a "distinct human
reviewer" and silently suppresses the collision warning (false negative).
This file pins the fix: read `<repo>/.three-pillars/config.json` fail-open
and thread it through.

New file (NOT extending the 355-line test_single_account_collision.py, per
the file-size soft-warn convention).

Run with: pytest skills/_shared/test_collision_advisory.py -q
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _fake_gh_run(argv, **kwargs):
    if argv[:4] == ["gh", "api", "user", "--jq"]:
        return mock.Mock(returncode=0, stdout="CurtisThe\n", stderr="")
    if argv[:2] == ["gh", "api"] and any("collaborators" in a for a in argv):
        payload = json.dumps(
            [
                {"login": "CurtisThe", "type": "User"},
                {"login": "CurtisTheBot", "type": "User"},
            ]
        )
        return mock.Mock(returncode=0, stdout=payload, stderr="")
    return mock.Mock(returncode=1, stdout="", stderr="unrecognized")


def _write_config(repo: Path, data: dict) -> None:
    cfg_dir = repo / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(data), encoding="utf-8")


class TestCollisionAdvisoryConfigThreading:
    def test_bot_in_automation_identities_flips_to_collision(self, tmp_path):
        """The {human, bot} collaborator set previously read as 'two accounts,
        no collision' because config={} hid the bot from the automation set.
        With the real config threaded, CurtisTheBot is recognized as
        automation and the collision fires."""
        import collision_advisory

        repo = tmp_path / "repo"
        repo.mkdir()
        _write_config(
            repo,
            {"schema_version": 1, "review": {"automation_identities": ["curtisthebot"]}},
        )

        buf = io.StringIO()
        with mock.patch("subprocess.run", side_effect=_fake_gh_run):
            old_stdout = sys.stdout
            sys.stdout = buf
            try:
                exit_code = collision_advisory.main([str(repo)])
            finally:
                sys.stdout = old_stdout

        assert exit_code == 0
        assert "COLLISION" in buf.getvalue()

    def test_missing_config_file_behaves_as_empty_dict_fail_open(self, tmp_path):
        import collision_advisory

        repo = tmp_path / "repo"
        repo.mkdir()
        # No .three-pillars/config.json at all.

        with mock.patch("subprocess.run", side_effect=_fake_gh_run):
            exit_code = collision_advisory.main([str(repo)])

        assert exit_code == 0

    def test_corrupt_config_file_behaves_as_empty_dict_fail_open(self, tmp_path):
        import collision_advisory

        repo = tmp_path / "repo"
        repo.mkdir()
        cfg_dir = repo / ".three-pillars"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.json").write_text("{not valid json", encoding="utf-8")

        with mock.patch("subprocess.run", side_effect=_fake_gh_run):
            exit_code = collision_advisory.main([str(repo)])

        assert exit_code == 0


class TestSingleAccountCollisionPureCompanion:
    """Pure-layer companion assertion (design.md Task 3.1 Red) — the same
    scenario at the single_account_collision() unit level, no gh calls."""

    def test_bot_in_config_automation_identities_causes_collision(self):
        from single_account_detect import single_account_collision

        cfg = {"review": {"automation_identities": ["curtisthebot"]}}
        result = single_account_collision(
            self_login="curtisthe",
            collaborators=[
                {"login": "CurtisThe", "type": "User"},
                {"login": "CurtisTheBot", "type": "User"},
            ],
            config=cfg,
        )
        assert result is True
