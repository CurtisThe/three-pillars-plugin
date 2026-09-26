"""Parity pin between resolve_root.sh and resolve_script.py — plan Phase 4 (D1).

The two resolvers answer DIFFERENT questions and therefore probe in different
orders. That divergence is deliberate (design D1), so it has to be pinned from
BOTH sides: where they must agree (same sentinel; same answer whenever there is
no contention) and where they must disagree (the three order inversions that
moving ``toplevel`` from last to first creates).

``resolve_root.sh`` is **not** edited by this design. Every assertion here reads
the SHIPPED files — the real script, the real module — never a transcribed copy,
so either side silently reordering its probes fails here rather than in
production.

Run with: python -m pytest skills/_shared/test_resolve_script_parity.py -q
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import resolve_script  # noqa: E402
from resolve_script import resolve_shared_script  # noqa: E402

RESOLVE_ROOT_SH = HERE / "resolve_root.sh"
RESOLVE_SCRIPT_PY = HERE / "resolve_script.py"

NAME = "github_pr_author.py"


# --------------------------------------------------------------------------- #
# Fixture builders
# --------------------------------------------------------------------------- #
def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(path)], check=True, capture_output=True
    )


def _framework_root(root: Path, *, git: bool = False) -> Path:
    """A qualifying framework root: sentinel + the FREE module under test.

    Both resolvers need the sentinel to qualify a candidate; resolve_script.py
    additionally needs ``<name>`` to exist. Carrying both is what makes a root
    a legitimate answer for EITHER resolver, which is the precondition for
    comparing them at all.
    """
    root.mkdir(parents=True, exist_ok=True)
    if git:
        _git_init(root)
    _write(root / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    _write(root / "skills" / "_shared" / NAME, "# module\n")
    return root


def _plain_repo(root: Path) -> Path:
    """A git repo that is NOT a framework checkout — the toplevel probe misses."""
    root.mkdir(parents=True, exist_ok=True)
    _git_init(root)
    return root


def _cache_root(home: Path) -> Path:
    return home / ".claude" / "plugins" / "cache"


def _cached_framework(home: Path, *, version: str = "1.2.0") -> Path:
    """A framework root at the real marketplace cache depth under ``home``."""
    return _framework_root(
        _cache_root(home) / "marketplace" / "three-pillars" / version
    )


def _resolve_root_sh(*, cwd: Path, home: Path, plugin_root=None, skill_dir=None):
    """Run the SHIPPED resolve_root.sh as a real subprocess."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    # Probe 1 reads this ambiently; a developer with it set would otherwise
    # have it outrank every root the case constructs.
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    if plugin_root is not None:
        env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    args = ["bash", str(RESOLVE_ROOT_SH)]
    if skill_dir is not None:
        args += ["--skill-dir", str(skill_dir)]
    return subprocess.run(
        args, cwd=str(cwd), env=env, capture_output=True, text=True
    )


def _real(path) -> str:
    return os.path.realpath(str(path))


def _root_of(script_path) -> str:
    """The framework root of a ``<root>/skills/_shared/<name>`` hit, realpathed.

    resolve_root.sh answers with a ROOT and resolve_script.py answers with a
    PATH TO A FILE; comparing them means climbing back out of skills/_shared.
    """
    return _real(Path(script_path).parents[2])


# --------------------------------------------------------------------------- #
# Task 4.1 — the shared sentinel
# --------------------------------------------------------------------------- #
def test_both_resolvers_key_off_the_same_sentinel():
    """Both resolvers qualify a candidate root with the SAME sentinel file.

    Read out of the shipped sources rather than transcribed, so a change to
    either side's sentinel breaks parity here instead of silently splitting
    the two definitions of "what is a framework checkout".
    """
    sh_text = RESOLVE_ROOT_SH.read_text(encoding="utf-8")
    py_text = RESOLVE_SCRIPT_PY.read_text(encoding="utf-8")

    sh_match = re.search(r'SENTINEL_REL="([^"]+)"', sh_text)
    assert sh_match, "resolve_root.sh no longer declares SENTINEL_REL"
    sh_sentinel = sh_match.group(1)

    py_match = re.search(
        r'_SENTINEL_REL\s*=\s*Path\("([^"]+)"\)((?:\s*/\s*"[^"]+")+)', py_text
    )
    assert py_match, "resolve_script.py no longer declares _SENTINEL_REL"
    py_sentinel = "/".join(
        [py_match.group(1), *re.findall(r'"([^"]+)"', py_match.group(2))]
    )

    assert sh_sentinel == py_sentinel == "skills/_shared/first-run.md"


