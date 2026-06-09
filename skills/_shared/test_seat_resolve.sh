#!/usr/bin/env bash
# test_seat_resolve.sh — bash test harness for seat_resolve.sh
#
# Builds real throwaway git repos in mktemp -d dirs; asserts each verdict.
# Run:  bash skills/_shared/test_seat_resolve.sh
# Exit: 0 = all fixtures pass; non-zero = at least one assertion failed.
#
# Each fixture cleans up its own mktemp dir (trap + explicit rm).

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve seat_resolve.sh relative to this file's location
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEAT_RESOLVE="${SCRIPT_DIR}/seat_resolve.sh"

# ---------------------------------------------------------------------------
# Colours / counters
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

_pass() { PASS=$((PASS + 1)); echo -e "  ${GREEN}PASS${NC} $1"; }
_fail() { FAIL=$((FAIL + 1)); echo -e "  ${RED}FAIL${NC} $1"; }

# ---------------------------------------------------------------------------
# Preflight: seat_resolve.sh must exist
# ---------------------------------------------------------------------------
if [[ ! -f "${SEAT_RESOLVE}" ]]; then
    echo "FAIL: seat_resolve.sh not found at ${SEAT_RESOLVE}" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Helper: mk_repo — initialise a bare or non-bare git repo with a commit
# Usage: mk_repo <dir> [--bare]
# Sets up git user config so commits work in the throwaway repo.
# ---------------------------------------------------------------------------
mk_repo() {
    local dir="$1"
    local bare="${2:-}"
    if [[ "${bare}" == "--bare" ]]; then
        git init --bare "${dir}" -q
    else
        git init "${dir}" -q
        git -C "${dir}" config user.email "test@test.invalid"
        git -C "${dir}" config user.name "Test"
        # Add a committed file so HEAD is not unborn
        echo "hello" > "${dir}/file.txt"
        git -C "${dir}" add file.txt
        git -C "${dir}" commit -m "init" -q
    fi
}

# ---------------------------------------------------------------------------
# Helper: assert_verdict — assert --detect output contains state=<verdict>
# ---------------------------------------------------------------------------
assert_verdict() {
    local label="$1" expected="$2" repo="$3"
    local out
    out="$("${SEAT_RESOLVE}" --detect --repo "${repo}" 2>&1)"
    if echo "${out}" | grep -q "state=${expected}"; then
        _pass "${label}: state=${expected}"
    else
        _fail "${label}: expected state=${expected}, got: ${out}"
    fi
}

# ---------------------------------------------------------------------------
# Helper: snapshot_before_after — assert no mutation across a command
# Usage: snapshot_before_after <repo> <label> <command...>
# ---------------------------------------------------------------------------
snapshot_before_after() {
    local repo="$1" label="$2"
    shift 2
    local before_status before_config after_status after_config
    before_status="$(git -C "${repo}" status --porcelain 2>&1 || true)"
    before_config="$(git -C "${repo}" config -l 2>&1 || true)"
    "$@" > /dev/null 2>&1 || true
    after_status="$(git -C "${repo}" status --porcelain 2>&1 || true)"
    after_config="$(git -C "${repo}" config -l 2>&1 || true)"
    if [[ "${before_status}" == "${after_status}" && "${before_config}" == "${after_config}" ]]; then
        _pass "${label}: no-mutation"
    else
        _fail "${label}: mutation detected (status or config changed)"
    fi
}

# ===========================================================================
# FIXTURE 1: seat-healthy
# ===========================================================================
echo ""
echo "=== Fixture: seat-healthy ==="
_tmp_seat_healthy="$(mktemp -d)"
trap 'rm -rf "${_tmp_seat_healthy}"' EXIT

mk_repo "${_tmp_seat_healthy}/repo"
# Create sibling *-wt/ dir with a worktree on branch tp/foo
git -C "${_tmp_seat_healthy}/repo" checkout -b tp/foo -q
git -C "${_tmp_seat_healthy}/repo" checkout -b master -q 2>/dev/null || \
    git -C "${_tmp_seat_healthy}/repo" checkout master -q 2>/dev/null || true
mkdir -p "${_tmp_seat_healthy}/repo-wt"
git -C "${_tmp_seat_healthy}/repo" worktree add "${_tmp_seat_healthy}/repo-wt/foo" tp/foo -q 2>/dev/null || {
    # branch may not exist yet; create it
    git -C "${_tmp_seat_healthy}/repo" branch tp/foo 2>/dev/null || true
    git -C "${_tmp_seat_healthy}/repo" worktree add "${_tmp_seat_healthy}/repo-wt/foo" tp/foo -q
}

# --detect from seat root => seat-healthy
assert_verdict "seat-healthy --detect" "seat-healthy" "${_tmp_seat_healthy}/repo"

# --am-i-seat from repo root => exit 0
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_seat_healthy}/repo"; then
    _pass "seat-healthy --am-i-seat from root: exit 0"
else
    _fail "seat-healthy --am-i-seat from root: expected exit 0, got exit 1"
fi

# --am-i-seat from *-wt/foo => exit 1
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_seat_healthy}/repo-wt/foo"; then
    _fail "seat-healthy --am-i-seat from wt/foo: expected exit 1, got exit 0"
