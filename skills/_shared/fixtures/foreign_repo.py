"""foreign_repo.py — deterministic foreign-consumer-repo fixture (plugin-mode-parity).

Builds the plugin-mode parity harness fixture per detailed-design §Interfaces 2:

  * ``root``       — a foreign consumer git repo (one commit; optionally a
                     committed ``.three-pillars/config.json`` carrying
                     ``github.pr_author_account``),
  * ``home``       — a fake ``$HOME`` whose
                     ``.claude/plugins/cache/local/three-pillars/<version>`` is
                     populated from ``git archive HEAD`` of the framework
                     checkout (committed content only — mirrors a released
                     install; exactly ONE cache entry so resolve_root probe-3's
                     multi-match path is never exercised here). The ``<version>``
                     segment models the REAL Claude Code cache layout
                     (``cache/<marketplace>/<plugin>/<version>/``) — a
                     versionless fixture would vacuously green-light a probe-3
                     that cannot resolve a real install [plugin-mode-parity H2],
  * ``bin_dir``    — a PATH-prepend dir holding a ``gh`` shim that returns
                     canned JSON and appends every argv line to
                     ``bin_dir/gh-calls.log`` (the REAL gh is never invoked).

Standalone by design: does NOT import ``base_sync_repo`` (that fixture clones
this checkout's branch topology — more machinery than parity needs). Only the
gh-shim *pattern* from ``embedded_framework._GH_SHIM`` is reused; the template
is kept local because the canned responses differ (not byte-identical).

Stdlib only. No ``__init__.py`` — import by name with the fixtures dir on
``sys.path`` (same convention as the sibling fixtures).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

MARKETPLACE_SEGMENT = "local"
PLUGIN_DIR_NAME = "three-pillars"
# The real Claude Code cache layout is cache/<marketplace>/<plugin>/<version>/;
# the sentinel (first-run.md) lives under the version segment, NOT the plugin
# dir. A digit-leading name keeps this fixture's cache lexicographically first
# among sibling matches (probe-3 multi-match selection). [plugin-mode-parity H2]
PLUGIN_VERSION = "0.0.0-fixture"

# gh PATH-shim template (pattern from embedded_framework._GH_SHIM — kept local:
# responses differ). Doubled braces are literal; {login!r}/{log_path!r} fill in.
_GH_SHIM_TEMPLATE = '''#!/usr/bin/env python3
"""PATH-shim for `gh` — plugin-parity fixture edition (offline, hermetic).

