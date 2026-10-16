"""test_github_pr_author_delegation.py — `github_pr_author` holds no copy of the token logic.

design: review-proof-ambient-gh-identity, Task 1.1 (behaviour B7)

The identity core (`automation_identity.py`) owns `BotAuthUnavailable`, `resolve_pr_author`,
`bot_token`, config load and `_default_repo_root`. `github_pr_author` keeps its public names by
re-exporting the core's objects, so its callers and every existing test are unchanged, and
`gh auth token --user` has exactly one implementation. `create_pr`'s bot branch builds its child env through the core.

Run with: pytest skills/_shared/test_github_pr_author_delegation.py -q
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE / "explainer"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import automation_identity as ai  # noqa: E402
import github_pr_author as gpa  # noqa: E402

CFG = {"github": {"pr_author_account": "CurtisTheBot", "used_for": "all-prs"}}


def test_the_exception_is_the_cores():
    assert gpa.BotAuthUnavailable is ai.BotAuthUnavailable


def test_the_moved_functions_are_the_cores_objects():
    assert gpa.resolve_pr_author is ai.resolve_pr_author
    assert gpa.bot_token is ai.bot_token
    assert gpa._load_repo_config is ai.load_repo_config


def test_the_default_repo_root_is_the_cores_not_a_second_toplevel_lookup():
    """The shipped autouse fixture wraps the core's attribute for hermeticity; the object it
    wrapped (`__wrapped__`) is the function `github_pr_author` re-exports."""
    core = ai._default_repo_root
    assert gpa._default_repo_root is getattr(core, "__wrapped__", core)


def _probe_sites(source: str) -> int:
    """Count argv-shaped sites (list/tuple literals, call arguments) holding both "auth" and
    "token" as string elements. Layout-insensitive: it walks the AST, so one element per line
    or a reformatted literal counts the same."""
    def strs(nodes):
        return {n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)}

    count = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.List, ast.Tuple)):
            elts = strs(node.elts)
        elif isinstance(node, ast.Call):
            elts = strs(node.args)
        else:
            continue
        count += {"auth", "token"} <= elts
    return count


def test_the_probe_counter_ignores_layout():
    one_line = 'run(["gh", "auth", "token", "--user", a])'
    per_line = 'run([\n    "gh",\n    "auth",\n    "token",\n    "--user",\n    a,\n])'
    call_form = 'run("gh", "auth", "token")'
    assert [_probe_sites(x) for x in (one_line, per_line, call_form)] == [1, 1, 1], \
        "the token-probe site counter must not depend on source layout"


def test_the_token_probe_argv_is_written_once_in_the_core():
    shim_sites = _probe_sites(Path(gpa.__file__).read_text(encoding="utf-8"))
    core_sites = _probe_sites(Path(ai.__file__).read_text(encoding="utf-8"))
    assert (shim_sites, core_sites) == (0, 1), (
        f"`gh auth token` argv must be written once, in the core: "
        f"pr-author shim={shim_sites}, automation_identity={core_sites}")


def test_create_pr_builds_its_bot_env_through_the_core(monkeypatch):
    built: list = []

    def account_env(account, base_env=None, token_runner=None):
        built.append((account, dict(base_env or {})))
        return {"GH_TOKEN": "from-core"}

    monkeypatch.setattr(ai, "account_env", account_env)
    calls: list = []

    def create(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    rc = gpa.create_pr(["--base", "master"], CFG, "manual", runner=create, env={"PATH": "/bin"})
    assert rc == 0 and built == [("CurtisTheBot", {"PATH": "/bin"})]
    assert calls[0][1]["env"] == {"GH_TOKEN": "from-core"}