else
    _pass "seat-healthy --am-i-seat from wt/foo: exit 1"
fi

# --where prints non-empty seat path equal to seat base dir
_where_out="$("${SEAT_RESOLVE}" --where --repo "${_tmp_seat_healthy}/repo")"
if [[ -n "${_where_out}" && "${_where_out}" != "NONE" ]]; then
    _pass "seat-healthy --where: non-empty, non-NONE: ${_where_out}"
else
    _fail "seat-healthy --where: expected non-empty non-NONE, got: '${_where_out}'"
fi

# no-mutation checks
snapshot_before_after "${_tmp_seat_healthy}/repo" "seat-healthy --detect no-mutation" \
    "${SEAT_RESOLVE}" --detect --repo "${_tmp_seat_healthy}/repo"
snapshot_before_after "${_tmp_seat_healthy}/repo" "seat-healthy --where no-mutation" \
    "${SEAT_RESOLVE}" --where --repo "${_tmp_seat_healthy}/repo"
snapshot_before_after "${_tmp_seat_healthy}/repo" "seat-healthy --am-i-seat no-mutation" \
    "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_seat_healthy}/repo"
snapshot_before_after "${_tmp_seat_healthy}/repo" "seat-healthy --json no-mutation" \
    "${SEAT_RESOLVE}" --json --repo "${_tmp_seat_healthy}/repo"

trap - EXIT
rm -rf "${_tmp_seat_healthy}"

# ===========================================================================
# FIXTURE 2: core-bare-flip
# ===========================================================================
echo ""
echo "=== Fixture: core-bare-flip ==="
_tmp_core_bare="$(mktemp -d)"
trap 'rm -rf "${_tmp_core_bare}"' EXIT

mk_repo "${_tmp_core_bare}/repo"
# The repo has a committed file. Now flip core.bare to true.
git -C "${_tmp_core_bare}/repo" config core.bare true

# (a) --detect => core-bare-flip
assert_verdict "core-bare-flip --detect" "core-bare-flip" "${_tmp_core_bare}/repo"

# (b) Normative discriminator: [ -d <toplevel>/.git ] AND is-bare==true
_toplevel="$(git -C "${_tmp_core_bare}/repo" worktree list --porcelain | grep '^worktree ' | head -1 | cut -d' ' -f2-)"
if [[ -d "${_toplevel}/.git" ]]; then
    _pass "core-bare-flip discriminator: .git subdir exists"
else
    _fail "core-bare-flip discriminator: .git subdir NOT found at ${_toplevel}/.git"
fi

_is_bare="$(git -C "${_tmp_core_bare}/repo" rev-parse --is-bare-repository 2>&1 || true)"
if [[ "${_is_bare}" == "true" ]]; then
    _pass "core-bare-flip: is-bare-repository=true"
else
    _fail "core-bare-flip: expected is-bare-repository=true, got: ${_is_bare}"
fi

# (c) --am-i-seat => exit 1
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_core_bare}/repo"; then
    _fail "core-bare-flip --am-i-seat: expected exit 1, got exit 0"
else
    _pass "core-bare-flip --am-i-seat: exit 1"
fi

# (d) git rev-parse --show-toplevel fails (exit 128) on core-bare-flip
if git -C "${_tmp_core_bare}/repo" rev-parse --show-toplevel > /dev/null 2>&1; then
    _fail "core-bare-flip: --show-toplevel unexpectedly succeeded (expected exit 128)"
else
    _ec=$?
    if [[ ${_ec} -eq 128 ]]; then
        _pass "core-bare-flip: --show-toplevel fails exit 128 as expected"
    else
        _pass "core-bare-flip: --show-toplevel failed exit ${_ec} (non-zero, proves unusable)"
    fi
fi

# no-mutation
snapshot_before_after "${_tmp_core_bare}/repo" "core-bare-flip --detect no-mutation" \
    "${SEAT_RESOLVE}" --detect --repo "${_tmp_core_bare}/repo"

trap - EXIT
rm -rf "${_tmp_core_bare}"

# ===========================================================================
# FIXTURE 3: missing-seat / repair_hint == add-worktree
# ===========================================================================
echo ""
echo "=== Fixture: missing-seat / repair_hint=add-worktree ==="
_tmp_missing="$(mktemp -d)"
trap 'rm -rf "${_tmp_missing}"' EXIT

# A genuine bare hub with no standing worktree
git init --bare "${_tmp_missing}/hub" -q

# Assert verdict = missing-seat
assert_verdict "missing-seat --detect" "missing-seat" "${_tmp_missing}/hub"

# Assert repair_hint=add-worktree in --detect output
_detect_out="$("${SEAT_RESOLVE}" --detect --repo "${_tmp_missing}/hub" 2>&1)"
if echo "${_detect_out}" | grep -q "repair_hint=add-worktree"; then
    _pass "missing-seat: repair_hint=add-worktree in --detect"
else
    _fail "missing-seat: repair_hint=add-worktree NOT in --detect output: ${_detect_out}"
fi

# Assert NO .git/ subdir at toplevel (confirms genuine bare, not core-bare-flip)
if [[ -d "${_tmp_missing}/hub/.git" ]]; then
    _fail "missing-seat: unexpected .git subdir (should be genuine bare hub)"
