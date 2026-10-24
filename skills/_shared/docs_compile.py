"""docs_compile.py — fold every pending living-doc fragment into the living docs in one commit.

design: living-doc-fragments, Tasks 1.4-1.5 (§Interfaces steps 1-5: per folded slug ``final_doc_state.close``
and ``reconcile_slug``, a clock-free ``*Last updated:*`` re-stamp, the rollovers, then the zero-drop
verify (``docs_compile_verify``) last; a refusal restores every touched path from HEAD and exits 1).
``compile_all(repo_root, *, base_ref, prs, commit=False) -> CompileResult(folded, conflicts, commit)``:
fold each fragment at HEAD atomically in ``(date, slug)`` order (a ``FoldError`` keeps the file and
names it in ``conflicts``), number placeholders in memory against ``base_ref`` over every tracked
``.md`` (``number_issues.plan_numbering``), write the docs, roll History and caps per touched doc,
delete folded fragments (one holding a ``## Vision`` section is cut down to it), then one commit
``docs(compile): fold N fragments (<slugs>)``. Without ``commit`` nothing is written. Deterministic:
no clock; every date comes from a fragment. CLI ``compile --base-ref REF [--pr SLUG=N]… [--commit]
[--repo-root R] [--json]``: exit 0 ok/nothing, 2 usage/git error, 3 dirty tree, 4 conflicts. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
for _path in (_SHARED, _SHARED.parent / "tp-merge-from-main" / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import certify_issues  # noqa: E402
import doc_rollover  # noqa: E402
import docs_compile_verify  # noqa: E402
import docs_fold  # noqa: E402
import docs_fold_text  # noqa: E402
import file_size_guard  # noqa: E402
import final_doc_state  # noqa: E402
import history_rollover  # noqa: E402
import living_doc_archive  # noqa: E402
import number_issues  # noqa: E402
import pending_changes  # noqa: E402
import pending_flip  # noqa: E402
import reconcile_docs  # noqa: E402
from number_issues import NumberIssuesError, _run_git  # noqa: E402

CHANGES_DIR = pending_changes.CHANGES_DIR


class DirtyTree(RuntimeError):
    """The working tree has uncommitted changes; the compile refuses to mix them in."""


@dataclass
class CompileResult:
    folded: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)  # (slug, reason)
    commit: str | None = None
    refused: list = field(default_factory=list)  # dropped atoms (the verify refused; tree restored)
    duplicates: list = field(default_factory=list)  # issue IDs headed twice (refused; tree restored)
    over_cap: list = field(default_factory=list)  # (doc, chars, hard cap) of a doc past its hard cap (refused)


def vision_only(text: str) -> str:
    """``text`` cut down to its frontmatter plus the ``## Vision`` section."""
    lines = text.splitlines(keepends=True)
    fm_end = 0
    if lines and lines[0].strip() == "---":
        fm_end = next((i + 1 for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "## Vision")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = "".join(lines[start:end]).rstrip("\n") + "\n"
    return "".join(lines[:fm_end]) + "\n" + section


def _fold_all(docs: dict, fragments, prs: dict, root: Path):
    """(docs, folded slugs, conflicts, cut, directed) after folding each fragment atomically."""
    folded, conflicts, cut, directed = [], [], {}, set()
    for frag in fragments:
        if not frag.problems and set(frag.sections) == {"Vision"}:
            continue  # waits for the operator, not a conflict
        try:
            result = docs_fold.fold(docs, frag, pr=prs.get(frag.slug), root=root)
        except docs_fold.FoldError as exc:
            conflicts.append((frag.slug, str(exc)))
            continue
        docs = result.docs
        directed |= result.directed
        folded.append(frag.slug)
        if "Vision" in frag.sections:
            cut[frag.slug] = True
    return docs, folded, conflicts, cut, directed


def _plan(root: Path, base_ref: str, prs: dict):
    """(head, after, folded, conflicts, cut, fragments, directed): all in memory, nothing written."""
    paths = number_issues._head_paths(root)
    head = number_issues._doc_at(root, "HEAD", paths)
    fragments = pending_changes.list_fragments(root)
    docs, folded, conflicts, cut, directed = _fold_all(head, fragments, prs, root)
    base = number_issues._doc_at(root, base_ref, number_issues.base_read_paths(paths))
    after = dict(docs)
    after.update(number_issues.plan_numbering(docs, base=base, merge_base=base))
    return head, after, folded, conflicts, cut, fragments, directed


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _apply(root: Path, head: dict, after: dict, folded: list, cut: dict) -> list:
    """Write the folded tree to disk; returns the touched doc paths (fragments excluded)."""
    touched = []
    for rel, text in after.items():
        if text != head.get(rel) and not rel.startswith(CHANGES_DIR + "/"):
            _write(root, rel, text)
            touched.append(rel)
    for slug in folded:
        rel = f"{CHANGES_DIR}/{slug}.md"
        if slug in cut:
            _write(root, rel, vision_only(after[rel]))
        else:
            (root / rel).unlink()
    return touched


def _roll(root: Path, touched: list) -> None:
    for rel in sorted(touched):
        if rel in living_doc_archive.ARCHIVES:
            history_rollover.roll(root, rel)
            doc_rollover.roll_to_cap(root, rel)


def _changed_paths(root: Path) -> list:
    out = _run_git(root, ["status", "--porcelain", "-z", "--untracked-files=all"])
    paths = []
    for entry in out.split("\0"):
        if entry:
            paths.append(entry[3:])
    return paths


def _commit(root: Path, folded: list, conflicts: list) -> str:
    paths = _changed_paths(root)
    _run_git(root, ["add", "--", *paths])
    body = "".join(f"- {slug}: kept, {reason}\n" for slug, reason in conflicts)
    msg = f"docs(compile): fold {len(folded)} fragments ({', '.join(folded)})"
    _run_git(root, ["commit", "-q", "-m", msg + (f"\n\n{body}" if body else "")])
    return _run_git(root, ["rev-parse", "HEAD"]).strip()


def _close_and_reconcile(root: Path, folded: list, prs: dict) -> None:
    """Per folded slug: move its inventory row and flip the pending token, then repoint and flip."""
    for slug in folded:
        pr = prs.get(slug)
        final_doc_state.close(root, slug, fragment_aware=False)
        reconcile_docs.reconcile_slug(root, slug, pr, apply=True)
        if pr is not None:
            pending_flip.flip(root, slug, pr, apply=True)  # upgrade Done (completion PR) to Done — PR #N


def _restamp(root: Path, date: str) -> list:
    """Stamp every changed doc's ``*Last updated:`` with the fragments' date (the clock is not used)."""
    docs = [p for p in _changed_paths(root) if not p.startswith(CHANGES_DIR + "/") and p.endswith(".md")]
    for rel in docs:
        text = (root / rel).read_text(encoding="utf-8")
        if docs_fold_text.stamp(text, date) != text:
            _write(root, rel, docs_fold_text.stamp(text, date))
    return docs


def _dup_keys(texts) -> set:
    """Issue IDs headed more than once across the given issue-doc texts."""
    seen, dups = set(), set()
    for text in texts:
        for issue_id in number_issues.NUMBERED.finditer(text):
            key = issue_id.group(1) + issue_id.group(2)
            (dups if key in seen else seen).add(key)
    return dups


def _duplicate_ids(root: Path, base_ref: str | None = None) -> list:
    """Issue IDs headed more than once in the working tree's issue docs and not already so on ``base_ref``."""
    rels = certify_issues.ISSUE_ID_DOCS
    dups = _dup_keys((root / rel).read_text(encoding="utf-8") for rel in rels if (root / rel).is_file())
    if base_ref is not None and dups:
        dups -= _dup_keys(number_issues._doc_at(root, base_ref, list(rels)).values())
    return sorted(dups)


def _over_cap(root: Path, touched: list) -> list:
    """``(doc, chars, hard)`` for each touched living doc over its hard cap, by the shared predicate."""
    framework = file_size_guard.is_framework_tree(root)
    over = []
    for rel in sorted(touched):
        if not file_size_guard.is_living_doc(rel) or file_size_guard.is_exempt(rel) or not (root / rel).is_file():
            continue
        chars = file_size_guard.measure(root / rel)[1]
        hard = file_size_guard.char_caps(rel, framework)[1]
        if chars > hard:
            over.append((rel, chars, hard))
    return over


def _restore(root: Path) -> None:
    """Put every path the compile touched back to HEAD; files it created are removed."""
    tracked = []
    for entry in _run_git(root, ["status", "--porcelain", "-z", "--untracked-files=all"]).split("\0"):
        if entry and entry.startswith("??"):
            (root / entry[3:]).unlink()
        elif entry:
            tracked.append(entry[3:])
    if tracked:
        _run_git(root, ["restore", "--source=HEAD", "--worktree", "--", *tracked])


def _verify(root: Path, head: dict, after: dict, folded: list, fragments: list, directed: set, prs: dict) -> list:
    """The dropped atoms: the guarded docs at HEAD against the working tree, fragments as numbered."""
    by_slug = {f.slug: f for f in fragments}
    rels = {r for r in head if docs_compile_verify.is_guarded(r)}
    rels |= {p for p in _changed_paths(root) if docs_compile_verify.is_guarded(p)}
    disk = {r: (root / r).read_text(encoding="utf-8") for r in rels if (root / r).is_file()}
    texts = [docs_fold_text.expand_pr(after[f"{CHANGES_DIR}/{s}.md"], prs.get(s)) for s in folded]
    resolved = {b.heading: by_slug[s].date for s in folded for b in by_slug[s].sections.get("Known issues — resolve", [])}
    return docs_compile_verify.verify_compile(head, disk, texts, resolved, directed)


def compile_all(repo_root, *, base_ref: str, prs: dict | None = None, commit: bool = False) -> CompileResult:
    root = Path(repo_root)
    if _run_git(root, ["status", "--porcelain"]).strip():
        raise DirtyTree("working tree is not clean")
    prs = dict(prs or {})
    head, after, folded, conflicts, cut, fragments, directed = _plan(root, base_ref, prs)
    result = CompileResult(folded, conflicts)
    if not commit or not folded:
        return result
    _apply(root, head, after, folded, cut)
    _close_and_reconcile(root, folded, prs)
    date = max(f.date for f in fragments if f.slug in folded)
    touched = _restamp(root, date)
    _roll(root, touched)
    result.over_cap = _over_cap(root, touched)
    if result.over_cap:
        _restore(root)
        return result
    result.duplicates = _duplicate_ids(root, base_ref)
    if result.duplicates:
        _restore(root)
        return result
    result.refused = _verify(root, head, after, folded, fragments, directed, prs)
    if result.refused:
        _restore(root)
        return result
    result.commit = _commit(root, folded, conflicts)
    return result


def _parse_prs(items: list) -> dict:
    prs = {}
    for item in items:
        slug, _, num = item.partition("=")
        if not slug or not num.isdigit():
            raise ValueError(f"--pr expects SLUG=N, got {item!r}")
        prs[slug] = int(num)
    return prs


def _fill_prs(root: str, prs: dict) -> dict:
    """The CLI-only lookup: a folded slug with no ``--pr`` asks ``gh`` (None on Gitea/failure)."""
    import reconcile_docs

    for slug in pending_changes.pending_slugs(root):
        if slug not in prs:
            number = reconcile_docs.merged_pr_number(root, slug)
            if number is None:
                print(f"docs-compile: PR number unknown for {slug}")
            else:
                prs[slug] = number
    return prs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="docs_compile.py", description="fold living-doc fragments")
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--pr", action="append", default=[])
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        prs = _parse_prs(args.pr)
        if _run_git(Path(args.repo_root), ["status", "--porcelain"]).strip():
            raise DirtyTree("working tree is not clean")
        prs = _fill_prs(args.repo_root, prs) if args.commit else prs
        result = compile_all(args.repo_root, base_ref=args.base_ref, prs=prs, commit=args.commit)
    except DirtyTree as exc:
        print(f"docs-compile: dirty tree: {exc}", file=sys.stderr)
        return 3
    except (NumberIssuesError, ValueError) as exc:
        print(f"docs-compile: error: {exc}", file=sys.stderr)
        return 2
    for slug, reason in result.conflicts:
        print(f"docs-compile: {slug}: {reason}")
    for rel, chars, hard in result.over_cap:
        print(f"docs-compile: {rel} over hard cap ({chars} > {hard}); run /tp-docs-update --diet")
    for issue_id in result.duplicates:
        print(f"docs-compile: duplicate issue ID {issue_id}")
    for kind, signature in result.refused:
        print(f"docs-compile: dropped {kind}: {signature}")
    if args.json:
        print(json.dumps({"folded": result.folded, "conflicts": result.conflicts, "commit": result.commit,
                          "refused": [list(atom) for atom in result.refused],
                          "duplicates": result.duplicates,
                          "over_cap": [list(item) for item in result.over_cap]}))
    return 1 if result.refused or result.duplicates or result.over_cap else 4 if result.conflicts else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
