"""Test-only fixture: the env a real launcher leaves a session (no logic).

Captured 2026-10-15 by running the launcher's own `python3 -I lib/launcher/plan.py` read-only in
a scratch directory from `env -i` with only HOME, PATH and TERM, with and without
`CLAUDE_LAUNCHER_ROLE=run`, then applying its `U:`/`E:` records. A real session never holds
`CLAUDE_LAUNCHER_ROLE` or `CLAUDE_LAUNCHER_FORCE_BACKEND`.
"""
_SETTINGS = "/home/curtis/.local/state/claude-launcher/run/settings-a3823c6b.json"

DIRECT_EXPORT = {
    "CLAUDE_CONFIG_DIR": "/home/curtis/.claude-profiles/personal",
    "CLAUDE_LAUNCHER_BACKEND": "direct",
    "CLAUDE_LAUNCHER_TOOLSET": "default",
    "CLAUDE_LAUNCHER_SETTINGS": _SETTINGS,
    "CLAUDE_LAUNCHER_HARNESS_CPUS": "4-7,12-15,20-23,28-31",
    "PYTEST_XDIST_AUTO_NUM_WORKERS": "4",
    "TP_LOCAL": "off",
    "CLAUDE_LAUNCHER_OWNED": (
        "CLAUDE_CONFIG_DIR CLAUDE_LAUNCHER_BACKEND CLAUDE_LAUNCHER_TOOLSET "
        "CLAUDE_LAUNCHER_SETTINGS CLAUDE_LAUNCHER_HARNESS_CPUS "
        "PYTEST_XDIST_AUTO_NUM_WORKERS TP_LOCAL CLAUDE_LAUNCHER_OWNED"),
}

HYBRID_EXPORT = {
    "CLAUDE_CONFIG_DIR": "/home/curtis/.claude-profiles/personal",
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:3457",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "strata",
    "ENABLE_TOOL_SEARCH": "true",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000",
    "CLAUDE_LAUNCHER_BACKEND": "hybrid",
    "CLAUDE_LAUNCHER_TOOLSET": "default",
    "CLAUDE_LAUNCHER_SETTINGS": _SETTINGS,
    "CLAUDE_LAUNCHER_HARNESS_CPUS": "4-7,12-15,20-23,28-31",
    "PYTEST_XDIST_AUTO_NUM_WORKERS": "4",
    "TP_LOCAL": "off",
    "CLAUDE_LAUNCHER_OWNED": (
        "CLAUDE_CONFIG_DIR ANTHROPIC_BASE_URL ANTHROPIC_DEFAULT_HAIKU_MODEL ENABLE_TOOL_SEARCH "
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW CLAUDE_LAUNCHER_BACKEND CLAUDE_LAUNCHER_TOOLSET "
        "CLAUDE_LAUNCHER_SETTINGS CLAUDE_LAUNCHER_HARNESS_CPUS PYTEST_XDIST_AUTO_NUM_WORKERS "
        "TP_LOCAL CLAUDE_LAUNCHER_OWNED"),
}