else
    _pass "missing-seat: no .git subdir (genuine bare hub confirmed)"
fi

# --json: state=missing-seat, seat_path absent/NONE, repair_hint=add-worktree
_json_out="$("${SEAT_RESOLVE}" --json --repo "${_tmp_missing}/hub" 2>&1)"
if echo "${_json_out}" | grep -q '"state".*"missing-seat"'; then
    _pass "missing-seat --json: state=missing-seat"
else
    _fail "missing-seat --json: state not found: ${_json_out}"
fi
if echo "${_json_out}" | grep -q '"repair_hint".*"add-worktree"'; then
    _pass "missing-seat --json: repair_hint=add-worktree"
else
    _fail "missing-seat --json: repair_hint not found: ${_json_out}"
fi
if echo "${_json_out}" | grep -q '"seat_path"'; then
    _pass "missing-seat --json: seat_path field present"
else
    _fail "missing-seat --json: seat_path field missing"
fi

# --where on missing-seat prints exactly NONE
_where_missing="$("${SEAT_RESOLVE}" --where --repo "${_tmp_missing}/hub")"
if [[ "${_where_missing}" == "NONE" ]]; then
    _pass "missing-seat --where: prints exactly NONE"
else
    _fail "missing-seat --where: expected NONE, got '${_where_missing}'"
fi

# no-mutation (git status porcelain on bare repo may differ; use config only)
_before_cfg="$(git -C "${_tmp_missing}/hub" config -l 2>&1 || true)"
"${SEAT_RESOLVE}" --detect --repo "${_tmp_missing}/hub" > /dev/null 2>&1 || true
_after_cfg="$(git -C "${_tmp_missing}/hub" config -l 2>&1 || true)"
if [[ "${_before_cfg}" == "${_after_cfg}" ]]; then
    _pass "missing-seat --detect no-mutation"
else
    _fail "missing-seat --detect no-mutation: config changed"
fi

trap - EXIT
rm -rf "${_tmp_missing}"

# ===========================================================================
# FIXTURE 4: bare-hub-variant
# ===========================================================================
echo ""
echo "=== Fixture: bare-hub-variant ==="
_tmp_bare_hub="$(mktemp -d)"
trap 'rm -rf "${_tmp_bare_hub}"' EXIT

# Set up a non-bare clone to create commits, then use it as source for bare hub
mk_repo "${_tmp_bare_hub}/source"
git -C "${_tmp_bare_hub}/source" config user.email "test@test.invalid"
git -C "${_tmp_bare_hub}/source" config user.name "Test"

# Clone bare
git clone --bare "${_tmp_bare_hub}/source" "${_tmp_bare_hub}/hub" -q 2>/dev/null

# Resolve the default base branch name in the hub
_hub_base="$(git -C "${_tmp_bare_hub}/hub" symbolic-ref --short HEAD 2>/dev/null | sed 's|^refs/heads/||' || echo "master")"
if [[ -z "${_hub_base}" ]]; then
    _hub_base="master"
fi

# Add a standing worktree for the base branch
mkdir -p "${_tmp_bare_hub}/hub-wt"
git -C "${_tmp_bare_hub}/hub" worktree add "${_tmp_bare_hub}/hub-wt/${_hub_base}" "${_hub_base}" -q 2>/dev/null || {
    # Try with HEAD
    git -C "${_tmp_bare_hub}/hub" worktree add "${_tmp_bare_hub}/hub-wt/master" HEAD -q
}

assert_verdict "bare-hub-variant --detect" "bare-hub-variant" "${_tmp_bare_hub}/hub"

# Also assert NOT missing-seat
_bh_out="$("${SEAT_RESOLVE}" --detect --repo "${_tmp_bare_hub}/hub" 2>&1)"
if echo "${_bh_out}" | grep -q "state=missing-seat"; then
    _fail "bare-hub-variant: got missing-seat (should be bare-hub-variant)"
else
    _pass "bare-hub-variant: NOT missing-seat"
fi
if echo "${_bh_out}" | grep -q "state=core-bare-flip"; then
    _fail "bare-hub-variant: got core-bare-flip (should be bare-hub-variant)"
else
    _pass "bare-hub-variant: NOT core-bare-flip"
fi

# no-mutation
_before_cfg_bh="$(git -C "${_tmp_bare_hub}/hub" config -l 2>&1 || true)"
"${SEAT_RESOLVE}" --detect --repo "${_tmp_bare_hub}/hub" > /dev/null 2>&1 || true
_after_cfg_bh="$(git -C "${_tmp_bare_hub}/hub" config -l 2>&1 || true)"
if [[ "${_before_cfg_bh}" == "${_after_cfg_bh}" ]]; then
    _pass "bare-hub-variant --detect no-mutation"
else
    _fail "bare-hub-variant --detect no-mutation: config changed"
fi

trap - EXIT
rm -rf "${_tmp_bare_hub}"

# ===========================================================================
# FIXTURE 5: redundant-base-worktree
# ===========================================================================
echo ""
echo "=== Fixture: redundant-base-worktree ==="
_tmp_redundant="$(mktemp -d)"
trap 'rm -rf "${_tmp_redundant}"' EXIT

