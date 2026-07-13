#!/usr/bin/env python3
"""resolve_script.py — resolve a FREE ``skills/_shared`` helper to its path.

The framework ships as TWO plugins installed at DIFFERENT roots (a FREE core
plugin and a PRO plugin). ``resolve_root.sh`` answers "where is *a* framework
root" but qualifies a candidate solely by the ``skills/_shared/first-run.md``
sentinel — which the PRO cache also carries. So ``$TP_ROOT`` can legitimately
land on the PRO cache, which does NOT carry FREE-only ``_shared`` modules
(``github_pr_author.py`` is verifiably absent from ``three-pillars-pro/1.2.0``).
Invoking ``python3 "$TP_ROOT"/skills/_shared/<name>`` then dies with
``No such file or directory`` (this failed live in PR #126, 2026-07-07).

This module refines ``$TP_ROOT`` PER FREE SCRIPT:

* **Dogfood / self-host wins.** When the current git toplevel is itself a
  framework checkout (carries ``resolve_root.sh``'s ``first-run.md`` sentinel)
  and holds ``skills/_shared/<name>``, that repo copy is returned. It is the
  authoritative, current copy — never lost to a stale/absent cache copy.
* **Consumer cache fallback.** Otherwise the versioned plugin cache is globbed
  (``cache/<marketplace>/three-pillars*/<version>/skills/_shared/<name>``,
  descending INTO the version segment per PR #122 H2). Only EXISTING paths are
  candidates, so a FREE-only module naturally skips a PRO cache lacking it.
* **Fail loud.** If ``<name>`` exists in NO candidate root, raise
  ``SharedScriptNotFound`` naming every probed root — never a silent wrong path.

Pure stdlib + ``subprocess`` git; no third-party deps. Importable as
``resolve_shared_script(name)`` and runnable as ``python3 resolve_script.py
<name>`` (path on stdout / diagnostic on stderr / exit-code contract mirrors
``resolve_root.sh``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# The framework-root sentinel — the SAME file resolve_root.sh keys off (see its
# SENTINEL_REL). One source of truth for "what is a framework checkout"; the
# design Constraint mandates reuse of this sentinel rather than the corroborating
# .claude-plugin/ marker (audit F2).
_SENTINEL_REL = Path("skills") / "_shared" / "first-run.md"
_SHARED_REL = Path("skills") / "_shared"


class SharedScriptNotFound(Exception):
    """A FREE ``_shared`` script was absent from every candidate root.

    Carries the ``name`` probed and the list of ``probed_roots`` so the
    diagnostic (and any catching caller) can name exactly where it looked —
    the fail-loud contract that replaces the silent path-not-found flailing.
    """

    def __init__(self, name: str, probed_roots) -> None:
        self.name = name
        self.probed_roots = [str(r) for r in probed_roots]
        listing = "\n".join(f"  - {r}" for r in self.probed_roots) or "  (none)"
        super().__init__(
            f"resolve_script: FREE _shared script {name!r} not found in any "
            f"candidate root. Probed roots:\n{listing}"
        )


def _is_framework_root(path) -> bool:
    """True iff ``path`` is a framework checkout (carries the sentinel).

    Keyed off resolve_root.sh's ``skills/_shared/first-run.md`` sentinel — the
    single source of truth for framework-root identity.
    """
    try:
        return (Path(path) / _SENTINEL_REL).is_file()
    except OSError:
        return False


def _git_toplevel(cwd):
    """Return the git toplevel of ``cwd`` as a ``Path``, or ``None``.

    Resolves off ``git -C <cwd> rev-parse --show-toplevel`` (not raw cwd), the
    same discipline ``github_pr_author.py`` uses. Returns ``None`` when ``cwd``
    is outside any git repo or git is unavailable — the caller then falls to the
    consumer cache.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    top = result.stdout.strip()
    return Path(top) if top else None


