#!/usr/bin/env python3
"""resolve_script.py — resolve a FREE ``skills/_shared`` helper to its path.

The framework ships as TWO plugins at DIFFERENT roots (FREE core and PRO), and
``resolve_root.sh`` qualifies a root solely by the ``skills/_shared/first-run.md``
sentinel — which the PRO cache also carries. So ``$TP_ROOT`` can legitimately
land on the PRO cache, which does NOT carry FREE-only ``_shared`` modules, and
``python3 "$TP_ROOT"/skills/_shared/<name>`` dies with ``No such file or
directory`` (this failed live in PR #126, 2026-07-07).

This module refines ``$TP_ROOT`` PER FREE SCRIPT. Probe order — the FIRST
EXISTING ``<root>/skills/_shared/<name>`` wins:

1. ``toplevel`` — the git toplevel of ``cwd``, when it carries the sentinel.
   Dogfood wins: the live checkout is the CURRENT copy, never lost to a stale cache copy.
2. ``plugin-root`` — the ``CLAUDE_PLUGIN_ROOT`` override install.
3. ``skill-dir`` — ``<skill_dir>/../..``, an explicitly anchored install.
4. ``self`` — the framework root this resolver itself was installed into.
5. ``cache`` — the versioned/versionless plugin cache, descending INTO the
   version segment (PR #122 H2). Sentinel-qualified like every other probe.

Probe 2 is NOT subsumed by probe 4, though on a dogfood machine both collapse
onto probe 1: ``CLAUDE_PLUGIN_ROOT`` is set by the HOST, never by an in-repo
caller, so grepping cannot tell you whether it is in use. Probe 3 is
FORWARD-COVER PARITY with probe 2.

Divergence from resolve_root.sh
-------------------------------
That script probes ``plugin-root(1) > skill-dir(2) > cache(3) > toplevel(4)``
— toplevel LAST. Hoisting toplevel to FIRST here is deliberate and NOT portable
back, for two reasons:

1. Toplevel-first there would return the design **worktree** for ``/tp-merge``.
   ``base_sync_cert.oracle_independent`` refuses a worktree-derived root as
   provenance-indeterminate, turning a valid PASS into INDETERMINATE — a gate
   that stops answering is worse than one that answers slowly.
2. ``--skill-dir`` is an EXPLICIT override. An ambient cwd probe must not
   outrank a root the caller named on purpose.

One order cannot serve both questions: ``resolve_root.sh`` asks *"which install
is this anchored to"* (explicit wins), this module asks *"where is the CURRENT
copy of THIS FREE module"* (dogfood wins, because an anchored install can LAG —
PR #126). Both pinned in ``test_resolve_script_parity.py``.

Every probed root is RECORDED, hit or miss, and one physical root reached twice
is reported once. If ``<name>`` is in NO root, ``SharedScriptNotFound`` names
them all — never a wrong path.

Pure stdlib. Importable as ``resolve_shared_script(name)``, runnable as
``python3 resolve_script.py [--skill-dir <dir>] <name>`` — stdout/stderr and the
exit-code contract both mirror ``resolve_root.sh``.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

# The framework-root sentinel — the SAME file resolve_root.sh keys off (its
# SENTINEL_REL). One source of truth for "what is a framework checkout"; the
# design Constraint mandates it over the .claude-plugin/ marker (audit F2).
_SENTINEL_REL = Path("skills") / "_shared" / "first-run.md"
_SHARED_REL = Path("skills") / "_shared"
# The ONLY thing keeping an unrelated vendor's plugin out of the walk.
# ``Path.match``, not ``fnmatch``: no new import, no unguarded primitive.
_PLUGIN_GLOB = "three-pillars*"
# "Derive this root from the ambient MACHINE" (env, ``__file__``, process cwd).
# ``None`` is the OPPOSITE and load-bearing: "this root does not exist for this
# call" — the D3 opt-out. ONE meaning across all three, or a sweep reads a lie.
_UNSET = object()
# The probe tags, IN ORDER. Plain strings, no Enum — rendered into the
# diagnostic and parsed back out by the parity tests. This tuple DRIVES the
# probe loop, so a tag cannot drift from its position.
_SOURCES = ("toplevel", "plugin-root", "skill-dir", "self", "cache")


class SharedScriptNotFound(Exception):
    """A FREE ``_shared`` script was absent from every candidate root.

    Carries ``name`` and ``probed_roots`` so the diagnostic (and any catching caller)
    names exactly where it looked — the fail-loud contract that replaces silent
    path-not-found flailing. ``probe_report`` is the STRUCTURED form: ``(source, path,
    status)`` triples, status in ``{hit, miss, unreadable}``, strictly ADDITIVE
    (``probed_roots`` keeps its ``list[str]`` type AND its contents, so #129 callers
    are untouched). One rendered line per distinct path: ``  - <path>  [<source>:
    <status>]``.
    """

    def __init__(self, name: str, probed_roots, probe_report=None) -> None:
        self.name = name
        self.probed_roots = [str(r) for r in probed_roots]
        if probe_report is None:
            probe_report = [("probe", r, "miss") for r in self.probed_roots]
        self.probe_report = [(str(s), str(p), str(t)) for s, p, t in probe_report]
        lines = "\n".join(f"  - {p}  [{s}: {t}]" for s, p, t in self.probe_report)
        super().__init__(
            f"resolve_script: FREE _shared script {name!r} not found in any "
            f"candidate root. Probed roots:\n{lines or '  (none)'}"
        )


def _framework_probe(path):
    """``(carries_sentinel, wall)`` for ``path`` — never raises.

    One ``os.stat`` per step down ``path``/``skills``/``_shared``/sentinel, so ``wall``
    NAMES the dir to chmod — never ``path`` itself, up to two segments above it (R5) —
    and ``is_file()`` on the sentinel swallows the deepest wall outright (R6). Two
    things descent must not lose, pinned by name in ``test_resolve_script_walls.py``:
    the sentinel is a REGULAR FILE as ``resolve_root.sh``'s ``[ -f ]`` requires, in
    ``test_dir_sentinel_is_not_a_root``; and ONLY a permission error is a wall — ELOOP
    is absence, not a chmod-able dir — in ``test_looped_skills_is_a_miss_not_a_wall``.
    """
    cursor = Path(path)
    for part in (*_SHARED_REL.parts, _SENTINEL_REL.name):
        try:
            info = os.stat(cursor / part)
        except PermissionError:
            return False, cursor
        except OSError:  # ENOENT / ENOTDIR / ELOOP — absent is not walled
            return False, None
        cursor = cursor / part
    return stat.S_ISREG(info.st_mode), None


def _git_toplevel(cwd):
    """Return the git toplevel of ``cwd`` as a ``Path``, or ``None``.

    Resolves off ``git -C <cwd> rev-parse --show-toplevel`` (not raw cwd), the
    same discipline ``github_pr_author.py`` uses. ``None`` when ``cwd`` is
    outside any repo or git is missing — the caller falls to the cache.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
    except (OSError, ValueError):
        return None
    top = result.stdout.strip() if result.returncode == 0 else ""
    return Path(top) if top else None


