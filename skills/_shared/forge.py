#!/usr/bin/env python3
"""forge.py — resolve a repo's forge (github / gitea / other) from its origin.

design: forge-interface (Task 1.1)

`parse_remote(url)` returns `(host, port or None, owner, repo)`: credentials never
reach any field, and an scp-style `alias:owner/repo` keeps the alias as the host.
`resolve(repo, *, config, runner, urlopen, tea_logins, timeout)` reads the origin
URL through the injectable `runner`, picks a **web base** (config `forge.web_base`
> a `tea` login url whose hostname matches the remote host > `https://host[:port]`
for an https remote > `https://host` for an SSH remote whose host is a real FQDN),
then the **kind** (config `forge.kind` — not authoritative as `other` once config
`forge.web_base` is set — > github.com > an ssh alias that `ssh -G` resolves to
github.com (see `forge_ssh.py`) > a `<web_base>/api/v1/version` probe over
system-CA TLS > `other`). Every seam is injectable, so no test needs the network,
a real `git` or a real `tea`. `Result` is the typed ok/degraded contract the PR
operations (Task 1.5) return; the CLI dispatch is not here yet. Stdlib only.
"""
from __future__ import annotations

import json
import re
import ssl
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen as _stdlib_urlopen

import automation_identity
import forge_ssh

# The one setup line every `no web base` reason (and first-run, Task 1.8) prints.
GITHUB_HINT = "for a GitHub ssh alias or GitHub Enterprise host, set forge.kind: github"
NO_WEB_BASE_LINE = (
    "if this is a Gitea, set forge.web_base in .three-pillars/config.json, "
    f"e.g. https://<host>:<port>; {GITHUB_HINT} "
    "(or set forge.kind: other to silence this)"
)

_SCP_RE = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>/.+|[^/].*)$")


class ForgeInfo(NamedTuple):
    """What a repo's origin resolves to. `reason` explains an `other`."""

    kind: str  # "github" | "gitea" | "other"
    host: str
    owner: str
    repo: str
    web_base: str  # instance base: scheme + host (+ port), never owner/repo
    api_base: str
    reason: str


@dataclass(frozen=True)
class Result:
    """One operation's outcome: `ok` + payload, or `degraded` + one line."""

    status: str
    payload: dict = field(default_factory=dict)
    line: str = ""
    note: str = ""

    @classmethod
    def ok(cls, payload: dict, note: str = "") -> "Result":
        return cls("ok", dict(payload), "", note)

    @classmethod
    def degraded(cls, line: str, note: str = "") -> "Result":
        """A degrade is one actionable line — never empty, never wrapped."""
        if not line or "\n" in line:
            raise ValueError("a degraded result needs exactly one actionable line")
        return cls("degraded", {}, line, note)


def _strip_suffix(name: str) -> str:
    return name[:-4] if name.endswith(".git") else name


def parse_remote(url: str) -> tuple:
    """`(host, port or None, owner, repo)` for any git remote URL.

    Credentials are dropped by the parse, not scrubbed afterwards. scp-style
    addressing has no port slot, so its port is `None` and its host may be an
    ssh-config alias rather than a hostname.
    """
    if "://" in url:
        parsed = urlparse(url)
        host, port, path = parsed.hostname or "", parsed.port, parsed.path
    else:
        match = _SCP_RE.match(url)
        if not match:
            return (urlparse(url).hostname or "", None, "", _strip_suffix(url))
        host, port, path = match.group("host"), None, match.group("path")
    parts = [seg for seg in path.split("/") if seg]
    if parts:
        parts[-1] = _strip_suffix(parts[-1])
    return (host, port, "/".join(parts[:-1]), parts[-1] if parts else "")


def _scheme(url: str) -> str:
    """The remote's addressing scheme; scp-style is always SSH."""
    return urlparse(url).scheme.lower() if "://" in url else "ssh"


