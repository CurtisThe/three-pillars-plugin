"""The reviewed recommended allow list (classifier-allowlist design) and its expansion.

`recommended.json` holds the core entries; the pro build adds `recommended_pro.json`
next to it, merged after the core entries when present. Nothing here writes a settings file.
"""
import json
import os
from pathlib import Path

import allowlist_rules

RECOMMENDED = Path(__file__).resolve().parent / "allowlist" / "recommended.json"
RECOMMENDED_PRO = RECOMMENDED.with_name("recommended_pro.json")


def load(path=RECOMMENDED):
    """Load the list; the default path also merges the pro entries when shipped."""
    path = Path(path)
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec.setdefault("allow", [])
    rec.setdefault("deny", [])
    if path == RECOMMENDED and RECOMMENDED_PRO.exists():
        pro = json.loads(RECOMMENDED_PRO.read_text(encoding="utf-8"))
        rec["allow"] = list(rec["allow"]) + list(pro.get("allow", []))
    return rec


def entries_for(rec, forge, tp_root):
    """Entries for this forge whose script (if any) exists under tp_root."""
    tp_root = Path(tp_root)
    out = []
    for e in rec.get("allow", []):
        if e.get("forge") not in (None, forge):
            continue
        if e.get("script") and not (tp_root / e["script"]).is_file():
            continue
        out.append(e)
    return out


def root_forms(tp_root, repo):
    """The root texts a rule is written for; never the empty root (repo kept for the signature)."""
    del repo
    return ['"$TP_ROOT"/', f"{Path(tp_root)}/"]


def expand(entries, roots, repos=()):
    """Substitute {ROOT} and turn each command into its rules, de-duplicated in order.

    `repos` is ignored; it is kept so older callers still work.
    """
    del repos
    rules = []
    seen = set()
    for e in entries:
        cmds = [e["cmd"]]
        if "{ROOT}" in e["cmd"]:
            cmds = [c.replace("{ROOT}", r) for c in cmds for r in roots]
        for cmd in cmds:
            if e.get("exact"):
                allowlist_rules.validate_rule(f"Bash({cmd})")
                new = [f"Bash({cmd})"]
            else:
                new = allowlist_rules.rule_pair(cmd)
            for r in new:
                if r not in seen:
                    seen.add(r)
                    rules.append(r)
    return rules


def deny_rules(rec):
    """The deny rule strings, in file order."""
    return [e["rule"] for e in rec.get("deny", [])]


TP_ROOT_LITERAL = '"$TP_ROOT"/'
VERIFY = (
    "VERIFY: open a new auto-mode session and check /permissions lists the allow and deny rules "
    "(none dropped; a startup warning about a * before the git subcommand in the git -C * deny "
    "patterns is expected)",
    "VERIFY: ask it to run `git worktree list` (denied before) and confirm no classifier check ran",
    "VERIFY: negative probes `git status $(echo x)`, `git status `echo x`` and `git diff > /var/x` "
    "must each still reach the classifier, and so must the quoted-option probe "
    "`git log -1 \"--output=/var/x\"` (it is refused on a normal call; ask the session to run it "
    "only on a scratch repo, or just confirm /permissions shows no `git log *` or `git diff *` "
    "rule); if one runs unchecked, tell the maintainers: the git * pairs and the no-argument "
    "scripts then ship as bare rules only",
    "VERIFY: run allowlist_mine.py over your transcripts and confirm denials are found, else tell "
    "the maintainers the denial wording changed",
)


def settings_path(env=os.environ):
    """The user-scope settings file the operator pastes into."""
    if env.get("CLAUDE_CONFIG_DIR"):
        return Path(env["CLAUDE_CONFIG_DIR"]) / "settings.json"
    return Path.home() / ".claude" / "settings.json"


