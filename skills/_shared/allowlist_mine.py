#!/usr/bin/env python3
"""Mine Claude Code transcripts for per-prefix Bash calls and auto-mode denials.

Design classifier-allowlist, Task 1.4. Output holds prefixes, counts and denial
reasons only: no raw argument leaves this module. Anything the test-pinned deny
set screens, and anything that cannot be parsed whole, is counted but never
becomes a candidate. The denial matcher is calibrated on the two observed
strings: "... [Modify Shared Resources]." (completed-tp-designs/
run-tooling-footguns/decisions.md) and "... Reason: Blocked by classifier."
(completed-tp-designs/fleet-worker-turn-ending-error-resume/seed.md).
Stdlib only; writes nothing.
"""
import argparse
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import allowlist_settings as st  # noqa: E402
from allowlist_normalize import normalize  # noqa: E402
from attempt_scan import _result_text, _tool_calls  # noqa: E402
from transcript_tail import read_records  # noqa: E402

DENIAL_RE = re.compile(
    r"(?i)denied by the Claude Code auto mode classifier"
    r"|auto[- ]mode classifier.{0,40}\b(denied|blocked)\b"
    r"|\b(denied|blocked)\b.{0,80}auto[- ]mode classifier")
_REASON1 = re.compile(r"Reason:\s*\[?([^\]\n.]{1,60})")
_REASON2 = re.compile(r"\[([^\]\n]{1,60})\]")
NO_TRANSCRIPTS = ("no transcripts found; the shipped list is "
                  "skills/_shared/allowlist/recommended.json")


def _reason(text):
    m = _REASON1.search(text) or _REASON2.search(text)
    return m.group(1).strip() if m else "(no reason text)"


def _results(records):
    out = {}
    for rec in records:
        content = (rec.get("message") or {}).get("content") if rec.get("type") == "user" else None
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                out[b["tool_use_id"]] = (_result_text(b), bool(b.get("is_error")))
    return out


def _bump(table, key, denied):
    c = table.setdefault(key, [0, 0, []])
    c[0] += 1
    c[1] += denied
    return c


def mine(paths, denial_re=DENIAL_RE, repo=None):
    roots = (str(Path(repo or Path.cwd()).resolve()),)
    rule, env, gitc = {}, {}, {}
    scr = {"calls": 0, "denials": 0}
    unp = {"calls": 0, "denials": 0}
    root_forms, other_denials, bad = {}, [], set()
    n = 0
    for path in paths:
        recs = read_records(path)
        n += 1
        res = _results(recs)
        for call in _tool_calls(recs):
            text, _err = res.get(call["id"], ("", False))
            denied = 1 if denial_re.search(text) else 0
            reason = _reason(text) if denied else ""
            if call["name"] != "Bash":
                if denied:
                    other_denials.append({"prefix": call["name"], "reason": reason})
                continue
            for sub in normalize(str(call["input"].get("command", "")), roots):
                if sub.root != "none":
                    root_forms[sub.root] = root_forms.get(sub.root, 0) + 1
                if sub.kind == "unparseable":
                    unp["calls"] += 1
                    unp["denials"] += denied
                elif sub.screen:
                    scr["calls"] += 1
                    scr["denials"] += denied
                    bad.add(sub.prefix)
                else:
                    table = {"env-prefixed": env, "git-C": gitc}.get(sub.kind, rule)
                    c = _bump(table, sub.prefix, denied)
                    if denied:
                        c[2].append(reason)
    prefixes, denials = [], list(other_denials)
    for prefix, (calls, dn, reasons) in rule.items():
        if prefix in bad:
            scr["calls"] += calls
            scr["denials"] += dn
            continue
        words = prefix.split()
        fw = len(words) > 1 and words[1].startswith("skills/")
        prefixes.append({"prefix": prefix, "calls": calls, "denials": dn, "framework": fw})
        denials += [{"prefix": prefix, "reason": r} for r in reasons]
    prefixes.sort(key=lambda e: (not e["framework"], -e["denials"], -e["calls"], e["prefix"]))
    lists = {}
    for name, table in (("env_prefixed", env), ("git_c", gitc)):
        lists[name] = [{"prefix": p, "calls": c[0], "denials": c[1]} for p, c in sorted(table.items())]
        denials += [{"prefix": p, "reason": r} for p, c in sorted(table.items()) for r in c[2]]
    return {"transcripts": n, "prefixes": prefixes, "denials": denials, "screened": scr,
            "unparseable": unp, "root_forms": root_forms, **lists}


