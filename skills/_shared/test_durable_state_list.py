"""The durable-state list stays closed: doc list == DURABLE_STATE, and every
home- or temp-rooted literal in shipped code is durable, scratch or exempt."""
import ast
import fnmatch
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scratch_leftovers  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "skills" / "_shared" / "design-run-launch.md"
_T = "/" + "tmp" + "/"
PREFIXES = ("~/", "$HOME/", _T, "/var" + _T, "/dev" + "/shm/")
TMPROOT = "/" + "tmp"  # built from pieces: no absolute-temp literal on one line
BARE = (TMPROOT,)  # the temp root itself, as a literal (a socket parent), is collected too
FIX = "add it to DURABLE_STATE and the design-run-launch.md list in the same PR"

# (file, literal, reason): a read, a doc example, a test fixture, or a stated write (the
# reason says what is written and why it is not a leftover).
READ_OR_DOC_ONLY = [
    ('skills/_shared/allowlist_settings.py',
     '~/.claude/settings.json',
     'path only; nothing is written'),
    ('skills/_shared/attempt_scan.py',
     '~/.claude',
     'default Claude config dir fallback (home noise area ~/.claude*); read'),
    ('skills/_shared/cache_measure.py',
     '~/.claude',
     'default Claude config dir fallback (home noise area ~/.claude*); read'),
    ('skills/_shared/child_profile.py',
     '~/.claude',
     'default Claude config dir fallback (home noise area ~/.claude*); read'),
    ('skills/_shared/child_transcript.py',
     '~/.claude',
     'default Claude config dir fallback (home noise area ~/.claude*); read'),
    ('skills/_shared/forge_gitea.py',
     '~/.config/tea/config.yml',
     'tea CLI config; read'),
    ('skills/_shared/lessons.py',
     '~/.claude',
     'config-dir fallback; the user lesson layer writes lessons.md under ~/.claude/three-pillars'
     ' (home noise area ~/.claude*, the user-chosen layer)'),
    ('skills/_shared/resolve_script.py',
     '~/.claude/plugins/cache',
     'plugin cache lookup; read'),
    ('skills/_shared/stage_reset.py',
     '~/.claude',
     'default Claude config dir fallback (home noise area ~/.claude*); read'),
    ('skills/_shared/delete_fence_roots.py',
     TMPROOT,
     'never-root entry of the delete fence; nothing is created'),
    ('skills/_shared/reviewer_delete_hook.py',
     TMPROOT,
     'deny-list entry for scratch_for; nothing is created'),
    ('skills/_shared/scratch_reap.py',
     TMPROOT,
     'reap fallback root: deletes stale scratch there, creates nothing'),
    ('skills/conftest.py',
     TMPROOT,
     'socket and basetemp parent: a long or in-tree TMPDIR run makes short run-tagged tpt-<tag>-* '
     'dirs here (AF_UNIX 107-char limit; tmp_path outside the checkout) and removes them at '
     'session end'),
    ('skills/_shared/run_scratch.py',
     TMPROOT,
     'scratch-checkout parent: when TMPDIR is the in-tree run dir, round_scratch makes each '
     "reviewer copy's tp-angle-* dir here and refactor_invariance / changed_tests_runs make "
     'their tp-invariance-* / tp-runs-* scratch here (outside the checkout); each is removed '
     'after use'),
    ('skills/tp-' + 'fleet/scripts/transcript_paths.py',
     '~/.claude/projects',
     'transcript lookup; read'),
    ('skills/tp-' + 'worktree/scripts/check_sole_plugin.py',
     '~/.claude/plugins/installed_plugins.json',
     'plugin registry; read'),
]