def forge_kind(repo):
    """(kind, defaulted) from .three-pillars/config.json forge.kind."""
    try:
        cfg = json.loads((Path(repo) / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
        kind = cfg["forge"]["kind"]
        if isinstance(kind, str) and kind:
            return kind, False
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return "github", True


def snippet(allow, deny):
    return {"permissions": {"allow": allow, "deny": deny}}


def read_settings(path):
    """(object, error class name or None); never raises."""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        return (obj if isinstance(obj, dict) else {}), None
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError) as exc:
        return {}, type(exc).__name__


def _allow_of(settings_obj):
    allow = (settings_obj.get("permissions") or {}).get("allow") if isinstance(
        settings_obj.get("permissions"), dict) else None
    return set(allow) if isinstance(allow, list) else set()


def present_count(entries, allow_rules):
    """(k, n): entries whose primary rules are all present."""
    have = set(allow_rules)
    k = n = 0
    for e in entries:
        n += 1
        if all(r in have for r in expand([e], [TP_ROOT_LITERAL])):
            k += 1
    return k, n


def location_gaps(entries, allow_rules, tp_root):
    """[tp_root] when the install root's exact-path rules are not all present, else []."""
    have = set(allow_rules)
    root_entries = [e for e in entries if "{ROOT}" in e["cmd"]]
    if all(r in have for r in expand(root_entries, [f"{Path(tp_root)}/"])):
        return []
    return [str(tp_root)]


def hints(target, entries, settings_obj, tp_root=None, forge="github", defaulted=False,
          error=None):
    """The stderr lines for --print-settings."""
    lines = [f'target: {target} (paste the "permissions" block into it yourself; nothing was written)']
    if error:
        lines.append(f"cannot read {target}: {error}")
    allow = _allow_of(settings_obj)
    k, n = present_count(entries, allow)
    lines.append(f"{k} of {n} recommended entries already present")
    if tp_root is not None:
        lines += [f"no exact rules for {p}; re-run --print-settings after moving or upgrading "
                  "the plugin" for p in location_gaps(entries, allow, tp_root)]
    auto = settings_obj.get("autoMode")
    if isinstance(auto, dict) and auto.get("classifyAllShell") is True:
        lines.append("warning: autoMode.classifyAllShell is true; every shell call still reaches "
                     "the classifier, so these allow rules may not help")
    if defaulted:
        lines.append(f"forge: {forge} (default; set forge.kind in .three-pillars/config.json)")
    if forge == "gitea":
        lines.append("no Gitea rule: gh pr view, gh pr checks")
    return lines + list(VERIFY)


DEFAULT_TP_ROOT = Path(__file__).resolve().parents[2]


def _exists(path):
    try:
        Path(path).stat()
    except FileNotFoundError:
        return False
    except OSError:
        pass
    return True


def check(entries, user_path, repo, tp_root=DEFAULT_TP_ROOT):
    """The stale-list advisory: one line per finding, [] when there is nothing to say.

    The user-scope file `user_path` anchors the check: with no such file (CI, a fresh machine)
    the answer is []. Otherwise the `permissions.allow` of that file, `<repo>/.claude/settings.json`
    and `<repo>/.claude/settings.local.json` are unioned. A file that cannot be read gives only
    the `cannot read` lines, since the union is then unknown. Never raises on a read path.
    """
    if not _exists(user_path):
        return []
    repo = Path(repo)
    files = [Path(user_path), repo / ".claude" / "settings.json",
             repo / ".claude" / "settings.local.json"]
    allow, shell, unreadable = set(), [], []
    for path in (p for p in files if _exists(p)):
        obj, err = read_settings(path)
        if err:
            unreadable.append(f"advisory: cannot read {path}: {err}")
            continue
        allow |= _allow_of(obj)
        auto = obj.get("autoMode")
        if isinstance(auto, dict) and auto.get("classifyAllShell") is True:
            shell.append(path)
    if unreadable:
        return unreadable
    lines = []
    k, n = present_count(entries, allow)
    if k < n:
        lines.append(f"advisory: {n - k} of {n} recommended allow entries missing from the active "
                     'settings; print them with: python3 "$TP_ROOT"/skills/_shared/allowlist_mine.py '
                     "--print-settings")
    gaps = location_gaps(entries, allow, tp_root)
    if gaps:
        lines.append(f"advisory: no exact-path rules for {len(gaps)} current location(s): "
                     f"{', '.join(gaps)}; re-run --print-settings")
    lines += [f"advisory: autoMode.classifyAllShell is true in {p}; every Bash allow rule is "
              "suspended" for p in shell]
    return lines