def _resolved(path):
    """``Path.resolve()`` degraded to ``None`` — never raises.

    A symlink loop raises ``RuntimeError``, NOT ``OSError``, so an OSError-only
    guard lets a self-referential ``--skill-dir`` escape as a bare traceback and
    break the exit 0/1/2 contract. Both ``.resolve()`` sites go through here.
    """
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError):
        return None


def _named_root(value):
    """A caller-named root as an ABSOLUTE ``Path``, or ``None`` if it names none.

    ONE normalizer for EVERY root-valued input — ``plugin_root``, ``skill_dir``,
    ``self_root``, ``cache_root``, the ``CLAUDE_PLUGIN_ROOT`` env derivation
    (``cwd`` is not one: it is a dir to probe FROM, and git answers with an
    absolute toplevel). SHARED, not per-parameter, because per-parameter is how
    the bug survived — written for ``skill_dir``, its identically-shaped SIBLING
    ``plugin_root`` kept it. THREE properties, all pinned in
    ``test_resolve_script_roots.py`` and ``test_resolve_script_root_inputs.py``:

    * ``""`` / ``"."`` / ``Path("")`` / ``Path(".")`` name NO directory, yet
      make ``Path(root)/_SHARED_REL`` relative to the PROCESS CWD — an unnamed
      cwd anchored as an EXPLICIT root, outranking the cache. Truthiness cannot
      see it (``Path("")`` IS ``PosixPath('.')``, TRUTHY), nor can ``str`` (it
      is "."); ``.parts`` is empty for every such spelling, of either type.
    * a RELATIVE root DOES name a directory — one anchored on the process cwd
      at stat time, so the resolver returned a RELATIVE path against its
      documented ``:returns: an absolute Path``. Anchored explicitly here, never
      ``normpath``-ed: collapsing ``..`` lexically walks past a symlink.
    * whitespace-ONLY joins bullet 1; otherwise the value is NOT stripped —
      stripping made ``"<b>/ws "`` return ``<b>/ws``, a DIFFERENT existing root.
    """
    path = Path(os.fspath(value)) if value is not None else Path()
    if not path.parts or not os.fspath(path).strip():  # names no directory
        return None
    if path.is_absolute():
        return path
    try:
        return Path(os.getcwd()) / path
    except OSError:  # no cwd to anchor on: the value names no reachable dir
        return None


