#!/usr/bin/env bash
set -u
# Maximum-detail Claude Code status line
# Shows: model, git branch, context usage bar, tokens, cost, duration, API time,
#        code changes, cache stats, rate limits, agent/worktree info

input=$(cat)
field() { echo "$input" | jq -r "$1 // empty" 2>/dev/null; }

# --- Gather all data ---
MODEL=$(field '.model.display_name')
CWD=$(field '.workspace.current_dir')
VERSION=$(field '.version')
SESSION=$(field '.session_id')

# Context window
USED_PCT=$(field '.context_window.used_percentage')
CTX_SIZE=$(field '.context_window.context_window_size')
TOTAL_IN=$(field '.context_window.total_input_tokens')
TOTAL_OUT=$(field '.context_window.total_output_tokens')
CUR_IN=$(field '.context_window.current_usage.input_tokens')
CUR_OUT=$(field '.context_window.current_usage.output_tokens')
CACHE_WRITE=$(field '.context_window.current_usage.cache_creation_input_tokens')
CACHE_READ=$(field '.context_window.current_usage.cache_read_input_tokens')
EXCEEDS_200K=$(field '.exceeds_200k_tokens')

# Cost & duration
COST=$(field '.cost.total_cost_usd')
DURATION_MS=$(field '.cost.total_duration_ms')
API_MS=$(field '.cost.total_api_duration_ms')
LINES_ADD=$(field '.cost.total_lines_added')
LINES_DEL=$(field '.cost.total_lines_removed')

# Rate limits
RL5H=$(field '.rate_limits.five_hour.used_percentage')
RL7D=$(field '.rate_limits.seven_day.used_percentage')

# Optional fields
VIM_MODE=$(field '.vim.mode')
AGENT_NAME=$(field '.agent.name')
WT_NAME=$(field '.worktree.name')
WT_BRANCH=$(field '.worktree.branch')

# --- Colors ---
RST='\033[0m'
DIM='\033[2m'
GRN='\033[32m'
YEL='\033[33m'
BLU='\033[34m'
MAG='\033[35m'
CYN='\033[36m'
BRED='\033[1;31m'
BGRN='\033[1;32m'
BYEL='\033[1;33m'
BCYN='\033[1;36m'
BMAG='\033[1;35m'

# --- Helpers ---
fmt_tokens() {
  local t="${1:-0}"
  if [ "$t" -ge 1000000 ] 2>/dev/null; then
    printf "%.1fM" "$(echo "$t" | awk '{printf "%.1f", $1/1000000}')"
  elif [ "$t" -ge 1000 ] 2>/dev/null; then
    printf "%.1fk" "$(echo "$t" | awk '{printf "%.1f", $1/1000}')"
  else
    printf "%s" "${t:-0}"
  fi
}

fmt_ms() {
  local ms="${1:-0}"
  local total_s=$((ms / 1000))
  local h=$((total_s / 3600))
  local m=$(((total_s % 3600) / 60))
  local s=$((total_s % 60))
  if [ "$h" -gt 0 ] 2>/dev/null; then
    printf "%dh%02dm%02ds" "$h" "$m" "$s"
  elif [ "$m" -gt 0 ] 2>/dev/null; then
    printf "%dm%02ds" "$m" "$s"
  else
    printf "%ds" "$s"
  fi
}

progress_bar() {
  local pct="${1:-0}"
  local width=20
  pct=$(printf '%.0f' "$pct" 2>/dev/null || echo 0)
  local filled=$(( (pct * width + 50) / 100 ))
  [ "$filled" -gt "$width" ] && filled=$width
  [ "$filled" -lt 0 ] && filled=0
  local empty=$((width - filled))
  local bar=""
  local color="$GRN"
  [ "$pct" -ge 50 ] && color="$YEL"
  [ "$pct" -ge 75 ] && color="$BYEL"
  [ "$pct" -ge 90 ] && color="$BRED"
  bar="${color}"
  for ((i=0; i<filled; i++)); do bar+="█"; done
  bar+="${DIM}"
  for ((i=0; i<empty; i++)); do bar+="░"; done
  bar+="${RST}"
  printf "%b" "$bar"
}

