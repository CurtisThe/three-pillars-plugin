# Privacy Policy — Three Pillars Plugin

**Last updated:** 2026-04-08

## Overview

The Three Pillars plugin for Claude Code is a collection of local skill definitions and agent definitions. It operates within your Claude Code session and makes no plugin-specific outbound connections. Council agents use Claude Code's built-in web search for research during deliberation (see Data Collection below).

## Data Collection

This plugin does not collect, transmit, or store any user data. Specifically:

- **No plugin-initiated network requests**: The plugin makes no outbound connections of its own — no APIs, webhooks, or telemetry endpoints. Council agents have `WebSearch` and `WebFetch` in their tool lists for research during deliberation; these use Claude Code's built-in web access (the same capability available in vanilla Claude Code) and are subject to your organization's Claude Code permission policies.
- **No analytics or telemetry**: No usage tracking, metrics, or telemetry of any kind.
- **No external services**: The plugin does not integrate with or send data to any external service, API, or server. Web search during council deliberation uses Claude Code's native web access, not a plugin-specific integration.
- **No cookies or local storage**: The plugin does not use browser cookies, local storage, or any persistent tracking mechanism beyond what Claude Code itself provides.

## Local Files

The plugin's skills may create or modify files within your project directory as part of normal operation (e.g., design documents in `docs/tdd-designs/`, a `.claude/last-design` tracking file). These files remain entirely on your local filesystem.

## Third-Party Dependencies

This plugin has no runtime dependencies (no npm packages, pip packages, or external libraries). It consists solely of markdown instruction files and shell scripts. The council agent personas are adapted from [Council of High Intelligence](https://github.com/0xNyk/council-of-high-intelligence) (MIT-licensed), vendored as markdown files. See THIRD-PARTY-NOTICES for details.

## Changes to This Policy

If this policy changes, the updated version will be published in the plugin's GitHub repository.

## Contact

For questions about this privacy policy, open an issue at https://github.com/CurtisThe/three-pillars-plugin/issues.
