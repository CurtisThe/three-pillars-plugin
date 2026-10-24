"""scratch_leftovers.py — detect scratch created outside the worktree (design: run-scratch-in-fence 1.2).

``provision`` writes a baseline of the watch set to ``<git common dir>/tp-scratch/<slug>/baseline.json``;
``check`` lists every path created since (exit 1); ``accept`` records an inspected path
(and appends a ``### [scratch_leftovers] accepted <path>`` entry to the design's decisions.md, exit 2 without it);
``snapshot`` prints the current scan. Stdlib only.
"""
import argparse
import datetime
import fnmatch
import json
import os
import stat
import subprocess
import sys

import run_scratch

SCRATCH_AREAS = tuple("/" + n for n in ("tmp", "var/tmp", "dev/shm"))
AREA_DEPTH = 3
HOME_DEPTH = 2
HOME_DEEP = (".config", ".cache", ".local/share")  # a new entry directly inside is reported
DURABLE_STATE = (
    "<git common dir>/objects", "<git common dir>/tp-children", "<git common dir>/tp-ladder",
    "<git common dir>/tp-scratch", "~/.local/state/tp-local", "~/.three-pillars",
    "$CLAUDE_CONFIG_DIR/projects",
)
NOISE_AREA = (
    "pytest-of-*", "tmp*", "pip-*", "hsperfdata_*", "vscode-*", "ssh-*", ".org.chromium.*",
    ".com.google.Chrome.*", ".X*-lock", "pulse-*", "snap.*", "dbus-*", "systemd-private-*",
    ".X11-unix", ".ICE-unix", ".font-unix", ".Test-unix", "tmux-*", "snap-private-tmp", "claude-%d" % os.getuid(),
)
NOISE_HOME = (
    ".claude*", ".mozilla", ".var", ".thumbnails", ".Trash", "Downloads", ".xsession-errors*",
    ".ICEauthority", ".Xauthority", ".dbus", ".bash_history", ".zsh_history", ".lesshst",
    ".viminfo", ".python_history",
)
RUN_STOP = "stop: the finalizer or the operator inspects the path and accepts it"
RECOVERY = (
    "if this is not the run's own path (a sibling session's entry): inspect it (owner, ctime, "
    "content), then scratch_leftovers.py accept --path P --reason R; otherwise remove it "
    "(TP_SCRATCH_ALLOW, set at provision, names paths to skip)"
)


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def common_dir(worktree):
    for cwd in (worktree, os.getcwd()):
        if cwd and os.path.isdir(str(cwd)):
            out = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
            if out:
                return out
    return ""


def watch_areas(env, areas, worktree):
    home = os.path.realpath(env.get("HOME") or os.path.expanduser("~"))
    roots = [os.path.realpath(a) for a in areas if os.path.isdir(a)]
    if os.path.isdir(os.path.join(home, "t")):
        roots.append(os.path.join(home, "t"))
    tmpdir = env.get("TMPDIR")
    if tmpdir:
        par = os.path.realpath(os.path.dirname(os.path.normpath(tmpdir)))
        wt = os.path.realpath(str(worktree))
        bad = par in roots or par in (home, "/") or home.startswith(par + "/")
        if not bad and par != wt and not par.startswith(wt + "/") and os.path.isdir(par):
            roots.append(par)
    return roots


def _kind(st):
    return "dir" if stat.S_ISDIR(st.st_mode) else "link" if stat.S_ISLNK(st.st_mode) else "file"


def _scan(root, depth, skip=()):
    """{path: [type, mtime_ns]} for entries up to ``depth`` below root; skip prunes by path."""
    found = {}

    def walk(d, level):
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            return
        for e in entries:
            if e.path in skip:
                continue
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            kind = _kind(st)
            found[e.path] = [kind, st.st_mtime_ns]
            if kind == "dir" and level < depth:
                walk(e.path, level + 1)

    walk(root, 1)
    return found


def snapshot(areas, home):
    snap = {}
    for r in areas:
        snap.update(_scan(r, AREA_DEPTH))
    snap.update(_scan(home, HOME_DEPTH, skip=set(areas)))
    for rel in HOME_DEEP:
        snap.update(_scan(os.path.join(home, rel), 1))
    return snap