def _doc_entries(text=None):
    text = DOC.read_text(encoding="utf-8") if text is None else text
    body = text.split("## Durable state", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^- `([^`]+)`", body, re.M)


def test_doc_list_equals_durable_state():
    doc, code = set(_doc_entries()), set(scratch_leftovers.DURABLE_STATE)
    assert len(doc) == 7
    assert doc == code, f"only in doc: {sorted(doc - code)}; only in code: {sorted(code - doc)}"


def _docstring_nodes(tree):
    skip = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = n.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant):
                skip.add(id(b[0].value))
    return skip


def _is_home_call(n):
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "home")


def _chain(n):
    """Path.home() / "a" / "b" -> "~/a/b", else None."""
    parts = []
    while isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
        if not (isinstance(n.right, ast.Constant) and isinstance(n.right.value, str)):
            return None
        parts.append(n.right.value)
        n = n.left
    if _is_home_call(n) and parts:
        return "~/" + "/".join(reversed(parts))
    return None


def scan_source(src):
    tree = ast.parse(src)
    skip = _docstring_nodes(tree)
    found = []
    inner = {id(n.left) for n in ast.walk(tree)
             if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip:
            found.append(n.value)
        elif isinstance(n, ast.JoinedStr) and n.values:
            first = n.values[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append(first.value)
        elif isinstance(n, ast.BinOp) and id(n) not in inner:
            c = _chain(n)
            if c:
                found.append(c)
    return sorted({s for s in found if s.startswith(PREFIXES) or s in BARE})


def _durable(lit):
    lit = lit.replace("$HOME/", "~/")
    for d in scratch_leftovers.DURABLE_STATE:
        if d.startswith("~/") and (lit == d or lit.startswith(d + "/")):
            return True
    return False


_WRITE = re.compile(r"\b(write|writes|makes|creates)\b")
_NO_WRITE = ("nothing is created", "creates nothing")
# the named temp-rooted writes: the conftest roots (P12) and the angle exec-dir parent (review r1)
TEMP_WRITE_EXCEPTIONS = {("skills/conftest.py", TMPROOT), ("skills/_shared/run_scratch.py", TMPROOT)}


def _stated_write(reason):
    for phrase in _NO_WRITE:
        reason = reason.replace(phrase, "")
    return bool(_WRITE.search(reason))


def _noise_home(lit):
    """True when `lit` is `~/<name>[/...]` and `<name>` is a home noise name."""
    lit = lit.replace("$HOME/", "~/")
    if not lit.startswith("~/"):
        return False
    name = lit[2:].split("/", 1)[0]
    return any(fnmatch.fnmatchcase(name, p) for p in scratch_leftovers.NOISE_HOME)


def _table_violations(table):
    """Entries that state a write but sit outside a home noise name (they would hide a real
    durable writer): a write goes into DURABLE_STATE and the doc list, never into the table."""
    return [f"{f}: {lit!r}: {FIX}" for f, lit, reason in table
            if _stated_write(reason) and not _noise_home(lit) and (f, lit) not in TEMP_WRITE_EXCEPTIONS]


def _ok(rel, lit):
    return (_durable(lit) or "/.tp-scratch/" in lit
            or any(rel == f and lit == s for f, s, _ in READ_OR_DOC_ONLY))


def _violations(files):
    out = []
    for rel, src in files:
        for lit in scan_source(src):
            if not _ok(rel, lit):
                out.append(f"{rel}: {lit!r}: {FIX}")
    return out


def test_shipped_code_has_no_undeclared_durable_literals():
    files = []
    for p in sorted((ROOT / "skills").rglob("*.py")):
        if p.name.startswith("test_") or any(x.endswith("_tests") for x in p.parts):
            continue
        files.append((p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8")))
    bad = _violations(files)
    assert not bad, "\n".join(bad)


def test_synthetic_new_home_state_fails_with_guidance(tmp_path):
    mod = tmp_path / "newmod.py"
    mod.write_text('from pathlib import Path\np = Path.home() / ".newstate" / "f"\n',
                   encoding="utf-8")
    bad = _violations([("newmod.py", mod.read_text(encoding="utf-8"))])
    assert len(bad) == 1
    assert "newmod.py" in bad[0] and "~/.newstate/f" in bad[0] and FIX in bad[0]


def test_docstrings_and_comments_are_not_collected():
    src = '"""see ~/.docstring/x"""\n# ~/.comment/y\nx = 1\n'
    assert scan_source(src) == []


def test_scan_variants():
    src = ('import os\na = os.path.expanduser("~/.one")\nb = f"$HOME/.two/{a}"\n'
           'c = "~/.three-pillars/x"\n')
    got = scan_source(src)
    assert "~/.one" in got and "$HOME/.two/" in got
    assert [g for g in got if not _durable(g)] == ["$HOME/.two/", "~/.one"]


def test_conftest_socket_root_is_a_visible_entry_with_its_reason():
    bare = "/" + "tmp"  # built from pieces: no absolute-temp literal on one line
    assert scan_source('x = "%s"\n' % bare) == [bare]
    src = (ROOT / "skills" / "conftest.py").read_text(encoding="utf-8")
    assert bare in scan_source(src)
    assert any(f == "skills/conftest.py" and s == bare and "socket" in r
               for f, s, r in READ_OR_DOC_ONLY)


def test_the_lessons_write_is_not_filed_as_a_read():
    reason = next(r for f, _s, r in READ_OR_DOC_ONLY if f.endswith("lessons.py"))
    assert "write" in reason and "noise" in reason


def test_a_stated_write_in_the_table_must_lie_under_a_home_noise_name():
    assert _table_violations(READ_OR_DOC_ONLY) == []
    hidden = [("skills/_shared/newmod.py", "~/.newstate", "writes cache.json here")]
    (bad,) = _table_violations(hidden)
    assert "newmod.py" in bad and FIX in bad
    assert _table_violations([("a.py", "~/.claude", "writes lessons.md")]) == []
    assert _table_violations([("a.py", "~/.claude-x/y", "makes a dir")]) == []
    assert _table_violations([("a.py", "~/.claude", "creates nothing")]) == []
    assert _table_violations([("a.py", "~/.config", "default dir; read")]) == []
    assert len(_table_violations([("a.py", TMPROOT, "creates a dir here")])) == 1


def test_the_lessons_entry_stays_valid_under_the_write_rule():
    entry = [e for e in READ_OR_DOC_ONLY if e[0].endswith("lessons.py")]
    assert entry and _stated_write(entry[0][2]) and _noise_home(entry[0][1])
    assert _table_violations(entry) == []
