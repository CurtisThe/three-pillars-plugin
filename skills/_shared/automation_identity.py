"""automation_identity.py — the one identity core for automation's `gh` writes.

design: review-proof-ambient-gh-identity (built on pr-author-bot-account)

Every automation write that reaches GitHub (PR creation, review digests, thread replies,
labels, certificate comments) resolves its author here, so there is exactly one implementation
of `gh auth token --user`. **No `gh auth switch` anywhere** (a machine-global mutation, racy
under parallel fleet workers). **No token at rest**: the token is fetched per call, lives only
in a local variable and one child process env, and never reaches a log line, an exception
message or a returned value. `os.environ` is never mutated.

Config comes from `.three-pillars/config.json`: `github.pr_author_account` names the account
and `github.used_for` scopes PR *authorship* only (`resolve_pr_author`); every other automation
write uses the account whatever `used_for` says (`resolve_automation_account`). With no account
the write path is byte-identical to a bare `gh` call: no `env` key is added and the token
runner never runs. With an account whose token is unavailable, `BotAuthUnavailable` is raised
before anything runs, never a silent fallback to the ambient login (that would re-create the
self-approval trap this identity exists to remove).

Opt-in exception (per-developer-automation-account): `github.per_developer_author: "self"` runs
the write on the ambient gh login when the bot token cannot be fetched (one stderr line, no token).

`run_gh_write` defaults `config=DISCOVER`: it loads the repo config from the git toplevel, so
the identity is picked by the helper and never by a prompt. An explicit `config=None` or `{}`
stays the ambient path. `github_pr_author.py` re-exports the names that used to live there.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


class BotAuthUnavailable(RuntimeError):
    """Raised when a configured PR-author bot account cannot be honored.

    Covers two distinct triggers, both fail-loud (never a silent ambient
    fallback): (1) the configured account failed its `gh auth token --user`
    probe, and (2) the `github` config block is present but structurally
    unusable (non-dict, malformed account, unknown `used_for`).
    """


def resolve_pr_author(config: dict, context: str) -> "str | None":
    """Resolve which account (if any) should author the PR.

    Pure. Returns `github.pr_author_account` iff it is a non-empty str AND
    (`used_for` == "all-prs" or ("autonomous-only" and context == "autonomous")).
    `used_for` null/absent folds to "all-prs".

    Fail-loud asymmetry: a config with NO `github` key (or
    `pr_author_account: null`) → None (plain path, byte-identical to today).
    A PRESENT-yet-unusable `github` block — non-dict `github`, non-str
    non-null `pr_author_account`, empty-str account, unknown `used_for`
    (only when an account IS configured) — raises `BotAuthUnavailable`.

    `context` not in {"manual", "autonomous"} → ValueError (caller bug).
    """
    if context not in ("manual", "autonomous"):
        raise ValueError(
            f"context must be 'manual' or 'autonomous', got {context!r}"
        )

    cfg = config if isinstance(config, dict) else {}
    if "github" not in cfg:
        return None

    github = cfg["github"]
    if not isinstance(github, dict):
        raise BotAuthUnavailable(
            "`.three-pillars/config.json`'s `github` block is present but is "
            f"not an object (got {type(github).__name__}); cannot determine "
            "the PR-author account. Fix the config or remove the `github` "
            "key to fall back to ambient gh auth."
        )

    account = github.get("pr_author_account")
    if account is None:
        return None

    if not isinstance(account, str) or account == "":
        raise BotAuthUnavailable(
            "`github.pr_author_account` is configured but is not a usable "
            f"login (got {account!r}). Fix `.three-pillars/config.json` or "
            "clear `github.pr_author_account` to disable bot-authored PRs."
        )

    used_for = github.get("used_for")
    if used_for is None:
        used_for = "all-prs"
    if used_for not in ("all-prs", "autonomous-only"):
        raise BotAuthUnavailable(
            f"`github.used_for` is set to an unknown value {used_for!r} for "
            f"configured account {account!r}. Expected 'all-prs' or "
            "'autonomous-only'. Fix `.three-pillars/config.json`."
        )

    if used_for == "all-prs":
        return account
    # used_for == "autonomous-only"
    return account if context == "autonomous" else None


def bot_token(account: str, runner=None) -> str:
    """`gh auth token --user <account>`; non-zero/empty → BotAuthUnavailable.

    Fail loud, never fall back — a silent fallback to ambient auth re-creates
    the self-approval trap the design exists to remove. The probe CAPTURES
    stdout (never inherited) — `gh auth token` prints the credential, and an
    inheriting runner would leak it into the terminal/transcript.
    """
    run = runner or (
        lambda argv: subprocess.run(argv, capture_output=True, text=True)
    )
    result = run(["gh", "auth", "token", "--user", account])
    token = (result.stdout or "").strip() if result.returncode == 0 else ""
    if result.returncode != 0 or not token:
        raise BotAuthUnavailable(
            f"GitHub bot account {account!r} is not available via "
            f"`gh auth token --user {account}` — the account may not be "
            "logged into this machine's gh keyring. Fix by either: "
            f"(1) run `gh auth login` and authenticate as {account}, adding "
            "it to the multi-account keyring (`gh auth token --user` "
            "requires a modern gh, ~2.40+), or "
            "(2) clear `github.pr_author_account` in "
            "`.three-pillars/config.json` to disable bot-authored PRs, or "
            "(3) set `github.per_developer_author: \"self\"` to run as your own gh login."
        )
    return token


def load_repo_config(repo: Path) -> dict:
    """CLI-level config load: missing file -> {} (unconfigured, plain path);
    present-but-unparseable JSON -> BotAuthUnavailable (fail loud — a
    configured bot account cannot be ruled out, so this refuses rather than
    silently falling back to ambient gh auth). `repo` is the git toplevel
    when `--repo` is omitted (see `_default_repo_root`), not raw cwd — a
    "missing" config here means genuinely absent, not "wrong directory"."""
    config_path = repo / ".three-pillars" / "config.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise BotAuthUnavailable(
            "`.three-pillars/config.json` exists but could not be parsed "
            f"({exc}); a configured PR-author bot account cannot be ruled "
            "out. Fix or remove the file to proceed."
        ) from exc


def _default_repo_root() -> Path:
    """Resolve the repo root to use when `--repo` is NOT passed explicitly.

    Walks to the git toplevel (`git rev-parse --show-toplevel`) rather than
    trusting cwd — invoked from a subdirectory of a configured repo, a raw
    `Path(".").resolve()` finds no `.three-pillars/config.json`, cannot tell
    "config genuinely absent" from "wrong cwd", and silently resolves
    "unconfigured" (plain ambient `gh pr create`, no bot token, no
    reviewer) — the exact silent-ambient-authorship class this chokepoint
    exists to forbid. Falls back to `Path(".").resolve()` when not inside a
    git repo (`gh pr create` itself requires a git repo, so the fallback
    only affects degenerate/non-git invocations).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=".",
        )
    except OSError:
        return Path(".").resolve()
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return Path(".").resolve()