def _noisy(name, in_home, tag):
    if in_home:
        return any(fnmatch.fnmatchcase(name, p) for p in NOISE_HOME)
    if name.startswith("tpt-"):
        return not name.startswith("tpt-" + tag + "-")
    return any(fnmatch.fnmatchcase(name, p) for p in NOISE_AREA)


def durable_paths(common, home, env):
    cfg = env.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
    out = []
    for t in DURABLE_STATE:
        p = (t.replace("<git common dir>", common).replace("$CLAUDE_CONFIG_DIR", cfg)
             .replace("~", home, 1) if t.startswith("~") else
             t.replace("<git common dir>", common).replace("$CLAUDE_CONFIG_DIR", cfg))
        out.append(os.path.normpath(p))
    return out


def _under(path, base):
    return path == base or path.startswith(base.rstrip("/") + "/")


def _baseline_path(common, slug):
    return os.path.join(common, "tp-scratch", slug, "baseline.json")


def _slug(args, worktree):
    if args.slug:
        return args.slug
    br = _git(worktree, "branch", "--show-current")
    return br[3:] if br.startswith("tp/") else br


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def provision(args, env, areas, worktree, common, slug):
    existed = os.path.isdir(run_scratch.run_dir(worktree))
    d = run_scratch.ensure_run_dir(worktree)
    if d is None or not common:
        print("scratch-leftover: cannot create run dir")
        return 1
    bp = _baseline_path(common, slug)
    if not os.path.exists(bp):
        home = os.path.realpath(env.get("HOME") or os.path.expanduser("~"))
        roots = watch_areas(env, areas, worktree)
        base = {
            "worktree": os.path.realpath(str(worktree)), "tag": run_scratch.tag(worktree),
            "home": home, "areas": roots, "accepted": [],
            "allow": [n for n in (env.get("TP_SCRATCH_ALLOW") or "").split(":") if n],
            "entries": snapshot(roots, home),
        }
        os.makedirs(os.path.dirname(bp), exist_ok=True)
        tmp = bp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(base, f, sort_keys=True)
        os.replace(tmp, bp)
    print(d, "exists" if existed else "created")
    return 0


def _provisioned(design_dir):
    try:
        with open(os.path.join(design_dir, "decisions.md"), encoding="utf-8") as f:
            return any("scratch-provisioned" in ln for ln in f)
    except OSError:
        return False


def check(args, env, common, slug):
    base = _load(_baseline_path(common, slug)) if common else None
    if base is None:
        if args.design_dir and not _provisioned(args.design_dir):
            if args.expect:
                print("scratch-leftover: no run scratch")
                return 1
            print("scratch-leftover: skipped (no run scratch)")
            return 0
        print("scratch-leftover: no baseline")
        return 1
    home, wt, tag = base["home"], base["worktree"], base["tag"]
    entries, roots = base["entries"], base["areas"]
    durable = durable_paths(common, home, env)
    snap = snapshot(roots, home)
    area_set = set(roots)
    found, new_dirs = [], []
    for path in sorted(snap):
        kind, mtime = snap[path]
        in_home = not any(_under(path, r) for r in roots)
        if _under(path, wt) or any(_under(path, d) or _under(d, path) for d in durable):
            continue
        if any(_under(path, n) for n in new_dirs):
            continue
        if _noisy(os.path.basename(path), in_home, tag):
            new_dirs.append(path)
            continue
        old = entries.get(path)
        if old is None:
            parent = os.path.dirname(path)
            if in_home and parent != home and parent in entries and \
                    os.path.relpath(parent, home) not in HOME_DEEP:
                continue  # home is new-entries-only: a write into an existing dir escapes (stated gap)
            found.append(path)
            new_dirs.append(path)
        elif not in_home and kind == "dir" and old[0] == "dir" and old[1] != mtime and path not in area_set:
            found.append(path)
    bad, allowed = [], []
    for path in found:
        name = os.path.basename(path)
        acc = next((a for a in base["accepted"] if _under(path, a["path"])), None)
        if any(fnmatch.fnmatchcase(name, n) for n in base["allow"]):
            allowed.append("scratch-allowed: %s (allow)" % path)
        elif acc:
            allowed.append("scratch-allowed: %s (accepted %s %s)" % (path, acc["date"], acc["reason"]))
        else:
            bad.append(path)
    for line in allowed:
        print(line)
    for path in bad:
        print("scratch-leftover: " + path)
    if bad:
        print(RUN_STOP if env.get("TP_DESIGN_RUN") == "1" else RECOVERY)
    return 1 if bad else 0