def _self_root():
    """The framework root THIS RESOLVER was installed into, or ``None``.

    Walks up from ``__file__`` to the nearest ancestor carrying the sentinel.
    On a dogfood checkout that is the repo root — which is why every test here
    opts out with ``self_root=None``, or a cache case would pass wrongly.

    An ancestor that WALLED the search off is returned too, and for the same
    reason the probes thread their wall: it did not MISS, it could not be read.
    ``_probe`` re-stats it and tags it, so there is one wall-reporting path (F5).
    """
    here = _resolved(__file__)
    for parent in here.parents if here else ():
        qualified, wall = _framework_probe(parent)
        if qualified or wall is not None:
            return parent
    return None


def _cache_roots(cache_root):
    """``(roots, unreadable)`` — every plugin root under the versioned cache.

    Mirrors ``resolve_root.sh``'s ``_check_cache_tree``: for each
    ``<cache_root>/<marketplace>/three-pillars*/`` plugin dir, BOTH the plugin
    dir itself (versionless / local) and each immediate ``<plugin>/<version>/``
    (PR #122 H2) is a candidate root.

    QUALIFYING them is deliberately NOT done here: the one ``_probe`` in
    ``resolve_shared_script`` judges these roots too, so the cache cannot drift
    onto a weaker predicate than probes 1-4 (it once did, on nothing but the
    file existing), a FREE-only module still skips a PRO cache lacking it, and
    every scanned root is RECORDED by the same path as every other probe (A3,
    D5). ``unreadable`` names every dir that could not be walked, at EVERY
    level; one never aborts the rest.
    """
    roots: list[Path] = []
    unreadable: list[Path] = []
    if cache_root is None:  # names no directory — see _named_root
        return roots, unreadable
    root = Path(cache_root)
    try:
        if not root.is_dir():
            return roots, unreadable
    except OSError:
        unreadable.append(root)
        return roots, unreadable

    def _subdirs(parent):
        """``parent``'s child DIRECTORIES; tag ``parent`` if it walls off either step.

        The listing and each child's ``is_dir()`` stat fail on DIFFERENT
        permission shapes, so guarding only the listing leaves the filter bare:
        ``0o444`` lists fine, then raises ``PermissionError`` out of the next
        child stat. Either way the dir missing ``+x`` is ``parent``: what an
        operator fixes. No ``os.access`` pre-check — racy, and it lies under
        ACLs; read and believe the OSError, because ``[]`` from a ``0o000`` dir
        is otherwise indistinguishable from ``[]`` from an empty one.
        """
        try:
            children = sorted(Path(parent).iterdir())
        except OSError:
            unreadable.append(parent)
            return []
        kids = []
        for child in children:
            try:
                if child.is_dir():
                    kids.append(child)
            except OSError:
                unreadable.append(parent)
        return kids

    for marketplace in _subdirs(root):
        for plugin in _subdirs(marketplace):
            if not plugin.match(_PLUGIN_GLOB):
                continue
            # Readability is established BEFORE descending, so the dir NAMED
            # unreadable is the one to chmod, not a deeper child.
            roots.extend([plugin, *_subdirs(plugin)])  # versionless, then versioned
    return roots, unreadable