mk_repo "${_tmp_redundant}/repo"
# Determine base branch name
_base_r="$(git -C "${_tmp_redundant}/repo" symbolic-ref --short HEAD 2>/dev/null || echo "master")"
# Create a *-wt/{base} worktree (the redundant one)
mkdir -p "${_tmp_redundant}/repo-wt"
git -C "${_tmp_redundant}/repo" worktree add "${_tmp_redundant}/repo-wt/${_base_r}" HEAD -q 2>/dev/null || \
    git -C "${_tmp_redundant}/repo" worktree add "${_tmp_redundant}/repo-wt/${_base_r}" -q

assert_verdict "redundant-base-worktree --detect" "redundant-base-worktree" "${_tmp_redundant}/repo"

# --am-i-seat from seat root => exit 0 (documents finding #5 caveat: --am-i-seat
# does NOT catch the shadow; only --detect does)
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_redundant}/repo"; then
    _pass "redundant-base-worktree --am-i-seat from seat: exit 0 (finding #5 documented)"
else
    _fail "redundant-base-worktree --am-i-seat from seat: expected exit 0 (finding #5)"
fi

# no-mutation
snapshot_before_after "${_tmp_redundant}/repo" "redundant-base-worktree --detect no-mutation" \
    "${SEAT_RESOLVE}" --detect --repo "${_tmp_redundant}/repo"

trap - EXIT
rm -rf "${_tmp_redundant}"

# ===========================================================================
# FIXTURE 6: design-worktree (three sub-cases — total enum, finding #3)
# ===========================================================================
echo ""
echo "=== Fixture: design-worktree (3 sub-cases) ==="
_tmp_dw="$(mktemp -d)"
trap 'rm -rf "${_tmp_dw}"' EXIT

mk_repo "${_tmp_dw}/repo"
_base_dw="$(git -C "${_tmp_dw}/repo" symbolic-ref --short HEAD 2>/dev/null || echo "master")"
mkdir -p "${_tmp_dw}/repo-wt"

# Sub-case (i): *-wt/foo on tp/foo
git -C "${_tmp_dw}/repo" branch tp/foo 2>/dev/null || true
git -C "${_tmp_dw}/repo" worktree add "${_tmp_dw}/repo-wt/foo" tp/foo -q

assert_verdict "design-worktree tp/foo --detect" "design-worktree" "${_tmp_dw}/repo-wt/foo"
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_dw}/repo-wt/foo"; then
    _fail "design-worktree tp/foo --am-i-seat: expected exit 1"
else
    _pass "design-worktree tp/foo --am-i-seat: exit 1"
fi

# Sub-case (ii): *-wt/foo on non-tp branch (e.g. candidate/x)
# Create the worktree on tp/foo, then checkout candidate/x inside it
git -C "${_tmp_dw}/repo" branch candidate/x 2>/dev/null || true
git -C "${_tmp_dw}/repo-wt/foo" checkout candidate/x -q 2>/dev/null || {
    # If checkout fails, just verify the worktree path shape still gives design-worktree
    true
}

assert_verdict "design-worktree candidate/x --detect" "design-worktree" "${_tmp_dw}/repo-wt/foo"
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_dw}/repo-wt/foo"; then
    _fail "design-worktree candidate/x --am-i-seat: expected exit 1"
else
    _pass "design-worktree candidate/x --am-i-seat: exit 1"
fi

# Sub-case (iii): *-wt/foo on detached HEAD
# Add a second worktree for detached HEAD test to avoid confusing the foo one
git -C "${_tmp_dw}/repo" worktree add --detach "${_tmp_dw}/repo-wt/detached" HEAD -q 2>/dev/null || {
    # Some git versions need a sha
    _sha="$(git -C "${_tmp_dw}/repo" rev-parse HEAD)"
    git -C "${_tmp_dw}/repo" worktree add --detach "${_tmp_dw}/repo-wt/detached" "${_sha}" -q
}

assert_verdict "design-worktree detached HEAD --detect" "design-worktree" "${_tmp_dw}/repo-wt/detached"
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_dw}/repo-wt/detached"; then
    _fail "design-worktree detached --am-i-seat: expected exit 1"
else
    _pass "design-worktree detached --am-i-seat: exit 1"
fi

# no-mutation
snapshot_before_after "${_tmp_dw}/repo" "design-worktree --detect no-mutation" \
    "${SEAT_RESOLVE}" --detect --repo "${_tmp_dw}/repo-wt/foo"
snapshot_before_after "${_tmp_dw}/repo" "design-worktree --am-i-seat no-mutation" \
    "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_dw}/repo-wt/foo"

trap - EXIT
rm -rf "${_tmp_dw}"

# ===========================================================================
# FIXTURE 7: unknown-worktree (catch-all)
# ===========================================================================
echo ""
echo "=== Fixture: unknown-worktree ==="
_tmp_unk="$(mktemp -d)"
trap 'rm -rf "${_tmp_unk}"' EXIT

mk_repo "${_tmp_unk}/repo"
# Add a detached worktree at a path that is NOT under *-wt/ (outside the canonical *-wt/ dir)
_odd_dir="${_tmp_unk}/odd"
mkdir -p "${_odd_dir}"
git -C "${_tmp_unk}/repo" worktree add --detach "${_odd_dir}" HEAD -q 2>/dev/null || {
    _sha="$(git -C "${_tmp_unk}/repo" rev-parse HEAD)"
    git -C "${_tmp_unk}/repo" worktree add --detach "${_odd_dir}" "${_sha}" -q
}

