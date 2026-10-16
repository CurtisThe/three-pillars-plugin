"""test_proof_root_callers.py — every default-path caller uses the resolver (1.3).

In a temp linked worktree (cwd = the worktree): `review_proof.default_proof_root()`
IS `proof_root.default_proof_root()`; converge's default state path, converge_cli's
default proof root and `capture_proof(root=None)` all land under the git-dir root,
outside the worktree toplevel. An AST guard keeps any other runtime module from
spelling the proof-root directory itself: `review-proof` as a path component of any
string literal, or of a literal `os.path.join` / `Path` / `joinpath` / `/` join.
"""
from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import converge  # noqa: E402
import converge_cli  # noqa: E402
import loop_itest  # noqa: E402
import proof_root  # noqa: E402
import review_proof  # noqa: E402
from proof_root_itest import SUB, linked  # noqa: E402

PR = "https://github.com/o/r/pull/9"
SHARED = HERE.parents[1] / "_shared"


def _worktree(tmp_path, monkeypatch):
    """→ (wt, expected git-dir root, base, head); cwd is the linked worktree."""
    monkeypatch.delenv(proof_root.ENV_VAR, raising=False)
    main, wt = linked(tmp_path)
    base = loop_itest.git(wt, "rev-parse", "HEAD")
    loop_itest.write(wt, "src/f.py", "".join(f"x{i} = {i}\n" for i in range(5)))
    loop_itest.git(wt, "add", "src/f.py")
    loop_itest.git(wt, "commit", "-q", "-m", "feature")
    head = loop_itest.git(wt, "rev-parse", "HEAD")
    monkeypatch.chdir(wt)
    return wt, (main / ".git" / "worktrees" / "wt" / SUB).resolve(), base, head


def _outside(path, wt) -> bool:
    return Path(wt).resolve() not in Path(path).resolve().parents


def test_review_proof_default_is_the_proof_root_delegate(tmp_path, monkeypatch):
    wt, expected, _b, _h = _worktree(tmp_path, monkeypatch)
    assert review_proof.default_proof_root() == proof_root.default_proof_root() == expected
    assert _outside(expected, wt)


def test_converge_default_state_path_is_under_the_git_dir_root(tmp_path, monkeypatch):
    wt, expected, base, head = _worktree(tmp_path, monkeypatch)
    angle = tmp_path / "angle.md"
    angle.write_text(loop_itest.CLEAN, encoding="utf-8")
    seen = []

    def run_round_fn(stdin):
        seen.append(stdin)
        return dict(converged=False)

    converge.converge(base=base, head=head, pr_url=PR, config=dict(),
                      angle_files=[str(angle)], post_fn=lambda _u, _b: True,
                      comments_fn=lambda _u: [], self_login_fn=lambda: None,
                      run_round_fn=run_round_fn, out=io.StringIO(), err=io.StringIO())
    assert seen, "run_round was never reached"
    state = Path(seen[0]["state_path"])
    assert state == expected / "iterate-state.v1.json" and state.is_file()
    assert Path(seen[0]["review_proof_root"]) == expected and _outside(state, wt)


def test_converge_cli_default_proof_root_is_under_the_git_dir_root(tmp_path, monkeypatch):
    wt, expected, base, head = _worktree(tmp_path, monkeypatch)
    cfg = tmp_path / "config.json"
    cfg.write_text("[]", encoding="utf-8")
    got = []
    monkeypatch.setattr(converge, "converge", lambda **kw: got.append(kw) or 0)
    rc = converge_cli.main(["--base", base, "--head", head, "--pr-url", PR,
                            "--config", str(cfg)])
    assert rc == 0 and got[0]["proof_root"] == expected and _outside(expected, wt)


def test_capture_proof_default_root_writes_outside_the_tree(tmp_path, monkeypatch):
    wt, expected, base, head = _worktree(tmp_path, monkeypatch)
    meta = review_proof.capture_proof(base, head, [loop_itest.CLEAN])
    assert meta["degraded"] is False
    assert Path(meta["proof_dir"]) == expected / head
    assert (expected / head / "meta.json").is_file() and _outside(meta["proof_dir"], wt)
    assert not (wt / ".three-pillars").exists()


_SEGMENT = re.compile(r"(?:^|[/\\])review-proof(?:$|[/\\])")
_JOINERS = frozenset(("join", "joinpath", "Path", "PurePath", "PosixPath", "PurePosixPath"))


def _names_the_root(value: str) -> bool:
    """`review-proof` as a path component (between separators, or at either end)."""
    return bool(_SEGMENT.search(value))


def _parts(node) -> "list[str] | None":
    """The string parts of a `/` or `+` chain, or None when any part is not a literal."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
        left, right = _parts(node.left), _parts(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add) and left and right:
            return left[:-1] + [left[-1] + right[0]] + right[1:]
        return left + right
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return None if not isinstance(node, (ast.Name, ast.Attribute, ast.Call)) else []


def _joined(node) -> "str | None":
    """The literal path a join builds: `os.path.join`, `Path(..)`, `.joinpath`, a `/` chain."""
    if isinstance(node, ast.Call):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name in _JOINERS:
            parts = [a.value for a in node.args
                     if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            return "/".join(parts) if parts else None
    parts = _parts(node) if isinstance(node, ast.BinOp) else None
    return "/".join(parts) if parts else None


def _offending_lines(source: str, filename="<src>") -> "list[int]":
    """Line numbers where `source` spells the proof-root dir: a literal or a join of literals."""
    hits = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
        else:
            value = _joined(node)
        if value is not None and _names_the_root(value):
            hits.append(node.lineno)
    return hits


def _runtime_modules():
    for d in (HERE, SHARED):
        for p in sorted(d.rglob("*.py")):
            name = p.name
            if name.startswith("test_") or name.endswith("_itest.py") or name == "conftest.py":
                continue
            if p == HERE / "proof_root.py":
                continue
            yield p


def test_no_other_runtime_module_spells_the_proof_root_dir():
    offenders = []
    for p in _runtime_modules():
        rel = p.relative_to(HERE.parents[2])
        offenders += [f"{rel}:{n}" for n in _offending_lines(p.read_text(encoding="utf-8"), str(p))]
    assert not offenders, f"proof-root dir spelled outside proof_root.py: {offenders}"


SPELLINGS = (
    '"review-proof"', '".three-pillars/review-proof"', '"x/review-proof/"',
    '".three-pillars/review-proof/iterate-state.v1.json"',
    '"review-proof/rounds"', '"C:\\\\repo\\\\review-proof\\\\x"',
    'ap.add_argument("--state", default=".three-pillars/review-proof/iterate-state.v1.json")',
    'f"{top}/review-proof/{pr}"',
    'os.path.join(top, ".three-pillars", "review-" "proof", "iterate-state.v1.json")',
    'Path(top) / ".three-pillars" / ("review-" + "proof") / "iterate-state.v1.json"',
    'Path(top).joinpath(".three-pillars", "review-" + "proof")',
)


def test_guard_catches_every_spelling():
    for src in SPELLINGS:
        assert _offending_lines(src), src
    for prose in ('"review-proof-on-head predicate"', '"codereview-proof-of-review"',
                  '"design: review-proof-out-of-tree"', '"enforce-review-proof"',
                  'os.path.join(top, "reviews", "proof")'):
        assert not _offending_lines(prose), prose


def test_review_proof_stays_under_the_hard_cap():
    lines = (HERE / "review_proof.py").read_text(encoding="utf-8").count("\n")
    assert lines <= 500, f"review_proof.py is {lines} lines (hard cap 500)"