def _design_dir_ok(d, base, slug, worktree, common):
    """True when ``d`` is ``<repo>/three-pillars-docs/{tp-designs,completed-tp-designs}/<slug>``."""
    seat = os.path.dirname(os.path.realpath(common)) if common else ""
    real = os.path.realpath(d)
    return any(real == os.path.join(os.path.realpath(repo), "three-pillars-docs", sub, slug)  # no link below the repo
               for repo in (str(worktree), base["worktree"], seat) if repo
               for sub in ("tp-designs", "completed-tp-designs"))


def _decisions_log(args, base, slug, worktree):
    """The design's decisions.md path (its directory must exist), or None."""
    rel = os.path.join("three-pillars-docs", "tp-designs", slug)
    for d in (args.design_dir, os.path.join(str(worktree), rel), os.path.join(base["worktree"], rel)):
        if d and os.path.isdir(d):
            return os.path.join(d, "decisions.md")
    return None


def _audit(log, path, date, reason, env):
    who = "TP_DESIGN_RUN=%s user=%s" % (env.get("TP_DESIGN_RUN") or "unset",
                                         env.get("USER") or env.get("LOGNAME") or "unknown")
    entry = "\n### [scratch_leftovers] accepted %s\n- date: %s\n- reason: %s\n- who: %s\n" % (
        path, date, reason, who)
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        return False
    return True


def accept(args, env, common, slug, worktree):
    bp = _baseline_path(common, slug)
    base = _load(bp) if common else None
    path = os.path.abspath(args.path or "")
    if base is None or not args.path or not args.reason:
        print("accept needs a baseline, --path and --reason")
        return 2
    roots = base["areas"] + [base["home"]]
    if not os.path.lexists(path) or not any(_under(path, r) and path != r for r in roots):
        print("accept: path missing or outside the watch set: " + path)
        return 2
    if args.design_dir and not _design_dir_ok(args.design_dir, base, slug, worktree, common):
        print("accept: --design-dir must be <repo>/three-pillars-docs/{tp-designs,completed-tp-designs}/%s"
              "; nothing accepted" % slug)
        return 2
    date = datetime.date.today().isoformat()
    log = _decisions_log(args, base, slug, worktree)
    if log is None or not _audit(log, path, date, args.reason, env):
        print("accept: cannot write the decisions.md entry (design dir for %s not found or "
              "not writable); nothing accepted" % slug)
        return 2
    base["accepted"] = [a for a in base["accepted"] if a["path"] != path] + [
        {"path": path, "date": date, "reason": args.reason}]
    with open(bp, "w", encoding="utf-8") as f:
        json.dump(base, f, sort_keys=True)
    print("accepted " + path)
    return 0


def main(argv=None, env=None, areas=None):
    env = dict(os.environ) if env is None else env
    areas = SCRATCH_AREAS if areas is None else areas
    ap = argparse.ArgumentParser(prog="scratch_leftovers.py")
    ap.add_argument("cmd", choices=("provision", "snapshot", "check", "accept"))
    ap.add_argument("--slug")
    ap.add_argument("--worktree")
    ap.add_argument("--design-dir")
    ap.add_argument("--expect", action="store_true")
    ap.add_argument("--path")
    ap.add_argument("--reason")
    try:
        args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        return int(e.code or 0)
    worktree = args.worktree or _git(os.getcwd(), "rev-parse", "--show-toplevel") or os.getcwd()
    common, slug = common_dir(worktree), _slug(args, worktree)
    if args.cmd == "provision":
        return provision(args, env, areas, worktree, common, slug)
    if args.cmd == "snapshot":
        home = os.path.realpath(env.get("HOME") or os.path.expanduser("~"))
        print(json.dumps(snapshot(watch_areas(env, areas, worktree), home), sort_keys=True))
        return 0
    if args.cmd == "accept":
        return accept(args, env, common, slug, worktree)
    return check(args, env, common, slug)


if __name__ == "__main__":
    sys.exit(main())
