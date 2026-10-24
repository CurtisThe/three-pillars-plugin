"""Allowlist rule shapes: a command prefix becomes a bare rule plus a ' *' rule.

No other wildcard is allowed, and broad launcher heads are refused.
"""
import os
import re

BROAD_HEADS = frozenset({"python3", "python", "bash", "sh", "git", "gh", "tea", "tmux", "env", "node"})
_INTERPRETERS = frozenset({"python3", "python", "bash", "sh"})


class RuleError(ValueError):
    """A rule shape that is too broad or carries a disallowed wildcard."""


def rule_pair(cmd):
    cmd = cmd.strip()
    if not cmd:
        raise RuleError("empty command prefix")
    if "*" in cmd:
        raise RuleError(f"wildcard in command prefix: {cmd!r}")
    rules = [f"Bash({cmd})", f"Bash({cmd} *)"]
    for r in rules:
        validate_rule(r)
    return rules


def rule_matches(rule, text):
    inner = rule[len("Bash("):-1] if rule.startswith("Bash(") and rule.endswith(")") else rule
    if "*" not in inner:
        return text == inner
    if inner.endswith(" *") and "*" not in inner[:-2]:
        base = inner[:-2]
        return text == base or text.startswith(base + " ")
    pattern = ".*".join(re.escape(part) for part in inner.split("*"))
    return re.fullmatch(pattern, text, re.S) is not None


def validate_rule(rule):
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        raise RuleError(f"not a Bash rule: {rule!r}")
    inner = rule[len("Bash("):-1]
    base = inner[:-2] if inner.endswith(" *") else inner
    if "*" in base or ".." in base or ":*" in inner:
        raise RuleError(f"wildcard or traversal in rule: {rule!r}")
    tokens = base.split()
    if not tokens:
        raise RuleError(f"empty rule: {rule!r}")
    head = tokens[0]
    if len(tokens) == 1 and head in BROAD_HEADS:
        raise RuleError(f"broad rule: {rule!r}")
    if head in _INTERPRETERS and len(tokens) > 1 and tokens[1].startswith("-"):
        raise RuleError(f"interpreter flag rule: {rule!r}")
    if head in ("gh", "tea") and len(tokens) < 3:
        raise RuleError(f"gh/tea rule needs 3+ tokens: {rule!r}")


# tp-allow-fragile: test-pinned deny set (design Scope 3: process kill, send/email, rm, curl|sh, writes, settings), a security boundary, not a derived filter
DENY_HEADS = frozenset({
    "kill", "pkill", "killall", "rm", "curl", "wget", "sudo", "su", "ssh", "scp", "rsync", "eval",
    "mail", "mailx", "sendmail", "mutt", "msmtp", "tee", "dd", "cp", "mv", "ln", "chmod", "chown",
    "install", "shutdown", "reboot", "tmux", "xargs", "env", "exec", "setsid", "find",
})
# tp-allow-fragile: test-pinned deny set (design Scope 3: force-push, remote delete, writes), a security boundary, not a derived filter
GIT_DENY_VERBS = frozenset({
    "push", "reset", "clean", "checkout", "restore", "rm", "filter-branch", "update-ref", "config",
    "rebase", "gc", "prune", "remote", "tag",
})
# tp-allow-fragile: test-pinned deny set (design Scope 3: branch delete/force), a security boundary, not a derived filter
GIT_BRANCH_DENY_FLAGS = frozenset({"-D", "-d", "--delete", "-m", "-M", "--move", "-f", "--force"})
# tp-allow-fragile: test-pinned deny set (design Scope 3: worktree removal), a security boundary, not a derived filter
GIT_WORKTREE_DENY = frozenset({"remove", "prune", "move"})
READ_ONLY_FORGE = frozenset({
    ("gh", "pr", "view"), ("gh", "pr", "list"), ("gh", "pr", "checks"),
    ("tea", "pr", "list"), ("tea", "pulls", "list"),
})
# tp-allow-fragile: test-pinned deny set (design Scope 3: merge, teardown, process kill), a security boundary, not a derived filter
DENY_SCRIPTS = frozenset({"teardown.py", "design_run_tmux.py"})
# tp-allow-fragile: test-pinned deny set (design Scope 3: force-push, remote delete, writes), a security boundary, not a derived filter
DENY_LONG_ARGS = frozenset({
    "--force", "--force-with-lease", "--delete", "--upload-pack", "--receive-pack", "--exec",
    "--output", "--no-verify",
})
# tp-allow-fragile: test-pinned deny set (design Scope 3: writes, rm), a security boundary, not a derived filter
DENY_SHORT_ARGS = frozenset({"-delete", "-exec"})
# tp-allow-fragile: test-pinned deny set (design Scope 3: settings/permissions/CLAUDE.md/memory edits), a security boundary, not a derived filter
DENY_PATH_MARKERS = (
    "settings.json", "settings.local.json", "CLAUDE.md", "MEMORY.md", "/memory/", ".claude/",
)
_PY = frozenset({"python3", "python"})