Appends one argv line per invocation to gh-calls.log so harness assertions can
prove routing, then answers with canned JSON. The REAL gh is never invoked.
A `[GH_TOKEN=set]` marker on the logged line proves a bot token (not ambient
auth) reached that call — the token VALUE is never logged.
"""
import json
import os
import sys

LOGIN = {login!r}
LOG = {log_path!r}
PR_URL = "https://github.com/example/consumer/pull/1"

argv = sys.argv[1:]

line = " ".join(argv)
if os.environ.get("GH_TOKEN"):
    line += " [GH_TOKEN=set]"
with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(line + "\\n")


def _arg_after(flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if argv[:2] == ["auth", "status"]:
    print(json.dumps({{"logged_in": True, "login": LOGIN}}))
    sys.exit(0)

if argv[:2] == ["auth", "token"]:
    # Non-empty stdout satisfies github_pr_author.bot_token offline. The fake
    # token carries no real-credential prefix (secret-scanner friendly).
    print("fixture-token-" + (_arg_after("--user") or LOGIN))
    sys.exit(0)

if argv[:2] == ["api", "user"]:
    print(json.dumps({{"login": LOGIN}}))
    sys.exit(0)

if len(argv) >= 2 and argv[0] == "api" and argv[1] == "graphql":
    print(json.dumps({{"data": {{}}}}))
    sys.exit(0)

if len(argv) >= 2 and argv[0] == "api" and "/reviews" in argv[1]:
    print(json.dumps([]))
    sys.exit(0)

if argv[:2] == ["pr", "view"]:
    print(json.dumps({{
        "url": PR_URL, "state": "OPEN", "mergeable": "MERGEABLE",
        "headRefOid": "0" * 40, "baseRefName": "main",
        "statusCheckRollup": [], "commits": [],
    }}))
    sys.exit(0)

if argv[:2] == ["pr", "create"]:
    print(PR_URL)
    sys.exit(0)

if argv[:2] == ["pr", "list"]:
    print(json.dumps([]))
    sys.exit(0)

print("gh-shim: unhandled invocation: " + line, file=sys.stderr)
sys.exit(1)
'''


@dataclass
class ForeignRepo:
    """Fixture handle per detailed-design §Interfaces 2."""

    root: Path        # consumer git repo (foreign cwd)
    home: Path        # fake $HOME; plugin cache populated underneath
    cache_root: Path  # the fake plugin-cache framework install
    bin_dir: Path     # PATH-prepended dir holding the gh shim


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True,
    )


def build_foreign_repo(
    tmp,
    *,
    framework_src,
    gh_login: str = "fixture-bot",
    pr_author_account: "str | None" = None,
    with_config: bool = True,
) -> ForeignRepo:
    """Build the fixture under ``tmp``. See module docstring for the shape.

    ``with_config=True`` commits a ``.three-pillars/config.json`` that relaxes
    the two connectivity-requiring checks (mirrors clean-room-smoke.sh) and —
    when ``pr_author_account`` is given — carries ``github.pr_author_account``
    so the chokepoint resolves the bot identity from the CONSUMER repo's
    committed config. ``with_config=False`` commits no config at all.
    """
    tmp = Path(tmp)
    root = tmp / "consumer"
    home = tmp / "home"
    bin_dir = tmp / "bin"
    cache_root = (
        home / ".claude" / "plugins" / "cache"
        / MARKETPLACE_SEGMENT / PLUGIN_DIR_NAME / PLUGIN_VERSION
    )

    # --- consumer repo: git init + exactly one commit --------------------
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "parity-smoke@test.local")
    _git(root, "config", "user.name", "Parity Smoke")
    (root / "README.md").write_text(
        "# foreign consumer repo (plugin-parity fixture)\n", encoding="utf-8"
    )
    if with_config:
        cfg: dict = {
            "ci": {"expects_github_checks": False},
            "review": {"expects_copilot": False},
        }
        if pr_author_account is not None:
            cfg["github"] = {"pr_author_account": pr_author_account}
        cfg_dir = root / ".three-pillars"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.json").write_text(
            json.dumps(cfg, indent=2) + "\n", encoding="utf-8"
        )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fixture: consumer seed commit")

    # --- fake plugin cache from git archive HEAD (committed content only) -
    cache_root.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "-C", str(framework_src), "archive", "HEAD"],
        capture_output=True, check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        try:
            tf.extractall(cache_root, filter="data")
        except TypeError:  # pragma: no cover — pre-3.12 tarfile without filter=
            tf.extractall(cache_root)  # nosec B202 — archive is this repo's own HEAD

    # --- gh PATH shim ------------------------------------------------------
    bin_dir.mkdir(parents=True)
    shim = bin_dir / "gh"
    shim.write_text(
        _GH_SHIM_TEMPLATE.format(
            login=gh_login, log_path=str(bin_dir / "gh-calls.log")
        ),
        encoding="utf-8",
    )
    shim.chmod(0o755)

    return ForeignRepo(root=root, home=home, cache_root=cache_root, bin_dir=bin_dir)


def env_for(fx: ForeignRepo, *, plugin_mode: bool) -> dict:
    """Assemble the subprocess env for a scenario run (cwd chosen by caller).

    Always: ``HOME`` = the fake home, ``PATH`` = ``bin_dir`` prepended (the gh
    shim intercepts before any real gh). ``plugin_mode=True`` adds
    ``CLAUDE_PLUGIN_ROOT=cache_root`` (resolve_root probe 1);
    ``plugin_mode=False`` strips it, forcing probe 3 through the fake HOME.
    ``os.environ`` itself is never mutated.
    """
    env = dict(os.environ)
    env["HOME"] = str(fx.home)
    env["PATH"] = f"{fx.bin_dir}{os.pathsep}{env.get('PATH', '')}"
    if plugin_mode:
        env["CLAUDE_PLUGIN_ROOT"] = str(fx.cache_root)
    else:
        env.pop("CLAUDE_PLUGIN_ROOT", None)
    return env
