"""run_scratch.py — the run's in-tree scratch dir and its env (design: run-scratch-in-fence 1.1).

The run dir is ``<realpath worktree>/.tp-scratch/run``. ``env_pairs`` names the
temp/cache variables that point at it; ``run_dir_from_env`` recognizes it from
a TMPDIR value. Stdlib only, fail-open: OSError gives None, never a raise.
"""
import hashlib
import os
import sys

import scratch_root

RUN_SUBPATH = (".tp-scratch", "run")
CACHE_VARS = ("XDG_CACHE_HOME", "PIP_CACHE_DIR", "npm_config_cache", "UV_CACHE_DIR")
_CACHE_SUBDIRS = ("cache", "pip", "npm", "uv")
_TMP_VARS = ("TMPDIR", "TMP", "TEMP")
_SYSTEM_TMP = "/tmp"  # nosec B108  # scratch-checkout parent when TMPDIR is the in-tree run dir


def run_dir(worktree):
    return os.path.join(os.path.realpath(str(worktree)), *RUN_SUBPATH)


def env_pairs(worktree, env=None):
    """Fixed-order (name, value) pairs; reads nothing from os.environ."""
    d = run_dir(worktree)
    pairs = [(k, d) for k in _TMP_VARS]
    pairs += [(k, d + "/" + sub) for k, sub in zip(CACHE_VARS, _CACHE_SUBDIRS)]
    return pairs


def ensure_run_dir(worktree):
    """Create the run dir (0700), keep it out of git status; path or None."""
    try:
        d = run_dir(worktree)
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
        scratch_root.ensure_excluded(worktree)
        return d
    except (OSError, ValueError):
        return None


def run_dir_from_env(env):
    """Realpath of env TMPDIR iff it is a real <repo>/.tp-scratch/run, else None."""
    try:
        raw = (env or {}).get("TMPDIR") or ""
        norm = os.path.normpath(raw)
        if not os.path.isabs(norm) or not norm.endswith("/" + "/".join(RUN_SUBPATH)):
            return None
        scratch = os.path.dirname(norm)
        top = os.path.dirname(scratch)
        if os.path.islink(scratch) or os.path.islink(norm):
            return None
        if not os.path.exists(os.path.join(top, ".git")):
            return None
        real = os.path.realpath(norm)
        if real != os.path.join(os.path.realpath(top), *RUN_SUBPATH):
            return None
        return real if os.path.isdir(real) else None
    except (OSError, ValueError):
        return None


def outside_tmpdir(env=None):
    """A temp parent outside the checkout, for a dir an agent runs git in: the system temp when
    TMPDIR is run-dir-shaped (the run's in-tree dir), else None (tempfile's default). Never raises."""
    try:
        raw = os.path.normpath((os.environ if env is None else env).get("TMPDIR") or ".")
        if raw.endswith("/" + "/".join(RUN_SUBPATH)) and os.path.isdir(_SYSTEM_TMP):
            return _SYSTEM_TMP
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def tag(worktree):
    h = hashlib.sha1(os.path.realpath(str(worktree)).encode(), usedforsecurity=False)  # noqa: S324
    return h.hexdigest()[:6]


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    wt = args[0] if args else os.getcwd()
    d = ensure_run_dir(wt)
    if d is None:
        return 1
    print(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