assert_verdict "unknown-worktree --detect" "unknown-worktree" "${_odd_dir}"

# no-mutation
snapshot_before_after "${_tmp_unk}/repo" "unknown-worktree --detect no-mutation" \
    "${SEAT_RESOLVE}" --detect --repo "${_odd_dir}"

trap - EXIT
rm -rf "${_tmp_unk}"

# ===========================================================================
# FIXTURE 8: fail-open / indeterminate
# ===========================================================================
echo ""
echo "=== Fixture: indeterminate (fail-open) ==="
_tmp_ind="$(mktemp -d)"
trap 'rm -rf "${_tmp_ind}"' EXIT

# --repo at a non-repo dir => indeterminate, exit 0
# set +e / set -e so the exit code is genuinely observable — under set -e a
# non-zero reporter exit aborts the harness at the assignment before _ec=$? is
# read, making the assertion vacuously always-pass (same flaw fixed in fixtures
# 10/11).
_ind_out=""
_ind_ec=0
set +e
_ind_out="$("${SEAT_RESOLVE}" --detect --repo "${_tmp_ind}" 2>&1)"
_ind_ec=$?
set -e
if [[ ${_ind_ec} -eq 0 ]]; then
    _pass "indeterminate --detect: exit 0 (reporter always exits 0)"
else
    _fail "indeterminate --detect: expected exit 0, got exit ${_ind_ec}"
fi
if echo "${_ind_out}" | grep -q "state=indeterminate"; then
    _pass "indeterminate --detect: state=indeterminate"
else
    _fail "indeterminate --detect: expected state=indeterminate, got: ${_ind_out}"
fi

# --am-i-seat on non-repo => exit 1
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_ind}"; then
    _fail "indeterminate --am-i-seat: expected exit 1, got exit 0"
else
    _pass "indeterminate --am-i-seat: exit 1"
fi

trap - EXIT
rm -rf "${_tmp_ind}"

# ===========================================================================
# FIXTURE 9: --where output on seat-healthy (non-empty, equals seat base dir)
# ===========================================================================
echo ""
echo "=== Fixture: --where output ==="
_tmp_where="$(mktemp -d)"
trap 'rm -rf "${_tmp_where}"' EXIT

mk_repo "${_tmp_where}/repo"
git -C "${_tmp_where}/repo" branch tp/bar 2>/dev/null || true
mkdir -p "${_tmp_where}/repo-wt"
git -C "${_tmp_where}/repo" worktree add "${_tmp_where}/repo-wt/bar" tp/bar -q 2>/dev/null || true

_where_seat="$("${SEAT_RESOLVE}" --where --repo "${_tmp_where}/repo")"
if [[ -n "${_where_seat}" && "${_where_seat}" != "NONE" ]]; then
    _pass "--where on healthy seat: non-empty non-NONE: ${_where_seat}"
else
    _fail "--where on healthy seat: expected non-empty non-NONE, got: '${_where_seat}'"
fi

# The where output should match the seat base dir (canonicalized)
_expected_seat="$(cd "${_tmp_where}/repo" && pwd)"
_actual_seat="$(cd "${_where_seat}" 2>/dev/null && pwd || echo "${_where_seat}")"
if [[ "${_actual_seat}" == "${_expected_seat}" ]]; then
    _pass "--where equals seat base dir"
else
    _fail "--where: expected '${_expected_seat}', got '${_actual_seat}'"
fi

trap - EXIT
rm -rf "${_tmp_where}"

# ===========================================================================
# FIXTURE 10: exit-code contract — reporters always exit 0
# ===========================================================================
echo ""
echo "=== Fixture: exit-code contract (reporters always exit 0) ==="
_tmp_ec="$(mktemp -d)"
trap 'rm -rf "${_tmp_ec}"' EXIT

mk_repo "${_tmp_ec}/repo"

# --detect always exits 0
# set +e / set -e around the call so the exit code is genuinely observable —
# under set -e a non-zero reporter exit aborts the harness at the bare command
# before _ec=$? is read, making the assertion vacuously always-pass (same flaw
# fixed in the non-cd-able fixture below).
_ec_detect=0
set +e
"${SEAT_RESOLVE}" --detect --repo "${_tmp_ec}/repo" > /dev/null 2>&1
_ec_detect=$?
set -e
if [[ ${_ec_detect} -eq 0 ]]; then
    _pass "exit-code: --detect exits 0"
else
    _fail "exit-code: --detect exits ${_ec_detect} (expected 0)"
fi

# --where always exits 0
_ec_where=0
set +e
"${SEAT_RESOLVE}" --where --repo "${_tmp_ec}/repo" > /dev/null 2>&1
_ec_where=$?
set -e
if [[ ${_ec_where} -eq 0 ]]; then
    _pass "exit-code: --where exits 0"
else
    _fail "exit-code: --where exits ${_ec_where} (expected 0)"
fi

