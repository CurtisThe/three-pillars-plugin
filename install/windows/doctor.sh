#!/usr/bin/env bash
# doctor.sh: measure how complete a three-pillars Windows workstation is.
# Run in the Ubuntu WSL2 terminal: bash ~/three-pillars-install/doctor.sh --profile <profile>
# Prints one line per item (ok|red|skip <id>[: detail]), then a fenced summary
# repeating them, ready to paste into the Notion task. Read-only; safe to re-run.
#   --profile desktop|terminal|both   which checklist to measure (required)
#   --forge github|other              which forge hosts the packages [github]; other
#                                     makes no gh call and prints a visible skip
#   --list-items                      print "<id><TAB><label>" rows, run no check
# Exit codes: 0 no item is red (skips do not block), 1 any red, 2 usage error.
# Test seams (environment, defaults in brackets):
#   WWB_PROC_VERSION  file read for the WSL2 check [/proc/version]
#   WWB_WIN_MOUNT     where Windows drives mount [/mnt/c]
#   WWB_WIN_HOME      Windows profile as a Linux path [wslpath of cmd.exe /c
#                     'echo %USERPROFILE%' with \r stripped; empty if either is missing]
set -u

PROC_VERSION=${WWB_PROC_VERSION:-/proc/version}
WIN_MOUNT=${WWB_WIN_MOUNT:-/mnt/c}
PKG_OWNER=CurtisThe

# id|profiles|label, in output order.
ITEMS=(
  'wsl2|desktop,terminal|WSL2 distro'
  'repos-ext4|desktop,terminal|Repos on the Linux disk'
  'tmux|terminal|tmux'
  'gh-auth|desktop,terminal|GitHub login'
  'node|desktop,terminal|Node LTS'
  'claude|desktop,terminal|Claude Code'
  'three-pillars|desktop,terminal|three-pillars plugin'
  'notion-ops|desktop,terminal|notion-ops skills'
  'wiki-ops|desktop,terminal|wiki-ops skills'
  'wt-seat-profile|terminal|Windows Terminal seat profile'
  'desktop-app|desktop|Claude Desktop'
  'notifications|desktop,terminal|Ready-for-input notifications'
  'wiki-vault|desktop,terminal|Wiki vault'
  'notion-config|desktop,terminal|Notion config'
)

usage() { echo "usage: doctor.sh [--list-items] [--forge github|other] --profile desktop|terminal|both" >&2; exit 2; }

PROFILE=""
FORGE=github
LIST=0
while [ $# -gt 0 ]; do
  case $1 in
    --profile) [ $# -ge 2 ] || usage; PROFILE=$2; shift 2 ;;
    --forge) [ $# -ge 2 ] || usage; FORGE=$2; shift 2 ;;
    --list-items) LIST=1; shift ;;
    *) usage ;;
  esac
done
case $PROFILE in desktop | terminal | both) ;; *) usage ;; esac
case $FORGE in github | other) ;; *) usage ;; esac

windows_home() {
  local raw
  if command -v cmd.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
    raw=$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')
    [ -n "$raw" ] && wslpath "$raw" 2>/dev/null
  fi
  return 0
}
if [ -z "${WWB_WIN_HOME+x}" ]; then WIN_HOME=$(windows_home); else WIN_HOME=$WWB_WIN_HOME; fi

OK=0 RED=0 SKIP=0 BUF=()
emit() { # status id [detail]
  local line="$1 $2"
  [ -n "${3:-}" ] && line="$line: $3"
  printf '%s\n' "$line"
  BUF+=("$line")
  case $1 in ok) OK=$((OK + 1)) ;; red) RED=$((RED + 1)) ;; *) SKIP=$((SKIP + 1)) ;; esac
}

applies() { # profiles-csv: does the chosen profile use this row
  [ "$PROFILE" = both ] && return 0
  case ",$1," in *",$PROFILE,"*) return 0 ;; esac
  return 1
}

check_wsl2() {
  local v
  v=$(cat "$PROC_VERSION" 2>/dev/null)
  if printf '%s' "$v" | grep -qi microsoft && printf '%s' "$v" | grep -q WSL2; then
    emit ok wsl2
  else
    emit red wsl2 "WSL2 is not running: re-run Stage 0"
  fi
}