def _read_config(repo) -> dict:
    """`<repo>/.three-pillars/config.json`, or `{}` when absent / invalid."""
    try:
        loaded = json.loads(
            (Path(repo) / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _config_root(repo) -> Path:
    """`repo` when it holds the config, else its git toplevel (`repo='.'` from a subdirectory)."""
    root = Path(repo)
    if (root / ".three-pillars" / "config.json").exists():
        return root
    try:
        proc = _default_runner(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    except OSError:
        return root
    top = (proc.stdout or "").strip() if proc.returncode == 0 else ""
    return Path(top) if top else root


def _default_runner(argv):
    """The default `runner` seam: argv list -> CompletedProcess (text output)."""
    return subprocess.run(argv, capture_output=True, text=True)


def _origin_url(repo, run) -> str:
    proc = run(["git", "-C", str(repo), "remote", "get-url", "origin"])
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _web_base(url: str, host: str, port, configured: str, logins) -> tuple:
    """`(web_base, source)` — the instance base and how it was picked."""
    if configured:
        return configured, "config"
    for login in logins or ():
        login_url = (login.get("url") or "").strip().rstrip("/")
        if login_url and (urlparse(login_url).hostname or "") == host:
            return login_url, "tea"
    if _scheme(url) in ("http", "https"):
        return f"https://{host}" + (f":{port}" if port else ""), "https"
    if "." in host:  # a real FQDN over SSH; the SSH port is not the web port
        return f"https://{host}", "ssh"
    return "", ""  # an ssh-config alias has no derivable web base


def _usable_web_base(web_base: str) -> bool:
    """An absolute `http(s)://host` base: the only shape REST and compare URLs use."""
    parsed = urlparse(web_base or "")
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class _ProbeRequest(Request):
    """The probe request. `.url` is the legacy stdlib name for the target URL
    (3.3 and earlier) and stays the read handle an injected `urlopen` seam uses
    to report which URL it was called for; urllib itself only reads `full_url`."""

    @property
    def url(self) -> str:
        return self.full_url


def _probe_gitea(web_base: str, open_, timeout) -> bool:
    """True when `<web_base>/api/v1/version` answers with JSON. System CA only."""
    try:
        with open_(_ProbeRequest(f"{web_base}/api/v1/version"), timeout=timeout,
                   context=ssl.create_default_context()) as resp:
            json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, ValueError):
        return False
    return True


def resolve(repo, *, config=None, runner=None, urlopen=None, tea_logins=None,
            timeout=5) -> ForgeInfo:
    """Resolve `repo`'s origin. `config=None` reads the repo's own config file."""
    cfg = config if config is not None else _read_config(repo)
    forge_cfg = cfg.get("forge") if isinstance(cfg.get("forge"), dict) else {}
    url = _origin_url(repo, runner or _default_runner)
    if not url:
        return ForgeInfo("other", "", "", "", "", "", "no origin")
    host, port, owner, name = parse_remote(url)
    configured = (forge_cfg.get("web_base") or "").strip().rstrip("/")
    logins = tea_logins
    if logins is None:
        from forge_gitea import read_tea_logins  # lands in Task 1.3
        logins = read_tea_logins()
    web_base, source = _web_base(url, host, port, configured, logins)
    kind_cfg = (forge_cfg.get("kind") or "").strip().lower()
    open_ = urlopen or _stdlib_urlopen
    if kind_cfg and not (kind_cfg == "other" and configured):
        kind, reason = kind_cfg, ""
    elif host == "github.com":
        kind, reason, web_base = "github", "", "https://github.com"
    elif (not configured and _scheme(url) == "ssh"
          and forge_ssh.is_github_alias(host, runner)):  # ssh-config alias of github.com
        kind, reason, web_base, host = "github", "", "https://github.com", "github.com"
    elif not web_base:
        kind, reason = "other", f"no web base — {NO_WEB_BASE_LINE}"
    elif _probe_gitea(web_base, open_, timeout):
        kind, reason = "gitea", ""
    elif source == "ssh":  # a guessed base that fails: still no web base
        kind, reason = "other", f"no web base — {NO_WEB_BASE_LINE}"
    else:
        kind, reason = "other", f"unsupported forge: {host} — {GITHUB_HINT}"
    if kind == "gitea" and not _usable_web_base(web_base):  # e.g. kind set, alias origin
        kind, reason, web_base = "other", f"no web base — {NO_WEB_BASE_LINE}", ""
    if kind == "github":
        web_base = web_base or "https://github.com"  # forge.kind: github on an alias
        api_base = "https://api.github.com"
    else:
        api_base = f"{web_base}/api/v1" if web_base else ""
    return ForgeInfo(kind, host, owner, name, web_base, api_base, reason)


# --- dispatch (Task 1.5) ---------------------------------------------------------
# The backends import this module, so each one is imported INSIDE the function that
# needs it: a top-level import would be circular. Every op resolves once (or takes a
# caller-supplied `ForgeInfo`) and returns a `Result` — never `None`, never a raise.


def _unsupported(info: ForgeInfo) -> Result:
    """The one answer for a forge with no backend: it names the host and the reason."""
    if info.reason.startswith("unsupported forge"):  # already the whole line
        return Result.degraded(info.reason)
    host = info.host or "(no origin)"
    if not info.reason:  # kind came from config (`forge.kind: other`): no probe reason
        return Result.degraded(
            f"unsupported forge: {host} (forge.kind: other in "
            f".three-pillars/config.json — {GITHUB_HINT})")
    return Result.degraded(f"unsupported forge: {host} ({info.reason})")


def _info_for(repo, info):
    return info if info is not None else resolve(repo)


def _gitea_token(info: ForgeInfo, env):
    """The Gitea token for this instance (`None` = no token, so no REST path)."""
    import forge_gitea
    return forge_gitea.token_for(info.web_base, env=env)


# The GitHub ops that write as the automation identity (`BotAuthUnavailable` propagates:
# fail loud, never ambient). The strict `load_repo_config` is deliberate — `_read_config` is
# lenient (`{}` on a bad file), which would hide a configured bot.
_GH_WRITES = frozenset({"comment_post", "comment_edit", "label_add", "label_remove"})


def _dispatch(op: str, repo, args, *, info=None, env=None, urlopen=None,
              runner=None) -> Result:
    """One REST-shaped op to the backend its kind picked. `args` are positional."""
    info = _info_for(repo, info)
    if info.kind == "other":
        return _unsupported(info)
    if info.kind == "github":
        import forge_github
        who = {}  # the four writes run as the configured bot; reads stay ambient
        if op in _GH_WRITES:
            who = {"config": automation_identity.load_repo_config(_config_root(repo)), "env": env}
        return getattr(forge_github, op)(info, *args, runner=runner, **who)
    token = _gitea_token(info, env)
    if token is None:  # Gitea without a token has no REST path at all
        import forge_gitea_agit
        return forge_gitea_agit.no_token(op.replace("_", "-"), info)
    import forge_gitea
    return getattr(forge_gitea, op)(info, *args, token=token, urlopen=urlopen)


def pr_create(repo, *, base, head, title, body, reviewers=None, info=None, env=None,
              urlopen=None, runner=None) -> Result:
    """Open a PR: gh chokepoint (github), REST (gitea + token), AGit push (no token)."""
    info = _info_for(repo, info)
    if info.kind == "other":
        return _unsupported(info)
    if info.kind == "github":
        import forge_github
        gh_args = ["--base", base, "--head", head, "--title", title, "--body", body]
        if reviewers:
            gh_args += ["--reviewer", reviewers]
        return forge_github.pr_create(info, gh_args, _read_config(repo), "manual",
                                      runner=runner, env=env)
    token = _gitea_token(info, env)
    if token is not None:
        import forge_gitea
        return forge_gitea.pr_create(info, base=base, head=head, title=title,
                                     body=body, reviewers=reviewers, token=token,
                                     urlopen=urlopen)
    import forge_gitea_agit
    return forge_gitea_agit.pr_create_agit(info, base=base, head=head, title=title,
                                           body=body, reviewers=reviewers,
                                           runner=runner, repo=repo)


def pr_read(repo, number, *, info=None, env=None, urlopen=None, runner=None) -> Result:
    """Read one PR: `{number, head, head_sha, state, url}` (`head` is the branch name)."""
    return _dispatch("pr_read", repo, (number,), info=info, env=env,
                     urlopen=urlopen, runner=runner)


def comment_post(repo, number, body: str, *, info=None, env=None, urlopen=None,
                 runner=None) -> Result:
    """Add a comment to PR `number`."""
    return _dispatch("comment_post", repo, (number, body), info=info, env=env,
                     urlopen=urlopen, runner=runner)


def comment_list(repo, number, *, info=None, env=None, urlopen=None,
                 runner=None) -> Result:
    """List PR `number`'s comments: `{"comments": [{id, body}]}`."""
    return _dispatch("comment_list", repo, (number,), info=info, env=env,
                     urlopen=urlopen, runner=runner)


def comment_edit(repo, comment_id, body: str, *, info=None, env=None, urlopen=None,
                 runner=None) -> Result:
    """Edit comment `comment_id`."""
    return _dispatch("comment_edit", repo, (comment_id, body), info=info, env=env,
                     urlopen=urlopen, runner=runner)


def label_add(repo, number, name: str, *, info=None, env=None, urlopen=None,
              runner=None) -> Result:
    """Apply label `name` to PR `number`."""
    return _dispatch("label_add", repo, (number, name), info=info, env=env,
                     urlopen=urlopen, runner=runner)


def label_remove(repo, number, name: str, *, info=None, env=None, urlopen=None,
                 runner=None) -> Result:
    """Remove label `name` from PR `number`."""
    return _dispatch("label_remove", repo, (number, name), info=info, env=env,
                     urlopen=urlopen, runner=runner)


def main(argv=None) -> int:
    """This helper's command line lives in `forge_cli.py` (file-size split)."""
    import forge_cli
    return forge_cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
