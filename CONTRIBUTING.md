# Contributing

This repository is a **release artifact**, not a source of truth. It is regenerated from a private dev repo by `release.sh`, which rsyncs an allowlist of files (`skills/`, `agents/`, `.claude-plugin/`, `CLAUDE.md`, `settings.json`, etc.) into this directory.

**Direct edits to this repo will be overwritten on the next release.**

## How to contribute changes

Open an issue or pull request describing the change you want to see. The maintainer will:
1. Apply the change in the upstream dev repo.
2. Run `./release.sh ~/three-pillars-plugin` from the dev repo, which regenerates the files here.
3. Commit and push the regenerated state.

Pull requests against this repo are welcome as a **proposal mechanism** — the maintainer will mirror accepted changes upstream and re-release. The PR itself will not be merged directly, because the next release would discard it.

## What lives where

| In this (release) repo | In the dev repo |
|---|---|
| Distributable plugin files (skills, agents, CLAUDE.md, settings.json, …) | Source of truth for everything above |
| `README.md` (generated from dev's `README.plugin.md`) | `README.md` (dev workspace), `README.plugin.md` (release source) |
| `CLAUDE.md` (generated from dev's `CLAUDE.plugin.md`) | `CLAUDE.md` (dev workspace), `CLAUDE.plugin.md` (release source) |
| `CONTRIBUTING.md` (this file — synced from dev) | Same content, edited there |
| Nothing else | Project docs, design artifacts, dev tooling, tests, `release.sh` |

## License

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