check_repos_ext4() { # reports repos on the Windows drive; never moves them
  local mount_real g p real list=""
  mount_real=$(realpath "$WIN_MOUNT" 2>/dev/null || printf '%s' "$WIN_MOUNT")
  while IFS= read -r g; do
    p=${g%/.git}
    real=$(realpath "$p" 2>/dev/null) || continue
    case "$real/" in "$mount_real"/*) list="${list:+$list, }$p" ;; esac
  done < <(
    find -L "$HOME" -maxdepth 3 -path "$HOME/.*" -prune -o -name .git -print 2>/dev/null
    if [ -n "$WIN_HOME" ] && [ -d "$WIN_HOME" ]; then
      find "$WIN_HOME" -maxdepth 3 -name .git -print 2>/dev/null
    fi
  )
  if [ -n "$list" ]; then
    emit red repos-ext4 "$list on the Windows drive: move it to ~/"
  else
    emit ok repos-ext4
  fi
}

check_tmux() { if command -v tmux >/dev/null 2>&1; then emit ok tmux; else emit red tmux "install tmux"; fi; }

check_node() {
  local v major
  if ! command -v node >/dev/null 2>&1; then emit red node "install Node LTS"; return; fi
  v=$(node --version 2>/dev/null)
  v=${v#v}
  major=${v%%.*}
  case $major in '' | *[!0-9]*) emit red node "install Node LTS: version unreadable"; return ;; esac
  if [ "$major" -ge 20 ]; then emit ok node "v$v"; else emit red node "install Node LTS: found v$v"; fi
}

check_claude() { if claude --version >/dev/null 2>&1; then emit ok claude; else emit red claude "install Claude Code"; fi; }

check_gh_auth() {
  if [ "$FORGE" = other ]; then
    emit skip gh-auth "forge is not GitHub"
  elif gh auth status >/dev/null 2>&1; then
    emit ok gh-auth
  else
    emit red gh-auth "run gh auth login (device code): the private plugins need it"
  fi
}

# Read the person's own JSON: mode "plugin" = a plugins key starts with "<name>@",
# mode "hook" = hooks.Notification is a non-empty list. Missing or unreadable = no.
json_has() { # mode file [name]
  python3 -I -c '
import json, sys
mode, path, name = sys.argv[1:4]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if mode == "plugin":
        found = any(k.startswith(name + "@") for k in data["plugins"])
    else:
        hooks = data["hooks"]["Notification"]
        found = isinstance(hooks, list) and len(hooks) > 0
except Exception:
    found = False
sys.exit(0 if found else 1)
' "$1" "$2" "${3:-}" 2>/dev/null
}
plugin_present() { json_has plugin "$HOME/.claude/plugins/installed_plugins.json" "$1"; }
can_read() { gh repo view "$PKG_OWNER/$1" >/dev/null 2>&1; }
gh_logged_in() { gh auth status >/dev/null 2>&1; }
NO_LOGIN="log in to GitHub first (gh auth login): private plugins need it"
NO_ACCESS="no read access: accept the GitHub invite at github.com/notifications, or ask the operator for access"

check_three_pillars() {
  if [ "$PROFILE" = desktop ]; then
    if plugin_present three-pillars || plugin_present three-pillars-pro; then emit ok three-pillars
    else emit red three-pillars "not installed: follow the README packages step"; fi
  elif plugin_present three-pillars-pro; then
    emit ok three-pillars
  elif [ "$FORGE" = other ]; then
    emit red three-pillars "install the pro build"
  elif ! gh_logged_in; then
    emit red three-pillars "$NO_LOGIN"
  elif ! can_read three-pillars-pro; then
    emit red three-pillars "$NO_ACCESS"
  else
    emit red three-pillars "install the pro build after gh login"
  fi
}

check_package() { # id plugin-and-repo-name
  if plugin_present "$2"; then
    emit ok "$1"
  elif [ "$FORGE" = other ]; then
    emit skip "$1" "forge is not GitHub, package access checked by clone only"
  elif ! gh_logged_in; then
    emit red "$1" "$NO_LOGIN"
  elif ! can_read "$2"; then
    emit red "$1" "$NO_ACCESS"
  else
    emit red "$1" "not installed: follow the README packages step"
  fi
}
check_notion_ops() { check_package notion-ops notion-ops-skills; }
check_wiki_ops() { check_package wiki-ops wiki-ops-skills; }

check_wt_seat_profile() { # a text check: Windows Terminal JSON allows comments
  local base="$WIN_HOME/AppData/Local"
  if [ -z "$WIN_HOME" ]; then emit red wt-seat-profile "cannot see the Windows home"; return; fi
  if grep -qs '"commandline".*tmux' "$base/Microsoft/Windows Terminal/Fragments/three-pillars/seat.json" \
    "$base/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json"; then
    emit ok wt-seat-profile
  else
    emit red wt-seat-profile "no seat profile: follow the README Windows Terminal step"
  fi
}

check_desktop_app() {
  if [ -z "$WIN_HOME" ]; then emit red desktop-app "cannot see the Windows home"
  elif [ -d "$WIN_HOME/AppData/Local/AnthropicClaude" ]; then emit ok desktop-app
  else emit red desktop-app "install Claude Desktop: follow the README desktop step"; fi
}

check_notifications() {
  if json_has hook "$HOME/.claude/settings.json"; then
    emit ok notifications
  else
    emit red notifications "no Notification hook: follow the README notifications step"
  fi
}

check_wiki_vault() { # a dir at depth <= 2 holding both Raw/ and Wiki/
  local d
  while IFS= read -r d; do
    if [ -d "${d%/Raw}/Wiki" ]; then emit ok wiki-vault; return; fi
  done < <(find "$HOME" -mindepth 1 -maxdepth 3 -name '.*' -prune -o -type d -name Raw -print 2>/dev/null)
  emit red wiki-vault "no vault found: run /wiki-init"
}

check_notion_config() {
  if [ -n "$(find "$HOME" -mindepth 1 -maxdepth 3 -name '.*' -prune -o -name notion-config.yaml -print -quit 2>/dev/null)" ]; then
    emit ok notion-config
  else
    emit red notion-config "no notion-config.yaml: run /notion-scaffold-teamspace"
  fi
}

for row in "${ITEMS[@]}"; do
  id=${row%%|*}
  rest=${row#*|}
  profiles=${rest%%|*}
  label=${rest#*|}
  if applies "$profiles"; then
    if [ "$LIST" = 1 ]; then printf '%s\t%s\n' "$id" "$label"; else "check_${id//-/_}"; fi
  elif [ "$LIST" = 0 ]; then
    emit skip "$id" "not used by the $PROFILE profile"
  fi
done
[ "$LIST" = 1 ] && exit 0

echo '```text'
echo "three-pillars doctor | profile=$PROFILE | ok=$OK red=$RED skip=$SKIP"
printf '%s\n' "${BUF[@]}"
echo '```'
[ "$RED" -eq 0 ]