def render(r):
    out = ["candidates"]
    out += [f"  {e['prefix']}  calls={e['calls']} denials={e['denials']}"
            + ("  [framework]" if e["framework"] else "") for e in r["prefixes"]]
    out.append("denials")
    out += [f"  {d['prefix']}  [{d['reason']}]" for d in r["denials"]]
    out.append("not coverable (env prefix)")
    out += [f"  {e['prefix']}  calls={e['calls']} denials={e['denials']}" for e in r["env_prefixed"]]
    out.append("exact-path only (git -C)")
    out += [f"  {e['prefix']}  calls={e['calls']} denials={e['denials']}" for e in r["git_c"]]
    out.append("root forms")
    out += [f"  {k}: {v}" for k, v in sorted(r["root_forms"].items())]
    out.append(f"unparseable: {r['unparseable']['calls']} calls")
    out.append(f"screened by the deny set: {r['screened']['calls']} calls, "
               f"{r['screened']['denials']} denials")
    if r["transcripts"] > 0 and not r["denials"] and not r["screened"]["denials"]:
        out.append("note: no denial matched DENIAL_RE")
    return "\n".join(out)


def _expanded(repo):
    repo = Path(repo or Path.cwd()).resolve()
    forge, defaulted = st.forge_kind(repo)
    rec = st.load()
    tp_root = Path(st.__file__).resolve().parents[2]
    entries = st.entries_for(rec, forge, tp_root)
    allow = st.expand(entries, st.root_forms(tp_root, repo))
    return allow, st.deny_rules(rec), (entries, tp_root, forge, defaulted)


def print_settings(repo):
    """JSON snippet on stdout, hint lines on stderr; writes no file."""
    allow, deny, (entries, tp_root, forge, defaulted) = _expanded(repo)
    target = st.settings_path()
    obj, err = st.read_settings(target)
    print(json.dumps(st.snippet(allow, deny), indent=2))
    print("\n".join(st.hints(target, entries, obj, tp_root, forge, defaulted, err)),
          file=sys.stderr)
    return 0


def check_settings(repo):
    """The stale-list advisory on stdout; 0 on every read path, 2 only on a crash."""
    try:
        repo = Path(repo or Path.cwd()).resolve()
        forge, _defaulted = st.forge_kind(repo)
        entries = st.entries_for(st.load(), forge, st.DEFAULT_TP_ROOT)
        lines = st.check(entries, st.settings_path(), repo, st.DEFAULT_TP_ROOT)
    except Exception as exc:  # noqa: BLE001 - advisory by design: reported, never raised
        print(f"advisory: allowlist check crashed: {type(exc).__name__}")
        return 2
    if lines:
        print("\n".join(lines))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transcripts", action="append", metavar="GLOB")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--denial-regex", metavar="PATTERN")
    ap.add_argument("--repo", metavar="PATH")
    ap.add_argument("--print-settings", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="advisory: report recommended entries the active settings lack")
    a = ap.parse_args(argv)
    if a.check:
        return check_settings(a.repo)
    if a.print_settings:
        return print_settings(a.repo)
    if a.transcripts:
        paths = sorted({p for g in a.transcripts for p in glob.glob(g, recursive=True)})
    else:
        paths = sorted(str(p) for p in Path.home().glob(".claude*/projects/**/*.jsonl"))
    if not paths:
        print(NO_TRANSCRIPTS)
        allow, _deny, _ctx = _expanded(a.repo)
        print("\n".join(allow))
        return 0
    rx = re.compile(a.denial_regex) if a.denial_regex else DENIAL_RE
    r = mine(paths, rx, a.repo)
    print(json.dumps(r, indent=2) if a.json else render(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