# --------------------------------------------------------------------------- #
# Task 4.1 — no contention: exactly one root exists, both must agree
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("root_kind", ["plugin-root", "skill-dir", "cache", "toplevel"])
def test_no_contention_parity(tmp_path, root_kind):
    """With exactly ONE qualifying root, both resolvers land on the same path.

    No contention means probe ORDER cannot matter — so any disagreement here is
    a real defect in one of the two resolvers, not the deliberate D1 ordering
    divergence (which Task 4.2 pins separately).
    """
    home = tmp_path / "home"
    _cache_root(home).mkdir(parents=True)  # exists but empty, unless this case fills it
    cwd = _plain_repo(tmp_path / "cwd")
    plugin_root = skill_dir = None
    py_kwargs = {}

    if root_kind == "plugin-root":
        plugin_root = _framework_root(tmp_path / "plugin-install")
        expected = plugin_root
        py_kwargs["plugin_root"] = plugin_root
    elif root_kind == "skill-dir":
        expected = _framework_root(tmp_path / "anchored")
        skill_dir = expected / "skills" / "tp-foo"
        skill_dir.mkdir(parents=True)
        py_kwargs["skill_dir"] = skill_dir
    elif root_kind == "cache":
        expected = _cached_framework(home)
    else:  # toplevel
        expected = _framework_root(tmp_path / "checkout", git=True)
        cwd = expected

    sh = _resolve_root_sh(
        cwd=cwd, home=home, plugin_root=plugin_root, skill_dir=skill_dir
    )
    assert sh.returncode == 0, sh.stderr
    assert _real(sh.stdout.strip()) == _real(expected)

    hit = resolve_shared_script(
        NAME,
        cwd=cwd,
        cache_root=_cache_root(home),
        plugin_root=py_kwargs.get("plugin_root"),
        skill_dir=py_kwargs.get("skill_dir"),
        self_root=None,
    )
    assert _root_of(hit) == _real(expected)
    assert _root_of(hit) == _real(sh.stdout.strip())


# --------------------------------------------------------------------------- #
# Task 4.3 — the DECLARED orders match the code, and the divergence is written
#            down where a reader of either resolver will find it
# --------------------------------------------------------------------------- #
# Each resolver documents its probe order in its own header. Documentation that
# can drift from the code is worse than none — an operator debugging a wrong
# root trusts it. Both lists are therefore parsed out of the shipped files and
# checked against the real sequence.
_SH_PROBE_TAGS = {
    "CLAUDE_PLUGIN_ROOT": "plugin-root",
    "--skill-dir": "skill-dir",
    "Plugin-cache": "cache",
    "Dev-checkout": "toplevel",
}


def _sh_declared_order():
    """Parse resolve_root.sh's numbered header probe list into ordered tags."""
    header = RESOLVE_ROOT_SH.read_text(encoding="utf-8").split("set -eu")[0]
    entries = re.findall(r"^#\s+(\d+)\.\s+(.+)$", header, re.M)
    assert entries, "resolve_root.sh no longer declares a numbered probe list"
    assert [int(n) for n, _ in entries] == list(range(1, len(entries) + 1)), (
        "resolve_root.sh's declared probe list is not contiguously numbered"
    )
    order = []
    for _number, body in entries:
        matched = [tag for key, tag in _SH_PROBE_TAGS.items() if key in body]
        assert len(matched) == 1, f"cannot classify resolve_root.sh probe: {body!r}"
        order.append(matched[0])
    return order