def _probe_records(probes, unreadable):
    """Fold ordered ``(source, path)`` probes + unreadable dirs into report triples.

    One record per DISTINCT path: a dir that was both a probed root and
    unreadable is reported ONCE, as ``unreadable``. Deeper unreadable dirs are
    appended so the operator sees which directory to fix — each carrying the
    SOURCE that walled off, since probes 1-4 report walls too now (F5).
    """
    blind = {str(p) for _source, p in unreadable}
    first: dict[str, str] = {}  # path -> the FIRST source that reached it
    for source, path in [*probes, *unreadable]:
        first.setdefault(str(path), source)
    return [
        (source, path, "unreadable" if path in blind else "miss")
        for path, source in first.items()
    ]


def resolve_shared_script(
    name: str,
    *,
    cwd=_UNSET,
    cache_root=None,
    plugin_root=_UNSET,
    skill_dir=None,
    self_root=_UNSET,
) -> Path:
    """Resolve FREE ``skills/_shared/<name>`` to its authoritative path.

    Probes the five roots in the module docstring's order; the first EXISTING
    ``<root>/skills/_shared/<name>`` wins.

    :param name: BARE BASENAME of the FREE ``_shared`` script (e.g.
        ``github_pr_author.py``) — see the ValueError below.
    :param cwd: dir the git toplevel is probed from. AMBIENT — see below.
    :param cache_root: plugin cache, default ``~/.claude/plugins/cache``.
    :param plugin_root: the ``CLAUDE_PLUGIN_ROOT`` override install.
    :param skill_dir: a skill directory; its grandparent is the framework root.
    :param self_root: the framework root this resolver lives in.
    :returns: an absolute ``Path`` that EXISTS on disk.
    :raises ValueError: if ``name`` is not a bare basename.
    :raises SharedScriptNotFound: if ``<name>`` exists in no candidate root.

    ``cwd``/``plugin_root``/``self_root`` are AMBIENT: ``_UNSET`` derives each
    from the machine — the process cwd (``None`` if UNLINKED, A2), the env,
    ``__file__`` — and ``None`` WITHHOLDS it (D3, see ``_UNSET``).
    """
    # `shared / name` DISCARDS its left operand for an absolute `name` and
    # escapes _shared for a traversing one, so resolve("/etc/hostname") used to
    # return /etc/hostname — off an unvalidated CLI positional every call site
    # pipes into python3. The accepted set is spelled out rather than left to
    # `Path.name`'s quirks: `Path("..").name` is "..", so `..` was ACCEPTED by a
    # check whose contract says BARE BASENAME (not exploitable — `(shared /
    # "..").is_file()` is always False — but predicate and docstring must
    # agree). `"."`/`"foo/"` are rejected on purpose too.
    if name in ("", ".", "..") or Path(name).name != name:
        raise ValueError(f"resolve_script: name must be a bare basename, got {name!r}")
    if cwd is _UNSET:
        cwd = _resolved(".")  # unlinked cwd -> None (A2): probes 2-5 still run
    if plugin_root is _UNSET:
        plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if self_root is _UNSET:
        self_root = _self_root()
    # EVERY root-valued input goes through the ONE normalizer — see _named_root
    # for the two properties it enforces, and for why per-parameter guards left
    # `plugin_root` open after `skill_dir` was closed.
    plugin_root = _named_root(plugin_root)
    self_root = _named_root(self_root)

    # Ordered (source, path) pairs — `probed_roots` derives from this list, so
    # it stays byte-compatible with #129 while the tag feeds the report.
    probes: list[tuple[str, str]] = []
    unreadable: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def _probe(source, root):
        """Probe one candidate root; return the hit ``Path`` or ``None``.

        Records the visit BEFORE qualifying (D5), so a root that exists but
        fails the sentinel lands in the diagnostic as ``[<tag>: miss]``, never
        vanishing. Dedupes on the ``_shared`` realpath. The WALL is threaded
        here too: "miss" on an UNREADABLE named override root is the R5 lie.
        """
        if root is None:
            return None
        shared = Path(root) / _SHARED_REL
        try:
            key = os.path.realpath(shared)
        except OSError:
            key = str(shared)
        if key in seen:
            return None
        probes.append((source, str(shared)))
        if source == "skill-dir" and unresolved:
            return None  # recorded in probe order, never qualified (R4/F6)
        # `seen` is claimed only by a probe that got to QUALIFY. A fail-closed
        # override that claimed it EVICTED the same physical root from probe 4,
        # and a decoy PRO cache copy won at exit 0 (round-4 A1, PR #126 class).
        seen.add(key)
        qualified, wall = _framework_probe(root)
        if wall is not None:
            # Tag the probe line AND name the dir to chmod: `<shared>` is what
            # the reader looked for, `wall` what they must fix (never qualified).
            unreadable.extend([(source, shared), (source, wall)])
        if not qualified:
            return None
        candidate = shared / name
        # `os.path.isfile`, not `Path.is_file`, which RAISES ENAMETOOLONG (R7 S1).
        return candidate if os.path.isfile(candidate) else None

    top = _git_toplevel(cwd) if cwd is not None else None
    if top is None and cwd is not None:
        # No git toplevel. Record what was probed FROM so probe 1 stays visible
        # (D5); no cwd names no dir, so probe 1 drops out, never a fabricated
        # "None": test_unlinked_cwd_records_no_fabricated_toplevel_path (parity).
        probes.append(("toplevel", str(cwd)))
    # Resolve the SKILL DIR ITSELF, then take its grandparent — NEVER `.resolve()`
    # on `<dir>/../..`, which on 3.12 collapses the `..` LEXICALLY PAST a symlink
    # loop instead of raising, anchoring an override on a dir nobody named.
    # `_resolved` is None for the loop, so `unresolved` fails the probe closed
    # (as `cd "$SKILL_DIR/../.." && pwd -P` goes empty) while still RECORDING it
    # in PROBE ORDER off the lexical grandparent (D5) — see `_probe`.
    skill_root = _named_root(skill_dir)
    anchor = _resolved(skill_root) if skill_root is not None else None
    unresolved = skill_root is not None and anchor is None
    roots = {
        "toplevel": top,
        "plugin-root": plugin_root,
        "skill-dir": (anchor or skill_root).parent.parent if skill_root else None,
        "self": self_root,
    }
    for source in _SOURCES[:-1]:  # every root except "cache"
        found = _probe(source, roots[source])
        if found is not None:
            return found

    # Root 5 — the cache fallback. The home lookup is DEFERRED to here and uses
    # `os.path.expanduser`, never `Path.home()`, which RAISES RuntimeError (not
    # OSError — the degrade class `_resolved` exists for) when $HOME is unset
    # with no passwd entry: uncaught, and EAGER, so it killed even a call probe 1
    # had answered. `expanduser` cannot raise; with no home it leaves the path
    # unexpanded, so the root is NAMED either way and the exit contract holds.
    if cache_root is None:
        cache_root = os.path.expanduser("~/.claude/plugins/cache")
    cache_root = _named_root(cache_root)
    if cache_root is not None:  # `cache_root=""` names none: nothing was probed
        probes.append(("cache", str(cache_root)))
    cached, blind = _cache_roots(cache_root)
    unreadable.extend(("cache", entry) for entry in blind)
    # Judged by the SAME `_probe` as roots 1-4 — same sentinel, same records, so a
    # populated-but-non-matching cache names every dir it looked in (audit A3), not a
    # vacuous "empty" message. EVERY hit is collected, not the first: the winner is
    # `sort | head -n 1` over the ROOTS (resolve_root.sh:135) — never mtime (#129 B5),
    # never the script PATH, whose `/skills/_shared/<name>` suffix reorders a prefix
    # pair (`-` 0x2D < `/` 0x2F): FREE->PRO (R8 S2). Then fail loud: never a bad path.
    candidates = [hit for hit in (_probe("cache", r) for r in cached) if hit]
    if candidates:  # the .parent chain climbs back out of `skills/_shared/<name>`
        return min(candidates, key=lambda hit: str(hit.parent.parent.parent))

    records = _probe_records(probes, unreadable)
    raise SharedScriptNotFound(name, [path for _s, path in probes], records)