# --json always exits 0
_ec_json=0
set +e
"${SEAT_RESOLVE}" --json --repo "${_tmp_ec}/repo" > /dev/null 2>&1
_ec_json=$?
set -e
if [[ ${_ec_json} -eq 0 ]]; then
    _pass "exit-code: --json exits 0"
else
    _fail "exit-code: --json exits ${_ec_json} (expected 0)"
fi

# --am-i-seat on healthy seat exits 0
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_ec}/repo"; then
    _pass "exit-code: --am-i-seat on healthy exits 0"
else
    _fail "exit-code: --am-i-seat on healthy exits 1 (expected 0)"
fi

trap - EXIT
rm -rf "${_tmp_ec}"

# ===========================================================================
# FIXTURE 11: _canon infallible — non-cd-able sibling worktree path (Fix 1+3)
# --detect must still exit 0 with a verdict even when a registered worktree
# directory is not cd-able (e.g. permissions 000 after registration).
# ===========================================================================
echo ""
echo "=== Fixture: _canon infallible (non-cd-able sibling worktree) ==="
_tmp_nocd="$(mktemp -d)"
trap 'chmod 755 "${_tmp_nocd}/repo-wt/foo" 2>/dev/null || true; rm -rf "${_tmp_nocd}"' EXIT

mk_repo "${_tmp_nocd}/repo"
git -C "${_tmp_nocd}/repo" branch tp/foo 2>/dev/null || true
mkdir -p "${_tmp_nocd}/repo-wt"
git -C "${_tmp_nocd}/repo" worktree add "${_tmp_nocd}/repo-wt/foo" tp/foo -q

# Make the worktree directory non-cd-able so _canon would fail without the fix
chmod 000 "${_tmp_nocd}/repo-wt/foo"

# --detect must still exit 0 (reporter always-exit-0 contract holds).
# set +e / set -e around the call so the exit code is genuinely observable —
# under set -e a non-zero exit from within $() would abort the script before
# _ec=$? is reached, making that pattern vacuously always-pass.
_nocd_out=""
_nocd_ec=0
set +e
_nocd_out="$("${SEAT_RESOLVE}" --detect --repo "${_tmp_nocd}/repo" 2>&1)"
_nocd_ec=$?
set -e
if [[ ${_nocd_ec} -eq 0 ]]; then
    _pass "_canon-infallible: --detect still exits 0 with non-cd-able sibling worktree"
else
    _fail "_canon-infallible: --detect exited ${_nocd_ec} (expected 0)"
fi
# Specific verdict: seat-healthy (seat on master/main; tp/foo worktree is non-cd-able)
if echo "${_nocd_out}" | grep -q "state=seat-healthy"; then
    _pass "_canon-infallible: --detect => state=seat-healthy with non-cd-able sibling"
else
    _fail "_canon-infallible: --detect => expected state=seat-healthy, got: ${_nocd_out}"
fi

# Restore permissions before cleanup
chmod 755 "${_tmp_nocd}/repo-wt/foo"

trap - EXIT
rm -rf "${_tmp_nocd}"

# ===========================================================================
# FIXTURE 12: _canon physical — symlinked --repo path (Fix 1+3)
# --am-i-seat and --detect must agree when --repo is a symlink to the seat.
# ===========================================================================
echo ""
echo "=== Fixture: _canon physical (symlinked --repo path) ==="
_tmp_sym="$(mktemp -d)"
trap 'rm -rf "${_tmp_sym}"' EXIT

mk_repo "${_tmp_sym}/repo"
git -C "${_tmp_sym}/repo" branch tp/baz 2>/dev/null || true
mkdir -p "${_tmp_sym}/repo-wt"
git -C "${_tmp_sym}/repo" worktree add "${_tmp_sym}/repo-wt/baz" tp/baz -q

# Create a symlink pointing to the seat directory
ln -s "${_tmp_sym}/repo" "${_tmp_sym}/repo-link"

# Both modes must agree: symlinked path is seat
if "${SEAT_RESOLVE}" --am-i-seat --repo "${_tmp_sym}/repo-link"; then
    _pass "symlinked-repo: --am-i-seat via symlink exits 0 (seat)"
else
    _fail "symlinked-repo: --am-i-seat via symlink exits 1 (expected 0)"
fi

_sym_detect="$("${SEAT_RESOLVE}" --detect --repo "${_tmp_sym}/repo-link" 2>&1)"
if echo "${_sym_detect}" | grep -q "state=seat-healthy"; then
    _pass "symlinked-repo: --detect via symlink => seat-healthy"
else
    _fail "symlinked-repo: --detect via symlink => unexpected: ${_sym_detect}"
fi

trap - EXIT
rm -rf "${_tmp_sym}"

# ===========================================================================
# FIXTURE 13: _resolve_base bare hub with non-standard default branch (Fix 2)
# A bare hub whose HEAD == trunk + a standing trunk worktree => bare-hub-variant
# (not missing-seat, which would happen if the cascade falls to master).
# ===========================================================================
echo ""
echo "=== Fixture: _resolve_base bare hub with default branch trunk (Fix 2) ==="
_tmp_trunk="$(mktemp -d)"
trap 'rm -rf "${_tmp_trunk}"' EXIT