def _py_declared_order():
    """Parse resolve_script.py's docstring probe list into ordered tags.

    Scoped to the text BEFORE the divergence block: that block carries its own
    numbered list whose item 2 opens with ``--skill-dir``, which the probe-list
    pattern would otherwise sweep up as a sixth probe. The probe list is the
    only numbered list this parse may see.
    """
    head = resolve_script.__doc__.split("Divergence from resolve_root.sh", 1)[0]
    entries = re.findall(r"^(\d+)\. ``([a-z-]+)``", head, re.M)
    assert entries, "resolve_script.py no longer declares a numbered probe list"
    assert [int(n) for n, _ in entries] == list(range(1, len(entries) + 1)), (
        "resolve_script.py's declared probe list is not contiguously numbered"
    )
    return [tag for _number, tag in entries]


def test_declared_probe_orders_match():
    """Each resolver's documented order IS its real order — and they differ.

    The python side is checked against ``_SOURCES``, the tuple that literally
    drives the probe loop, so the docstring cannot drift from behaviour. The
    shell side has no such tuple, so its header is checked against the sequence
    the divergence tests above depend on.
    """
    assert _sh_declared_order() == ["plugin-root", "skill-dir", "cache", "toplevel"]
    assert _py_declared_order() == list(resolve_script._SOURCES)
    assert _py_declared_order() == [
        "toplevel", "plugin-root", "skill-dir", "self", "cache"
    ]
    # The divergence this design introduces, restated as a predicate: toplevel
    # is LAST for resolve_root.sh and FIRST for resolve_script.py.
    assert _sh_declared_order()[-1] == "toplevel"
    assert _py_declared_order()[0] == "toplevel"


def test_module_docstring_has_divergence_block():
    """resolve_script.py explains WHY it does not share resolve_root.sh's order.

    Both of D1's reasons must be on the page, not just the fact of the split:
    (1) toplevel-first in resolve_root.sh would hand /tp-merge the design
    WORKTREE, which base_sync_cert refuses as provenance-indeterminate;
    (2) --skill-dir is an explicit override an ambient cwd probe must not
    outrank. Plus the framing that makes the asymmetry make sense.
    """
    doc = resolve_script.__doc__
    assert "Divergence from resolve_root.sh" in doc, (
        "the deliberate D1 order split is undocumented in the module that owns it"
    )
    block = doc.split("Divergence from resolve_root.sh", 1)[1]
    # Reason 1 — the merge-gate consequence, named concretely enough to verify.
    assert "base_sync_cert" in block and "INDETERMINATE" in block
    assert "worktree" in block
    # Reason 2 — an explicit override outranks an ambient probe.
    assert "--skill-dir" in block and "override" in block
    # The framing, and the lag that motivates dogfood-first (PR #126).
    assert "#126" in block


def test_first_run_md_cross_references_probe_chain():
    """first-run.md §Probe chain points at the FREE-script resolver's own order.

    §Probe chain documents resolve_root.sh's four probes. A reader who stops
    there will assume the same order governs FREE _shared scripts — it does
    not. The cross-reference is what stops that wrong assumption.
    """
    text = (HERE / "first-run.md").read_text(encoding="utf-8")
    start = text.index("### Probe chain")
    section = text[start:text.index("###", start + 3)]
    assert "resolve_script.py" in section, (
        "§Probe chain does not mention resolve_script.py's different order"
    )
    assert "diverge" in section.lower() or "different order" in section.lower()


# --------------------------------------------------------------------------- #
# PR #144 round 4 (A2) — an UNLINKED cwd DEGRADES; it does not crash
# --------------------------------------------------------------------------- #
def _neutral_resolver(tmp_path: Path) -> Path:
    """A copy of the SHIPPED resolver with no framework-root ancestor.

    Probe 4 (``self``) resolves off the root the RESOLVER lives in, and a
    subprocess cannot be handed ``self_root=None``. Running the copy from here
    is the hermeticity opt-out: ``_self_root()`` returns ``None``, so the only
    root left standing is the one the case names.
    """
    target = tmp_path / "neutral" / "resolve_script.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(RESOLVE_SCRIPT_PY.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _from_unlinked_cwd(argv, *, gone: Path, env, script: Path):
    """Run the python CLI from a cwd that was rmdir'd out from under the process.

    ``subprocess(cwd=...)`` cannot express this — the directory has to still
    exist at spawn time. So the child chdirs into ``gone`` and removes it
    itself, which is exactly the shape a ``rm -rf`` of a checkout produces in a
    long-lived agent process.
    """
    gone.mkdir(parents=True, exist_ok=True)
    program = (
        "import os, sys\n"
        f"os.chdir({str(gone)!r}); os.rmdir({str(gone)!r})\n"
        f"sys.path.insert(0, {str(script.parent)!r})\n"
        "import resolve_script\n"
        f"sys.exit(resolve_script._main({list(argv)!r}))\n"
    )
    return subprocess.run(
        [sys.executable, "-c", program], env=env, capture_output=True, text=True
    )