def _cache_candidates(cache_root, name):
    """Return EXISTING cache paths for ``<name>`` under the plugin cache.

    Mirrors ``resolve_root.sh``'s ``_check_cache_tree``: for each
    ``<cache_root>/<marketplace>/three-pillars*/`` plugin dir, probe BOTH

    * the plugin dir itself — ``<plugin>/skills/_shared/<name>`` (versionless /
      local installs), and
    * each immediate ``<plugin>/<version>/skills/_shared/<name>`` — descending
      INTO the version segment (the real marketplace layout, PR #122 H2), never
      stopping at the parent ``<plugin>/`` dir which has no ``skills/``.

    Only paths that EXIST on disk are collected, so a FREE-only module naturally
    skips a PRO cache that lacks it (FREE-in-PRO-cache miss avoided, not merely
    reported). The caller sorts for a deterministic winner.

    Returns ``(found, scanned)`` where ``scanned`` is every EXISTING
    ``<plugin>[/<version>]/skills/_shared`` dir that was probed — so a fail-loud
    diagnostic can ENUMERATE the discovered-but-non-matching plugin roots (a
    populated cache that simply lacks the module is named, not reported as a
    vacuous "empty cache", audit A3).

    NOTE (scope, audit A6): this globs only the STANDARD
    ``~/.claude/plugins/cache/<mkt>/three-pillars*`` layout. Non-standard
    installs via ``CLAUDE_PLUGIN_ROOT`` / ``--skill-dir`` overrides are out of
    scope for this light change and are a tracked follow-up.
    """
    root = Path(cache_root)
    found: list[Path] = []
    scanned: list[Path] = []
    if not root.is_dir():
        return found, scanned
    for marketplace in sorted(root.iterdir()):
        if not marketplace.is_dir():
            continue
        for plugin in sorted(marketplace.glob("three-pillars*")):
            if not plugin.is_dir():
                continue
            # versionless / local layout: <plugin>/skills/_shared/<name>
            direct_shared = plugin / _SHARED_REL
            if direct_shared.is_dir():
                scanned.append(direct_shared)
            direct = direct_shared / name
            if direct.is_file():
                found.append(direct)
            # versioned marketplace layout: <plugin>/<version>/skills/_shared/<name>
            for version in sorted(plugin.iterdir()):
                if not version.is_dir():
                    continue
                nested_shared = version / _SHARED_REL
                if nested_shared.is_dir():
                    scanned.append(nested_shared)
                nested = nested_shared / name
                if nested.is_file():
                    found.append(nested)
    return found, scanned


def resolve_shared_script(name: str, *, cwd=None, cache_root=None) -> Path:
    """Resolve FREE ``skills/_shared/<name>`` to its authoritative path.

    :param name: basename of the FREE ``_shared`` script (e.g.
        ``github_pr_author.py``).
    :param cwd: working directory used to probe the git toplevel; defaults to
        ``os.getcwd()``. Injectable so tests use a fixture, never the real cwd.
    :param cache_root: plugin-cache root; defaults to
        ``~/.claude/plugins/cache``. Injectable so tests use a fixture, never
        the real machine cache.
    :returns: an absolute ``Path`` that EXISTS on disk.
    :raises SharedScriptNotFound: if ``<name>`` exists in no candidate root.
    """
    if cwd is None:
        cwd = os.getcwd()
    if cache_root is None:
        cache_root = Path.home() / ".claude" / "plugins" / "cache"

    probed: list[str] = []

    # 1. Dogfood / self-host — the repo's own copy is authoritative and current.
    top = _git_toplevel(cwd)
    if top is not None and _is_framework_root(top):
        shared = top / _SHARED_REL
        probed.append(str(shared))
        candidate = shared / name
        if candidate.is_file():
            return candidate

    # 2. Consumer versioned plugin-cache fallback (Task 1.2).
    probed.append(str(cache_root))
    candidates, scanned = _cache_candidates(cache_root, name)
    if candidates:
        # Deterministic, string-lexicographic — mirrors resolve_root.sh's
        # `sort | head -n 1`, never mtime (Behavior 5).
        return sorted(candidates, key=str)[0]

    # 3. Fail loud — never return a nonexistent path. Enumerate the discovered
    #    plugin _shared roots so a populated-but-non-matching cache names the
    #    dirs it actually looked in, not a vacuous "empty" message (audit A3).
    probed.extend(str(s) for s in scanned)
    raise SharedScriptNotFound(name, probed)


_USAGE = (
    "usage: resolve_script.py <name>\n"
    "  <name> = basename of a FREE skills/_shared script "
    "(e.g. github_pr_author.py)\n"
)


def _main(argv) -> int:
    """CLI entry point — path on stdout / diagnostic on stderr / exit codes.

    Mirrors ``resolve_root.sh``'s contract: exit 0 (path), exit 1 (fail-loud
    diagnostic), exit 2 (usage / wrong arity). Reads ``$HOME`` (via
    ``Path.home()``) for the cache root and ``os.getcwd()`` for cwd.
    """
    if len(argv) != 1:
        sys.stderr.write(_USAGE)
        return 2
    name = argv[0]
    try:
        path = resolve_shared_script(name)
    except SharedScriptNotFound as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    sys.stdout.write(str(path) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