# --- Git info ---
BRANCH=""
DIRTY=""
if [ -n "$CWD" ] && git -C "$CWD" --no-optional-locks rev-parse --git-dir >/dev/null 2>&1; then
  BRANCH=$(git -C "$CWD" --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [ -n "$(git -C "$CWD" --no-optional-locks status --porcelain 2>/dev/null | head -1)" ]; then
    DIRTY="*"
  fi
fi

# =====================================================================
# LINE 1: Model | Git | Agent/Worktree | Context bar + percentage
# =====================================================================
L1=""

# Model badge
if [ -n "$MODEL" ]; then
  L1+="${BCYN}${MODEL}${RST}"
  # Show extended context indicator
  if [ -n "$CTX_SIZE" ] && [ "$CTX_SIZE" -gt 200000 ] 2>/dev/null; then
    L1+="${MAG}[$(fmt_tokens "$CTX_SIZE")]${RST}"
  fi
fi

# Git branch
if [ -n "$BRANCH" ]; then
  L1+=" ${DIM}|${RST} ${BMAG}${BRANCH}${YEL}${DIRTY}${RST}"
fi

# Agent name
if [ -n "$AGENT_NAME" ]; then
  L1+=" ${DIM}|${RST} ${BYEL}agent:${AGENT_NAME}${RST}"
fi

# Worktree
if [ -n "$WT_NAME" ]; then
  L1+=" ${DIM}|${RST} ${CYN}wt:${WT_NAME}${RST}"
  [ -n "$WT_BRANCH" ] && L1+="${DIM}(${WT_BRANCH})${RST}"
fi

# Vim mode
if [ -n "$VIM_MODE" ]; then
  if [ "$VIM_MODE" = "NORMAL" ]; then
    L1+=" ${DIM}|${RST} ${BGRN}NOR${RST}"
  else
    L1+=" ${DIM}|${RST} ${BYEL}INS${RST}"
  fi
fi

# Context bar
if [ -n "$USED_PCT" ]; then
  L1+=" ${DIM}|${RST} $(progress_bar "$USED_PCT") "
  pct_int=$(printf '%.0f' "$USED_PCT" 2>/dev/null || echo 0)
  if [ "$pct_int" -ge 90 ]; then
    L1+="${BRED}${pct_int}%${RST}"
  elif [ "$pct_int" -ge 75 ]; then
    L1+="${BYEL}${pct_int}%${RST}"
  elif [ "$pct_int" -ge 50 ]; then
    L1+="${YEL}${pct_int}%${RST}"
  else
    L1+="${GRN}${pct_int}%${RST}"
  fi
fi

echo -e "$L1"

# =====================================================================
# LINE 2: Tokens detail | Cache | Cost | Duration
# =====================================================================
L2=""

# Current context tokens
if [ -n "$CUR_IN" ]; then
  L2+="${DIM}ctx:${RST}$(fmt_tokens "$CUR_IN")${DIM}in${RST}"
  [ -n "$CUR_OUT" ] && L2+="${DIM}+${RST}$(fmt_tokens "$CUR_OUT")${DIM}out${RST}"
fi

# Session totals
if [ -n "$TOTAL_IN" ]; then
  [ -n "$L2" ] && L2+=" ${DIM}|${RST} "
  L2+="${DIM}ses:${RST}$(fmt_tokens "$TOTAL_IN")${DIM}in${RST}"
  [ -n "$TOTAL_OUT" ] && L2+="${DIM}+${RST}$(fmt_tokens "$TOTAL_OUT")${DIM}out${RST}"
fi

# Cache stats
if [ -n "$CACHE_READ" ] || [ -n "$CACHE_WRITE" ]; then
  [ -n "$L2" ] && L2+=" ${DIM}|${RST} "
  L2+="${DIM}cache:${RST}"
  [ -n "$CACHE_READ" ] && L2+="${GRN}$(fmt_tokens "$CACHE_READ")${DIM}hit${RST}"
  if [ -n "$CACHE_WRITE" ]; then
    [ -n "$CACHE_READ" ] && L2+="${DIM}/${RST}"
    L2+="${BLU}$(fmt_tokens "$CACHE_WRITE")${DIM}new${RST}"
  fi
fi

# Cost
if [ -n "$COST" ]; then
  [ -n "$L2" ] && L2+=" ${DIM}|${RST} "
  L2+="${BYEL}\$${COST}${RST}"
fi

# Duration
if [ -n "$DURATION_MS" ]; then
  [ -n "$L2" ] && L2+=" ${DIM}|${RST} "
  L2+="${DIM}elapsed:${RST}$(fmt_ms "$DURATION_MS")"
  if [ -n "$API_MS" ]; then
    L2+="${DIM}(api:${RST}$(fmt_ms "$API_MS")${DIM})${RST}"
  fi
fi

echo -e "$L2"

# =====================================================================
# LINE 3: Code changes | Rate limits | Session/version
# =====================================================================
L3=""

# Code changes
if [ -n "$LINES_ADD" ] || [ -n "$LINES_DEL" ]; then
  L3+="${BGRN}+${LINES_ADD:-0}${RST}${DIM}/${RST}${BRED}-${LINES_DEL:-0}${RST}${DIM}lines${RST}"
fi

# Rate limits
if [ -n "$RL5H" ]; then
  [ -n "$L3" ] && L3+=" ${DIM}|${RST} "
  pct5=$(printf '%.0f' "$RL5H" 2>/dev/null || echo 0)
  if [ "$pct5" -ge 80 ]; then
    L3+="${BRED}5h:${pct5}%${RST}"
  elif [ "$pct5" -ge 50 ]; then
    L3+="${YEL}5h:${pct5}%${RST}"
  else
    L3+="${DIM}5h:${pct5}%${RST}"
  fi
fi
if [ -n "$RL7D" ]; then
  pct7=$(printf '%.0f' "$RL7D" 2>/dev/null || echo 0)
  if [ "$pct7" -ge 80 ]; then
    L3+=" ${BRED}7d:${pct7}%${RST}"
  elif [ "$pct7" -ge 50 ]; then
    L3+=" ${YEL}7d:${pct7}%${RST}"
  else
    L3+=" ${DIM}7d:${pct7}%${RST}"
  fi
fi

# >200k indicator
if [ "$EXCEEDS_200K" = "true" ]; then
  [ -n "$L3" ] && L3+=" ${DIM}|${RST} "
  L3+="${BYEL}>200k${RST}"
fi

# Session ID (short) + version
if [ -n "$SESSION" ]; then
  [ -n "$L3" ] && L3+=" ${DIM}|${RST} "
  L3+="${DIM}${SESSION:0:8}${RST}"
fi
if [ -n "$VERSION" ]; then
  L3+=" ${DIM}v${VERSION}${RST}"
fi

echo -e "$L3"