_USAGE = (
    "usage: resolve_script.py [--skill-dir <dir>] <name>\n"
    "  <name> = basename of a FREE skills/_shared script (e.g. github_pr_author.py)\n"
)


def _parse_argv(argv):
    """Split ``argv`` into ``(positionals, skill_dir, error)``.

    Mirrors ``resolve_root.sh``'s own parse loop: ``--skill-dir`` consumes the
    NEXT argv entry, a missing value and an unrecognized flag are both exit-2
    conditions, and each names itself on stderr. Naming matters — ``--bogus
    <name>`` is two argv entries, so a purely positional arity check would exit 2
    for the wrong reason AND accept ``--bogus`` as a script name. ``error`` is
    ``None`` on success; the caller owns the arity check, AFTER the flag pair.
    """
    positionals: list[str] = []
    skill_dir = None
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--skill-dir":
            # A following `--flag` is not a value: `--skill-dir --bogus x.py`
            # used to SWALLOW the flag as the anchor — a typo became a root.
            if not rest or rest[0].startswith("--"):
                return None, None, "resolve_script.py: --skill-dir requires a value"
            skill_dir = rest.pop(0)
        elif arg.startswith("--"):
            return None, None, f"resolve_script.py: unknown argument: {arg}"
        else:
            positionals.append(arg)
    return positionals, skill_dir, None


def _main(argv) -> int:
    """CLI entry point — path on stdout / diagnostic on stderr / exit codes.

    Mirrors ``resolve_root.sh``'s contract: exit 0 (path), exit 1 (fail-loud
    diagnostic), exit 2 (usage / wrong arity / bad flag). Reads ``$HOME`` for
    the cache root (degraded, never raising) and ``os.getcwd()`` for cwd.
    """
    positionals, skill_dir, error = _parse_argv(argv)
    if error is not None:
        sys.stderr.write(error + "\n")
        return 2
    if len(positionals) != 1:
        sys.stderr.write(_USAGE)
        return 2
    name = positionals[0]
    try:
        path = resolve_shared_script(name, skill_dir=skill_dir)
    except ValueError as exc:  # a name that is not a bare basename — usage error
        sys.stderr.write(f"{exc}\n{_USAGE}")
        return 2
    except SharedScriptNotFound as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    sys.stdout.write(str(path) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