class _Discover:
    """Type of the `DISCOVER` sentinel (a distinct object, so `None` and `{}` stay explicit)."""

    def __repr__(self) -> str:
        return "DISCOVER"


DISCOVER = _Discover()


def resolve_automation_account(config: dict) -> "str | None":
    """The account every automation write runs as, or None (ambient login).

    `used_for` scopes PR authorship only, so this resolves in the autonomous context: an
    `autonomous-only` account still posts digests, replies, labels and certificates.
    Raises `BotAuthUnavailable` for a present-yet-unusable `github` block.
    """
    return resolve_pr_author(config, "autonomous")


def _gate_mode(config) -> str:
    """The read-side mode: an invalid value is `off`, never a raise (the gate prunes it too)."""
    try:
        return per_developer_mode(config)
    except BotAuthUnavailable:
        return "off"


def trusted_digest_authors(config, self_login_fn, pr_author_fn=None) -> frozenset:
    """Lowercased logins whose posted review-proof digests count as proof at the merge gate.

    With `github.pr_author_account` set the trusted set is that account plus
    `review.automation_identities`, and the ambient login is never asked, so the same
    comments give the same verdict under any token. With no account it is the gh self login
    plus the extras (`self_login_fn` is called only then). A malformed `github` block raises
    `BotAuthUnavailable`; the gate's callers fail closed on it.

    Under `per_developer_author: self` the PR author (`pr_author_fn`) joins the set, self-attested.

    DELIBERATELY NARROWER than human_approval.automation_identities (review finding on
    PR #109): the digest allowlist is the DUAL of the approval denylist, so extra members make
    a denylist stricter but make THIS allowlist weaker. The hardcoded Copilot/native-bot floor
    is excluded: those identities never post digests, and on expects_copilot=true repos their
    bodies are model-generated from attacker-influencible PR context, so trusting them would
    let a prompt-injected comment mint proof. An unresolvable self login only SHRINKS the set,
    so the framework's own digests stop matching: fail-closed (dual of human_approval's F2,
    where a shrunken set fails OPEN and must hard-abort).
    """
    account = resolve_automation_account(config)
    members = {account.lower()} if account else set()
    if not account:
        try:
            self_login = self_login_fn()
        except Exception:
            self_login = None
        if isinstance(self_login, str) and self_login:
            members.add(self_login.lower())
    if pr_author_fn is not None and _gate_mode(config) == "self":
        try:  # any lookup error leaves the set as it was (fail closed)
            author = pr_author_fn()
        except Exception:
            author = None
        if isinstance(author, str) and author:
            members.add(author.lower())
    review = config.get("review") if isinstance(config, dict) else None
    extra = review.get("automation_identities") if isinstance(review, dict) else None
    if isinstance(extra, list):
        members.update(x.lower() for x in extra if isinstance(x, str) and x)
    return frozenset(members)


