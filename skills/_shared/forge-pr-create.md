# Opening a PR through the forge chokepoint

The shared caller recipe for `/tp-design-complete` (step 6g, `--context manual`) and
`/tp-run-full-design` Tier 6 (`--context autonomous`). Both open the completion PR
through one entry point, `skills/_shared/forge.py` (dispatch in `forge_cli.py`), so no
caller names a forge host. On a GitHub origin `forge.py` hands the args after `--` to
`skills/_shared/github_pr_author.py create` untouched, so for a `github.com` origin (or
`forge.kind: github`) the GitHub path is byte-identical to before (optional bot author,
plain `gh pr create` when unconfigured).

## Resolve

Git-toplevel-first, per `skills/_shared/first-run.md` §Resolve a FREE _shared script:

```bash
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
FORGE="$(python3 "$RS" forge.py)" || exit 1
[ -n "$FORGE" ] || exit 1
python3 "$FORGE" pr-create --context manual|autonomous -- --base … --head … --title … --body …
```

## Exit codes

| Exit | Meaning | Caller does |
|---|---|---|
| 0 | PR opened (or updated) | stdout is the PR URL; report it |
| 3 | `bot-auth-unavailable` (GitHub only) | surface the stderr; never retry with ambient auth |
| 4 | `forge-degraded` | print the stdout compare URL (empty on an unsupported forge; the stderr line explains) |
| 2 / other | usage error or `gh pr create` failure | log `gh-pr-create-failed`, print `python3 "$FORGE" compare-url --base <base> --head <branch>` |

Exit 3 stays distinct from `gh-pr-create-failed`: a misconfigured bot must never be
conflated with a benign network failure. The compare URL always comes from
`python3 "$FORGE" compare-url`, never from a hand-built host literal.

## GitHub origin

- Precondition: `gh auth status` returns 0; otherwise skip the PR and print the compare URL.
- Copilot review is requested through the REST `requested_reviewers` endpoint
  (`gh api repos/{owner}/{repo}/pulls/{n}/requested_reviewers`), never `gh pr edit --add-reviewer`.
- Tier 7 (`/tp-pr-iterate`) runs as before.

## Gitea or other origin

- No `gh auth status` precondition: `forge.py` uses a Gitea token when one is found,
  and otherwise opens the PR with an AGit push (`refs/for/<base>`), which needs only an SSH key.
- Token setup (optional, enables the REST path):
  `export GITEA_TOKEN=…` or `tea login add --url <web_base>`.
- When `python3 "$FORGE" resolve` reports reason `no web base`: if this is a Gitea, set
  `forge.web_base` in `.three-pillars/config.json`, e.g. `https://<host>:<port>`; for a
  GitHub ssh alias or GitHub Enterprise host, set `forge.kind: github`
  (or set `forge.kind: other` to silence this). An ssh alias that `ssh -G` resolves to
  `github.com` is detected as GitHub on its own.
- **Re-push step (AGit PRs).** After any later push to `tp/<branch>`, re-run
  `python3 "$FORGE" pr-create` with the same args. It re-pushes `refs/for/<base>` with the
  same topic and updates the same PR; the `ok` note on stderr says so. No branch delete.
- The Copilot `requested_reviewers` request is skipped: log decisions token
  `review-request-skipped-non-github`, and continue (fail-open).
- Tier 7 is skipped: log `forge-no-iterate`. PR-iterate on Gitea stays in the
  `gitea-forge-adapter` design.
