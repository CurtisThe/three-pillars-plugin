# Matchable commands

Permission rules match literal command text. A command built from a wrapper, a variable or a `cd`
cannot match any allow rule, so an unattended run stalls ("could not be checked") or the auto-mode
classifier blocks it. Write every Bash call in one of the forms below.

| Instead of | Write |
|---|---|
| `bash -c "…"`, `sh -c "…"`, `nohup bash -c …` | One script call: `python3 "$TP_ROOT"/skills/_shared/child_spawn.py …`. To run something in the background, start a child with `python3 "$TP_ROOT"/skills/_shared/child_spawn.py start …` (see [`child-spawn.md`](child-spawn.md)), or set `run_in_background` on the Bash tool call. Never wrap the command in a shell. |
| `cd <dir> && git …` | `git -C <dir> …` |
| `cd <dir> && pytest …` | From the repo root: `python3 -m pytest <paths> -q -n 4`. |
| `WT=…; git worktree add $WT …; git worktree remove --force $WT` | `python3 "$TP_ROOT"/skills/_shared/scratch_worktree.py add <name> [<ref>]`, then `… run <name> -- <cmd…>`, then `… remove <name>`. |
| `S=skills/_shared; python3 $S/resolve_script.py` | The literal path: `python3 "$TP_ROOT"/skills/_shared/resolve_script.py`. The one sanctioned prefix is the quoted `"$TP_ROOT"` (it resolves to the framework root in this repo and in a consumer repo). |
| `export TP_ROOT=$PWD && python3 …` | Drop the prefix. Scripts resolve their own root. |

## Scratch worktrees

A "compare against master" check, a Tier 7 regen or a base-sync compare needs a second checkout. Do not
hand-build one (`~/t/master-check`, `.tp-scratch/base-check`, `r2-regen`). `scratch_worktree.py`
keeps every one at `<repo>/.tp-scratch/scratch-<name>`:

```
python3 "$TP_ROOT"/skills/_shared/scratch_worktree.py add base-check origin/master
python3 "$TP_ROOT"/skills/_shared/scratch_worktree.py run base-check -- python3 -m pytest skills/_shared/test_scratch_worktree.py -q -n 4
python3 "$TP_ROOT"/skills/_shared/scratch_worktree.py remove base-check
```

`run` sets the working directory itself, so there is no `cd`. `remove` refuses any path outside the scratch
root and any directory git does not list as a worktree. `add` refuses when `.tp-scratch/` is not
gitignored (it prints one line saying so). One allow rule covers all three calls:
`Bash(python3 "$TP_ROOT"/skills/_shared/scratch_worktree.py *)`.

## Advisory scan

`python3 "$TP_ROOT"/skills/_shared/command_shape_scan.py` lists any `bash -c` / `sh -c` / `nohup`, `cd … && git|pytest`,
`$VAR/x.py` and `export TP_ROOT=… &&` shapes left in shipped prose. It always exits 0. Mark a deliberate
example with `matchable: ok` on its line.