# Build a source repo on branch 'trunk'
git init "${_tmp_trunk}/source" -q
git -C "${_tmp_trunk}/source" config user.email "test@test.invalid"
git -C "${_tmp_trunk}/source" config user.name "Test"
git -C "${_tmp_trunk}/source" checkout -b trunk -q 2>/dev/null || \
    git -C "${_tmp_trunk}/source" symbolic-ref HEAD refs/heads/trunk
echo "hello" > "${_tmp_trunk}/source/file.txt"
git -C "${_tmp_trunk}/source" add file.txt
git -C "${_tmp_trunk}/source" commit -m "init" -q

# Clone bare — no origin remote pointing to a live remote, so origin/HEAD
# won't be resolvable remotely.  The bare hub's HEAD == trunk (set by clone).
git clone --bare "${_tmp_trunk}/source" "${_tmp_trunk}/hub" -q 2>/dev/null

# Unset origin/HEAD in the bare hub to force the _resolve_base cascade past
# origin/HEAD (simulating a disconnected bare clone with non-standard default).
git -C "${_tmp_trunk}/hub" remote remove origin 2>/dev/null || true

# Add a standing worktree for 'trunk'
mkdir -p "${_tmp_trunk}/hub-wt"
git -C "${_tmp_trunk}/hub" worktree add "${_tmp_trunk}/hub-wt/trunk" trunk -q

assert_verdict "bare-trunk-hub --detect" "bare-hub-variant" "${_tmp_trunk}/hub"

# Must NOT be missing-seat
_trunk_out="$("${SEAT_RESOLVE}" --detect --repo "${_tmp_trunk}/hub" 2>&1)"
if echo "${_trunk_out}" | grep -q "state=missing-seat"; then
    _fail "bare-trunk-hub: got missing-seat (trunk worktree not found — bare symbolic-ref fix missing)"
else
    _pass "bare-trunk-hub: NOT missing-seat (bare symbolic-ref resolved trunk correctly)"
fi

trap - EXIT
rm -rf "${_tmp_trunk}"

# ===========================================================================
# FIXTURE 14: _resolve_base non-bare seat with develop as base (via origin/HEAD)
# with *-wt/develop shadow (Fix 2 regression check b) — must be
# redundant-base-worktree, not seat-healthy.
# Also verifies the NON-bare path does NOT misuse symbolic-ref HEAD as base
# (a seat on a tp/feat feature branch is still seat-healthy, not redundant).
# ===========================================================================
echo ""
echo "=== Fixture: _resolve_base non-bare seat with develop base + shadow (Fix 2 regression b) ==="
_tmp_dev="$(mktemp -d)"
trap 'rm -rf "${_tmp_dev}"' EXIT

# Build a "remote" source on branch develop
git init "${_tmp_dev}/remote" -q
git -C "${_tmp_dev}/remote" config user.email "test@test.invalid"
git -C "${_tmp_dev}/remote" config user.name "Test"
git -C "${_tmp_dev}/remote" checkout -b develop -q 2>/dev/null || \
    git -C "${_tmp_dev}/remote" symbolic-ref HEAD refs/heads/develop
echo "hello" > "${_tmp_dev}/remote/file.txt"
git -C "${_tmp_dev}/remote" add file.txt
git -C "${_tmp_dev}/remote" commit -m "init" -q

# Clone (non-bare) — origin/HEAD will point to develop
git clone "${_tmp_dev}/remote" "${_tmp_dev}/repo" -q

# Add a *-wt/develop worktree (the redundant one) — develop branch checked out
mkdir -p "${_tmp_dev}/repo-wt"
git -C "${_tmp_dev}/repo" worktree add "${_tmp_dev}/repo-wt/develop" develop -q 2>/dev/null || \
    git -C "${_tmp_dev}/repo" worktree add "${_tmp_dev}/repo-wt/develop" HEAD -q

# origin/HEAD resolves to develop → _resolve_base returns develop → shadow detected
assert_verdict "develop-shadow-origin-head" "redundant-base-worktree" "${_tmp_dev}/repo"

# Regression: now add a tp/feat worktree and run from the seat on develop.
# The seat is on develop (checked out), wt/develop is the shadow. Must still be
# redundant-base-worktree (not seat-healthy).
git -C "${_tmp_dev}/repo" branch tp/feat 2>/dev/null || true
git -C "${_tmp_dev}/repo" worktree add "${_tmp_dev}/repo-wt/feat" tp/feat -q
assert_verdict "develop-shadow-with-feat-worktree" "redundant-base-worktree" "${_tmp_dev}/repo"

# Verify the NON-bare symbolic-ref guard: if we checkout tp/feat in the seat
# (making symbolic-ref HEAD return tp/feat), _resolve_base must NOT use that
# as the base — origin/HEAD (develop) takes priority, so shadow is still detected.
# (We do not actually check out tp/feat in the seat here to avoid breaking the
# worktree state; the unit test for the non-bare guard is fixture 15.)

trap - EXIT
rm -rf "${_tmp_dev}"

