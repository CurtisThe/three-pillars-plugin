"""test_docs_compile_caps.py — fix.3: the compile refuses a result that pushes a living doc over its hard cap.

design: living-doc-fragments, fidelity-audit fix 3. After the rollovers each touched living doc is
measured with the shared ``file_size_guard`` predicate; one over its hard cap restores the tree, exits 1
and publishes nothing. Real temp git repos; assertions are exit codes, git state and branch tips
(Oracle: example), never message wording.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import docs_compile  # noqa: E402
import file_size_guard  # noqa: E402
from test_docs_compile import ARCH, CH, KI, frag, git, make_repo  # noqa: E402
from test_docs_compile_publish import Forge, publish, tip, with_origin  # noqa: E402

CAP = file_size_guard.char_caps(ARCH, False)[1]
PAD = "- " + "p" * 98 + "\n"


def _arch(chars: int) -> str:
    """An architecture doc of about ``chars`` characters (padding lives under ``### Dist``)."""
    head = "# Architecture\n*Last updated: 2019-05-05 — see [History](#history).*\n\n## Key\n### Dist\n- one\n"
    tail = "\n## History\n- **2019-05-05** — first\n"
    return head + PAD * ((chars - len(head) - len(tail)) // len(PAD)) + tail


def _bullets(n: int) -> str:
    return "\n## Architecture\n\n### Dist\n" + "".join(f"+ - {'b' * 200} {i}\n" for i in range(n))


def test_over_cap_result_refuses_restores_and_commits_nothing(tmp_path, capsys):
    root = make_repo(tmp_path, {"alpha": frag("alpha", "2020-01-02", _bullets(4))}, docs={ARCH: _arch(CAP - 300)})
    base = git(root, "rev-parse", "HEAD")
    rc = docs_compile.main(["--base-ref", base, "--commit", "--repo-root", str(root), "--pr", "alpha=7"])
    assert rc == 1 and "architecture.md" in capsys.readouterr().out
    assert git(root, "status", "--porcelain") == ""
    assert git(root, "rev-parse", "HEAD") == base
    assert (root / CH / "alpha.md").exists()


def test_under_cap_result_still_compiles(tmp_path):
    root = make_repo(tmp_path, {"alpha": frag("alpha", "2020-01-02", _bullets(1))}, docs={ARCH: _arch(CAP - 3000)})
    base = git(root, "rev-parse", "HEAD")
    assert docs_compile.main(["--base-ref", base, "--commit", "--repo-root", str(root), "--pr", "alpha=7"]) == 0
    assert git(root, "rev-parse", "HEAD") != base
    assert len((root / ARCH).read_text(encoding="utf-8")) <= CAP


def test_publish_pushes_nothing_for_an_over_cap_compile(tmp_path):
    root, bare, base = with_origin(tmp_path, {"alpha": frag("alpha", "2020-01-02", _bullets(4))},
                                   docs={ARCH: _arch(CAP - 300)})
    forge = Forge()
    publish(root, forge)
    assert tip(bare) == ""
    assert not [c for c in forge.calls if c[0] == "pr-create"]