def test_unlinked_cwd_parity_both_resolvers_still_answer(tmp_path):
    """cwd deleted + a named override install: BOTH resolvers exit 0, same root.

    ``os.getcwd()`` in ``resolve_shared_script`` was unguarded while the
    IDENTICAL call one function away (``_named_root``) was already wrapped in
    ``except OSError``. So an unlinked cwd killed the python resolver with a
    bare ``FileNotFoundError`` BEFORE probe 1 ran, losing every resolution
    probes 2-5 would have answered — while ``resolve_root.sh`` exits 0 from the
    IDENTICAL cwd. That is a parity break, not a shared limitation.

    The exit code makes it worse: a traceback exits 1, the same code the
    fail-loud "not found" diagnostic uses, so a caller keying on the return
    code reads a broken ENVIRONMENT as a genuine MISS and reports the wrong
    thing. Probe 1 simply drops out (no cwd names no dir to probe from) and the
    named override answers, as the shell script does. That drop-out is pinned
    by ``test_unlinked_cwd_records_no_fabricated_toplevel_path`` below — this
    case takes the SUCCESS path and never renders the report.
    """
    install = _framework_root(tmp_path / "plugin-install")
    home = tmp_path / "home"
    _cache_root(home).mkdir(parents=True)  # exists, empty: the cache cannot win
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PLUGIN_ROOT"] = str(install)
    gone = tmp_path / "gone"

    py = _from_unlinked_cwd(
        [NAME], gone=gone, env=env, script=_neutral_resolver(tmp_path)
    )
    gone.mkdir(parents=True, exist_ok=True)
    sh = subprocess.run(
        ["bash", "-c", f"cd {gone}; rmdir {gone}; bash {RESOLVE_ROOT_SH}"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert sh.returncode == 0, sh.stderr
    assert _real(sh.stdout.strip()) == _real(install)
    assert "Traceback" not in py.stderr, (
        f"the unlinked cwd escaped as a traceback:\n{py.stderr}"
    )
    assert py.returncode == 0, (
        f"resolve_root.sh answered from this cwd and the module did not; "
        f"exit {py.returncode}, stderr:\n{py.stderr}"
    )
    assert _root_of(py.stdout.strip()) == _real(sh.stdout.strip())


def test_unlinked_cwd_records_no_fabricated_toplevel_path(tmp_path):
    """The MISS path: probe 1 must drop out, not record the string "None".

    The parity case above takes the SUCCESS path — a named override answers, so
    the probe report is never rendered and the ``and cwd is not None`` guard on
    the toplevel record is never observed. Without it, an unlinked cwd emits
    ``('toplevel', 'None', 'miss')``, so the fail-loud diagnostic shows
    ``  - None  [toplevel: miss]`` — a fabricated path presented to the operator
    as a probed root — and the literal ``"None"`` enters the #129-compatible
    ``probed_roots`` list. Distinct from the by-design "an unset root produces
    no line": that is a MISSING line for an unset root, this is a BOGUS one.
    """
    home = tmp_path / "home"
    _cache_root(home).mkdir(parents=True)  # exists, empty: nothing can win
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("CLAUDE_PLUGIN_ROOT", None)  # no override: force the miss path
    gone = tmp_path / "gone"

    py = _from_unlinked_cwd(
        ["absent_module.py"], gone=gone, env=env, script=_neutral_resolver(tmp_path)
    )

    assert py.returncode == 1, f"expected the fail-loud miss, got {py.returncode}"
    assert "Traceback" not in py.stderr, py.stderr
    assert "[toplevel:" not in py.stderr, (
        f"probe 1 has no cwd to name and must not be recorded:\n{py.stderr}"
    )
    assert "- None" not in py.stderr, (
        f"a fabricated 'None' path reached the diagnostic:\n{py.stderr}"
    )
