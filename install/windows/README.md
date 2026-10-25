# three-pillars Windows workstation, Stage 1 (written for Claude Code)

You are Claude Code inside Ubuntu on WSL2, opened by Stage 0 in `~/three-pillars-install/`. Follow this file to finish the machine. The person is not a developer: plain words, one thing at a time.

## Rules

1. Ask the person their profile (`desktop`, `terminal` or `both`) unless they said. Call it `<p>`.
2. Run `bash ~/three-pillars-install/doctor.sh --profile <p>` first and again after every step. It prints `ok`, `red` or `skip` per item. Skip any step whose doctor line is `ok` or `skip`. The doctor is the resume check: there is no state file. Do the steps in order; a `STEP doctor=<id>` block fixes the doctor item of that id.
3. A `PAUSE id=<id>` block is something only the person can do. Say exactly the clicks it lists, then stop, wait until they say it is done, and re-run the doctor. Never do it for them.
4. Never move, copy or delete a repo. Never change Group Policy or any security setting. On a result saying `needs IT`, stop and tell the person to send that line to their IT team as it is.
5. `sudo` asks for the person's Ubuntu password. They type it; you never see or keep it. A line typed in this window with a leading `!` runs as them.
6. Another forge (Gitea and others): clone with the person's own forge credentials, run the doctor with `--forge other`, and skip the `gh` steps.
7. Plugins load when a session starts. After a plugin step, run slash commands in a new `claude` session started from the folder the step names.
8. If a step fails twice, tell the person to paste the doctor's last block as a comment on their Notion task and mention the operator named there. When no doctor line is `red`, say the machine is ready and post the block the same way.

<!-- STEP doctor=wsl2 -->
**WSL2 distro.** Report only. If `red`, this is not WSL2 Ubuntu: the person re-runs the Stage 0 script from their Notion task.

<!-- PAUSE id=admin-reboot -->
**PAUSE admin-reboot** (only if Stage 0 has not finished). Tell the person: right-click Start, choose Terminal (Admin) or Windows PowerShell (Admin), paste the Stage 0 script and press Enter. Click Yes on the permission prompt. The script asks you to restart: restart Windows yourself, then sign back in and the script carries on. If no PowerShell window opens within a minute of signing in, open PowerShell as administrator and paste the Stage 0 script again (it is safe to run again). Then stop, wait, re-run the doctor.

<!-- PAUSE id=bios-virtualization -->
**PAUSE bios-virtualization** (only if Stage 0 said CPU virtualization is off). Tell the person: restart into the BIOS or UEFI settings (the key shows at power-on, often F2, Del or F10), switch on Intel VT-x or AMD SVM, save, boot Windows, then run the Stage 0 script again. Then stop, wait, re-run the doctor.

<!-- STEP doctor=repos-ext4 -->
**Repos on the Linux disk.** Report only. If `red`, name each repo on the Windows drive (`/mnt/c`) and say it belongs under `~/`. Never move it yourself.

<!-- STEP doctor=tmux -->
**tmux** (the `desktop` profile skips it): `sudo apt-get update && sudo apt-get install -y tmux`.

<!-- STEP doctor=gh-auth -->
**GitHub login.** This login is what unlocks the private plugins (notion-ops, wiki-ops, and the three-pillars pro build for `terminal`). Every package step below needs it, under the GitHub account the operator invited.

```bash
sudo apt-get update && sudo apt-get install -y gh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
```

<!-- PAUSE id=gh-login -->
**PAUSE gh-login.** `gh` prints a short code and a web address. Tell the person: open the address, type the code, sign in to GitHub with the account whose invites you accepted, and approve. The code works once and expires after a few minutes. Then stop, wait, re-run the doctor.

<!-- PAUSE id=github-access -->
**PAUSE github-access** (only if a package line says `no read access`). Run `gh api user -q .login` and tell the person which account they are logged in as. Tell them: open github.com/notifications signed in as that account (or the invite emails from GitHub) and accept every invite to a `CurtisThe` repository. No invite there? Post that username as a comment on your Notion task and mention the operator, then wait for the invite. A different account than the invited one: run `gh auth login` again with the right one. Then stop, wait, re-run the doctor.

<!-- STEP doctor=node -->
**Node LTS.**

```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs
```

<!-- STEP doctor=claude -->
**Claude Code.** Stage 0 installed it. If `claude --version` fails, run `curl -fsSL https://claude.ai/install.sh | bash` and open a new Ubuntu window.

<!-- PAUSE id=claude-login -->
**PAUSE claude-login** (only if Claude Code asks to sign in). Tell the person: choose your Claude account, approve in the browser tab that opens, then come back to this window. Then stop, wait, re-run the doctor.

<!-- STEP doctor=three-pillars -->
**three-pillars plugin.** `desktop`: the public build. The marketplace is named after the build's plugin name, not the repo.

```bash
claude plugin marketplace add CurtisThe/three-pillars-plugin
claude plugin install three-pillars@three-pillars
```

`terminal` or `both`, after the `gh` login: the pro build, which carries the fleet and worktree commands. It already contains the public build, so uninstall `three-pillars@three-pillars` first if it is listed.