def trusted_digest_authors_for_pr(config, pr_url, self_login_fn, head_fn=None) -> frozenset:
    """`trusted_digest_authors` with the PR author bound to `pr_url`, fetched only under `self`."""
    if _gate_mode(config) != "self":
        return trusted_digest_authors(config, self_login_fn)
    import per_developer_author
    return trusted_digest_authors(
        config, self_login_fn, per_developer_author.pr_author_fn_for(pr_url, head_fn))


def token_env(token: str, base_env: "dict | None" = None) -> dict:
    """A copy of `base_env` (default `os.environ`) with `GH_TOKEN` set; nothing is mutated."""
    return {**(os.environ if base_env is None else base_env), "GH_TOKEN": token}


def account_env(account: str, base_env: "dict | None" = None, token_runner=None) -> dict:
    """The child env that runs `gh` as `account`: the token is fetched now, per call."""
    return token_env(bot_token(account, runner=token_runner), base_env)


def per_developer_mode(config) -> str:
    """`github.per_developer_author`: `"off"` when absent or null; any other non-enum value raises."""
    github = config.get("github") if isinstance(config, dict) else None
    value = github.get("per_developer_author") if isinstance(github, dict) else None
    if value is None:
        return "off"
    if value not in ("off", "self"):
        raise BotAuthUnavailable(
            f"`github.per_developer_author` is {value!r}; expected 'off' or 'self'.")
    return value


def _login_runner(argv, **kwargs):
    return subprocess.run(argv, **kwargs)  # looked up at call time: tests patch it


_AMBIENT: list = []


def _reset_ambient_login() -> None:  # test seam
    _AMBIENT.clear()

def ambient_login(runner=None) -> str:
    """The ambient `gh` login, resolved once per process; a failed lookup raises `BotAuthUnavailable`."""
    if _AMBIENT:
        return _AMBIENT[0]
    result = (runner or _login_runner)(["gh", "api", "user", "--jq", ".login"],
                                       capture_output=True, text=True)
    login = (result.stdout or "").strip() if result.returncode == 0 else ""
    if not login:
        raise BotAuthUnavailable("per_developer_author: self needs the gh login; `gh api user` failed.")
    _AMBIENT.append(login)
    return login


def _account_env_or_ambient(account: str, config: dict, base_env: "dict | None" = None,
                            token_runner=None, login_runner=None) -> "dict | None":
    """`account_env`, or None (the ambient path) when the token is unavailable under `self`."""
    try:
        return account_env(account, base_env, token_runner=token_runner)
    except BotAuthUnavailable:
        if per_developer_mode(config) != "self":
            raise
    fresh = not _AMBIENT  # one notice per process, like the login lookup
    login = ambient_login(login_runner)
    if fresh:
        print(f"per_developer_author: self — {account} not in this gh keyring; "
              f"automation writes run as {login}", file=sys.stderr)
    return None


def automation_env(config: dict, base_env: "dict | None" = None,
                   token_runner=None) -> "dict | None":
    """`account_env` for the configured automation account; None when none (or `self` fallback)."""
    account = resolve_automation_account(config)
    per_developer_mode(config)  # eager: a bad value raises even with a token or no account
    if account is None:
        return None
    return _account_env_or_ambient(account, config, base_env, token_runner)


def _default_runner(argv, **kwargs):
    return subprocess.run(argv, **kwargs)  # looked up at call time: tests patch it


def run_gh_write(argv, *, config=DISCOVER, runner=None, env=None, token_runner=None,
                 **run_kwargs):
    """Run one gh write as the configured automation account; return the runner's result.

    `config=DISCOVER` (default) loads the repo config from the git toplevel; an explicit
    `None`/`{}` is the ambient path. No account → `runner(argv, **run_kwargs)` exactly as
    today (a caller-supplied `env` is passed through, none is added) and the token runner
    never runs. An account → `runner(argv, env=<env + GH_TOKEN>, **run_kwargs)`. A token that
    cannot be fetched raises `BotAuthUnavailable` and `runner` is never called.
    """
    if config is DISCOVER:
        config = load_repo_config(_default_repo_root())
    run = runner or _default_runner
    child_env = automation_env(config, env, token_runner=token_runner)
    if child_env is not None:
        return run(argv, env=child_env, **run_kwargs)
    if env is not None:
        run_kwargs["env"] = env
    return run(argv, **run_kwargs)