def _git_verb(argv):
    i = 1
    while i < len(argv):
        if argv[i] in ("-C", "-c"):
            i += 2
        elif argv[i].startswith("-"):
            i += 1
        else:
            return i
    return None


def _long_arg_hit(tok):
    name = tok.split("=", 1)[0]
    if not name.startswith("--") or len(name) < 4:
        return None
    return next((d for d in sorted(DENY_LONG_ARGS) if d.startswith(name)), None)


def _screen_git(argv):
    i = _git_verb(argv)
    if i is None:
        return None
    verb = argv[i]
    if verb in GIT_DENY_VERBS:
        return f"git-write:{verb}"
    rest = argv[i + 1:]
    if verb == "branch":
        hit = next((a for a in rest if a in GIT_BRANCH_DENY_FLAGS), None)
        if hit:
            return f"git-branch:{hit}"
    if verb == "worktree" and rest and rest[0] in GIT_WORKTREE_DENY:
        return f"git-worktree:{rest[0]}"
    return None


def _screen_forge(argv):
    words = [a for a in argv if not a.startswith("-")][:3]
    if tuple(words) not in READ_ONLY_FORGE:
        return f"forge-write:{os.path.basename(argv[0])}"
    return None


_VALUED_OPTS = {"py": frozenset({"-W", "-X", "-Q"}), "sh": frozenset({"-o", "-O", "--rcfile", "--init-file"})}


def _is_interp(head):
    return head in _PY or head in ("bash", "sh") or re.fullmatch(r"python[0-9.]+", head) is not None


def _interp_scan(argv, head):
    """(inline, script_index) for an interpreter argv: option tokens are skipped, never read as the script."""
    valued = _VALUED_OPTS["sh" if head in ("bash", "sh") else "py"]
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok == "-":
            return True, None
        if tok == "--":
            i += 1
            break
        if not tok.startswith("-"):
            break
        if tok in valued:
            i += 2
            continue
        if not tok.startswith("--") and len(tok) > 1 and "c" in tok[1:] and tok[1] not in "WXQ":
            return True, None
        # a bundled shell flag ending in o/O (bash -euo pipefail) takes the next token as its value
        i += 2 if head in ("bash", "sh") and not tok.startswith("--") and tok[-1] in "oO" else 1
    return (False, i) if i < len(argv) else (True, None)


def _screen_head(argv, head):
    if head in DENY_HEADS:
        return f"head:{head}"
    if _is_interp(head):
        inline, idx = _interp_scan(argv, head)
        if inline:
            return f"inline-{'shell' if head in ('bash', 'sh') else 'code'}:{head}"
        if os.path.basename(argv[idx]) in DENY_SCRIPTS:
            return f"script:{os.path.basename(argv[idx])}"
    if head == "git":
        return _screen_git(argv)
    if head in ("gh", "tea"):
        return _screen_forge(argv)
    return None


def screen(argv):
    """Return a '<category>:<detail>' reason if argv is denied, else None."""
    if not argv:
        return None
    head = os.path.basename(argv[0])
    reason = _screen_head(argv, head)
    if reason:
        return reason
    args = argv[1:]
    if _is_interp(head):
        _inline, idx = _interp_scan(argv, head)
        args = argv[1:idx] + argv[idx + 1:] if idx is not None else argv[1:]
    for tok in args:
        hit = _long_arg_hit(tok)
        if hit:
            return f"arg:{hit}"
        if tok in DENY_SHORT_ARGS:
            return f"arg:{tok}"
        marker = next((m for m in DENY_PATH_MARKERS if m in tok), None)
        if marker:
            return f"path:{marker}"
    return None