```bash
claude plugin marketplace add CurtisThe/three-pillars-pro
claude plugin install three-pillars-pro@three-pillars-pro
```

If access is refused, tell the person to ask the operator for access. On another forge, clone the pro build from it and add the marketplace from the clone path.

<!-- PAUSE id=max-plan -->
**PAUSE max-plan** (`terminal` or `both`). Tell the person: in your Claude account open Settings, then Plans and billing, and check you are on a Max plan, which running several designs side by side needs. If not, tell the operator. Then stop, wait, re-run the doctor.

<!-- STEP doctor=notion-ops -->
**notion-ops skills.** Private package, repo `notion-ops-skills`. Needs the `gh` login.

```bash
gh repo clone CurtisThe/notion-ops-skills ~/notion-ops-skills
claude plugin marketplace add ~/notion-ops-skills
claude plugin install <plugin>@<marketplace>
```

Read `<marketplace>` (its `name`) and `<plugin>` (each of its `plugins[].name`) from `~/notion-ops-skills/.claude-plugin/marketplace.json`. Never assume they equal the repo name. A clone refused for access: tell the person to ask the operator for access.

<!-- STEP doctor=wiki-ops -->
**wiki-ops skills.** The same three commands, with the repo `wiki-ops-skills` in place of `notion-ops-skills`: clone it, add the clone as a marketplace, install the plugin by the names in its `marketplace.json`. Access refused: ask the operator for access.

<!-- STEP doctor=wt-seat-profile -->
**Windows Terminal seat profile** (`terminal` only). Write a fragment holding a profile that opens the seat in tmux. Keep the `commandline` on one line: the doctor reads it as text.

```bash
DIR="$(wslpath "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')")/AppData/Local/Microsoft/Windows Terminal/Fragments/three-pillars"
mkdir -p "$DIR"
printf '%s\n' '{"profiles": [{"name": "three-pillars seat", "commandline": "wsl.exe -d Ubuntu-24.04 -- tmux new -A -s seat"}]}' > "$DIR/seat.json"
```

<!-- PAUSE id=seat-start -->
**PAUSE seat-start** (`terminal`). Tell the person: close and reopen Windows Terminal, click the drop-down arrow next to the tab, pick `three-pillars seat` and press Enter. They land in a tmux seat, the tabbed workspace where fleet work runs. Leave it open. Then stop, wait, re-run the doctor.

<!-- STEP doctor=desktop-app -->
**Claude Desktop** (`desktop` only). If `red`, the person installs Claude Desktop from claude.ai/download. Write no app configuration.

<!-- PAUSE id=desktop-wsl -->
**PAUSE desktop-wsl** (`desktop`). Tell the person: in Claude Desktop open the Code tab and choose to work in WSL (Ubuntu), not on Windows. Then open the Code tab's **+** menu, choose **Plugins**, and check that three-pillars, notion-ops and wiki-ops are listed. If any is missing, they comment on their Notion task and mention the operator: whether the Code tab sees plugins installed in WSL is not verified yet. Then stop, wait, re-run the doctor.

<!-- STEP doctor=notifications -->
**Ready-for-input notifications.** A `Notification` hook runs a script that shows a Windows balloon through `powershell.exe`. Nothing in it is personal.

```bash
mkdir -p ~/.claude/hooks
cat > ~/.claude/hooks/notify.sh <<'EOF'
#!/usr/bin/env bash
powershell.exe -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms, System.Drawing; \$n = New-Object System.Windows.Forms.NotifyIcon; \$n.Icon = [System.Drawing.SystemIcons]::Information; \$n.Visible = \$true; \$n.ShowBalloonTip(5000, 'Claude Code', 'Ready for input', 'Info'); Start-Sleep -Seconds 6; \$n.Dispose()" >/dev/null 2>&1 &
EOF
chmod +x ~/.claude/hooks/notify.sh
python3 - <<'EOF'
import json, pathlib
home = pathlib.Path.home()
path = home / ".claude" / "settings.json"
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
hook = {"hooks": [{"type": "command", "command": str(home / ".claude/hooks/notify.sh")}]}
data.setdefault("hooks", {}).setdefault("Notification", []).append(hook)
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
EOF
```

<!-- STEP doctor=wiki-vault -->
**Wiki vault.** `mkdir -p ~/wiki && cd ~/wiki && claude 'Run /wiki-init, then follow ~/three-pillars-install/README.md from the top.'`

<!-- STEP doctor=notion-config -->
**Notion config.** Do the two PAUSE blocks below first, then run `/notion-scaffold-teamspace` in a new session started from `~/work`: `mkdir -p ~/work && cd ~/work && claude 'Run /notion-scaffold-teamspace, then follow ~/three-pillars-install/README.md from the top.'`

<!-- PAUSE id=connectors -->
**PAUSE connectors.** Tell the person: in a browser open claude.ai, go to Settings, then Connectors, and connect Notion and Google. Approve each permission screen. Then stop, wait, re-run the doctor.

<!-- PAUSE id=notion-invite -->
**PAUSE notion-invite.** Tell the person: accept the Notion workspace invite sent to you, so the team space shows in your Notion sidebar. Check it shows before you scaffold. Then stop, wait, re-run the doctor.