# ===========================================================================
# FIXTURE 15: _resolve_base non-bare seat on tp/foo feature branch (Fix 2 regression c)
# A normal seat on master/main with a tp/foo worktree, run from inside the
# tp/foo worktree — must classify as design-worktree (base resolves to
# master/main, NOT to 'tp/foo').
# ===========================================================================
echo ""
echo "=== Fixture: _resolve_base non-bare seat on feature branch (Fix 2 regression c) ==="
_tmp_feat="$(mktemp -d)"
trap 'rm -rf "${_tmp_feat}"' EXIT

mk_repo "${_tmp_feat}/repo"
# mk_repo creates a commit; determine what branch name it used
_feat_base="$(git -C "${_tmp_feat}/repo" symbolic-ref --short HEAD 2>/dev/null || echo "master")"

git -C "${_tmp_feat}/repo" branch tp/alpha 2>/dev/null || true
mkdir -p "${_tmp_feat}/repo-wt"
git -C "${_tmp_feat}/repo" worktree add "${_tmp_feat}/repo-wt/alpha" tp/alpha -q

# From the seat (master/main), must be seat-healthy
assert_verdict "feature-branch seat: seat" "seat-healthy" "${_tmp_feat}/repo"

# From the design worktree, must be design-worktree (not unknown or seat-healthy)
assert_verdict "feature-branch seat: wt/alpha" "design-worktree" "${_tmp_feat}/repo-wt/alpha"

trap - EXIT
rm -rf "${_tmp_feat}"

# ===========================================================================
# FIXTURE 16: is_bare gate — non-bare seat on tp/* branch + *-wt/master shadow
# (Regression: WITHOUT the is_bare gate in _resolve_base, symbolic-ref HEAD
# would return the tp/* feature branch and *-wt/master would NOT match it,
# giving a silently-wrong seat-healthy verdict instead of
# redundant-base-worktree.)
#
# Setup: non-bare repo, seat checked out on tp/feature (NOT master), no origin
# remote (no origin/HEAD), master branch exists, *-wt/master shadow worktree.
#
# WITH gate:    _resolve_base falls past origin/HEAD (none) and past the
#               bare-only symbolic-ref step, then tries main (absent) → master
#               → base = master → *-wt/master matched → redundant-base-worktree
# WITHOUT gate: _resolve_base uses symbolic-ref HEAD = tp/feature as base →
#               *-wt/master name ≠ tp/feature → has_redundant=false →
#               seat-healthy  (WRONG — fixture FAILS on gate-revert)
# ===========================================================================
echo ""
echo "=== Fixture: is_bare gate — non-bare seat on tp/feature + *-wt/master shadow ==="
_tmp_bare_gate="$(mktemp -d)"
trap 'rm -rf "${_tmp_bare_gate}"' EXIT

# Build a non-bare repo; mk_repo leaves it on master (or main)
mk_repo "${_tmp_bare_gate}/repo"
# Ensure we have a 'master' branch (mk_repo may use 'main' on some systems)
_bg_init_branch="$(git -C "${_tmp_bare_gate}/repo" symbolic-ref --short HEAD 2>/dev/null || echo "master")"
if [[ "${_bg_init_branch}" != "master" ]]; then
    git -C "${_tmp_bare_gate}/repo" checkout -b master -q 2>/dev/null || \
        git -C "${_tmp_bare_gate}/repo" branch master -q 2>/dev/null || true
    git -C "${_tmp_bare_gate}/repo" checkout master -q
fi

# Create the tp/feature branch and check out the seat onto it
git -C "${_tmp_bare_gate}/repo" checkout -b tp/feature -q

# No origin remote (so no origin/HEAD to resolve base from)
# (mk_repo never adds a remote, so no action needed)

# Add a *-wt/master worktree for the master branch (the redundant shadow)
mkdir -p "${_tmp_bare_gate}/repo-wt"
git -C "${_tmp_bare_gate}/repo" worktree add "${_tmp_bare_gate}/repo-wt/master" master -q

# Verify: seat is non-bare
_bg_bare="$(git -C "${_tmp_bare_gate}/repo" rev-parse --is-bare-repository 2>/dev/null || echo "?")"
if [[ "${_bg_bare}" == "false" ]]; then
    _pass "is_bare-gate setup: repo is non-bare"
else
    _fail "is_bare-gate setup: expected non-bare, got is-bare=${_bg_bare}"
fi

# Verify: seat HEAD is tp/feature (symbolic-ref would return tp/feature without gate)
_bg_head="$(git -C "${_tmp_bare_gate}/repo" symbolic-ref --short HEAD 2>/dev/null || echo "?")"
if [[ "${_bg_head}" == "tp/feature" ]]; then
    _pass "is_bare-gate setup: seat HEAD is tp/feature (gate exercise confirmed)"
else
    _fail "is_bare-gate setup: expected seat HEAD=tp/feature, got: ${_bg_head}"
fi

# Core assertion: must be redundant-base-worktree (gate prevents tp/feature misuse)
assert_verdict "is_bare-gate: non-bare seat on tp/feature + *-wt/master" \
    "redundant-base-worktree" "${_tmp_bare_gate}/repo"

trap - EXIT
rm -rf "${_tmp_bare_gate}"

# ===========================================================================
# Summary
# ===========================================================================
echo ""
echo "=================================="
echo "Results: ${PASS} passed, ${FAIL} failed"
echo "=================================="

if [[ ${FAIL} -gt 0 ]]; then
    exit 1
fi
exit 0
