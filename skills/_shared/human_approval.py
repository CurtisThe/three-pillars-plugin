"""human_approval — the REQUIRED human-approval merge-gate predicate (read path).

stdlib-only (C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`).
Subprocess calls go to `gh` only, never to Claude/anthropic. Mirrors
`review_readiness.py`'s shape: live `*_fn` runners with an injected-dict test seam.

See `three-pillars-docs/completed-tp-designs/human-approval-merge-gate/detailed-design.md` for
the full interface specification and Finding dispositions (F1–F4, Decisions D1–D13).

Core guarantee (login-independent, holds even when the human operator and the
framework automation share one GitHub account — the documented user-PAT workflow):
a present-AND-current `tp:human-approved` label requires a deliberate human action
on THIS exact head, because (a) the automation NEVER calls the apply-label path,
(b) every framework push auto-strips the label, and (c) the gate re-checks currency
on the head SHA. The login-layer checks (bot/App floor + automation-identity set) are
defense-in-depth, not the sole proof.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# ---- sys.path: ensure _shared/ is on path so sibling modules are importable ----
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


# ============================================================
# Constant
# ============================================================

# Defined once here (beside label_manager.READY_FOR_HUMAN_MERGE), imported where needed.
HUMAN_APPROVED_LABEL = "tp:human-approved"
# The applied label carries the head SHA as a tag: `tp:human-approved:<sha7+>`.
# The bare base is the family root; presence-matching accepts base OR base+":<tag>".
HUMAN_APPROVED_LABEL_PREFIX = HUMAN_APPROVED_LABEL + ":"


# ============================================================
# Task 1.1: _label_present
# ============================================================


def _label_present(labels, label: str) -> bool:
    """True ⟺ a `label`-FAMILY label is present in the PR labels list.

    Family match: a name equals `label` (the bare base) OR starts with `label + ":"`
    (a tagged variant, e.g. `tp:human-approved:<sha>`). Matching the bare base keeps a
    legacy untagged label *recognized* (so the gate can report it present-but-stale with
    remediation) rather than silently vanishing.

    Total over bad input: non-list, None entries, non-dict entries, missing/None
    "name" keys are all tolerated (skipped), never raise.
    """
    if not isinstance(labels, list):
        return False
    for entry in labels:
        if isinstance(entry, dict):
            nm = entry.get("name")
            if isinstance(nm, str) and (nm == label or nm.startswith(label + ":")):
                return True
    return False


# ============================================================
# Task 1.2: _latest_label_event
# ============================================================


def _latest_label_event(timeline, label: str):
    """The most-recent `labeled` event for `label`, or None.

    Filters event["event"] == "labeled" AND the label name is in the `label` FAMILY
    (name == label OR name startswith `label + ":"`); returns the one with the max
    event["created_at"]. ISO-8601 lexical sort is chronological for the Z-suffixed UTC
    form GitHub returns on this endpoint.

    Total over bad input: non-list timeline, non-dict events, missing label /
    created_at fields are all skipped, never raise. None when no event matches.
    """
    if not isinstance(timeline, list):
        return None
    matches = []
    for event in timeline:
        if not isinstance(event, dict):
            continue
        if event.get("event") != "labeled":
            continue
        lbl = event.get("label")
        if not isinstance(lbl, dict):
            continue
        nm = lbl.get("name")
        if not isinstance(nm, str) or not (nm == label or nm.startswith(label + ":")):
            continue
        if not isinstance(event.get("created_at"), str):
            continue
        matches.append(event)
    if not matches:
        return None
    return max(matches, key=lambda e: e["created_at"])


# ============================================================
# Task 1.3: _committer_logins (F1 REST shape)
# ============================================================


def _committer_logins(commits) -> frozenset:
    """The head commit's GitHub-account committer/author logins (REST shape, F1).

    The REST `gh api repos/{o}/{r}/pulls/{n}/commits` shape carries the login at the
    TOP level of the last entry: commits[-1]["committer"]["login"] and
    ["author"]["login"]. NOT commits[-1]["commit"]["committer"] — that sub-object
    carries name/email/date but NO login (that path is the GraphQL-shape F1 bug and
    yields nothing here).

    Lowercased, falsy/null-account logins dropped. Returns a frozenset (possibly
    empty — a null GitHub-account committer yields no login, handled gracefully).
    Total over non-list / malformed last entry; never raises.

    Used ONLY for the optional ADVISORY detail note (F3) — committer identity is
    never a hard reject.
    """
    if not isinstance(commits, list) or not commits:
        return frozenset()
    last = commits[-1]
    if not isinstance(last, dict):
        return frozenset()
    logins = set()
    for key in ("committer", "author"):
        obj = last.get(key)
        if isinstance(obj, dict):
            login = obj.get("login")
            if isinstance(login, str) and login:
                logins.add(login.lower())
    return frozenset(logins)


# ============================================================
# Task 1.4: automation_identities (hybrid set, D3)
# ============================================================

# GitHub-native automation logins NOT covered by review_readiness's Copilot set.
# (The Copilot logins are reused from review_readiness._REST_COPILOT_LOGINS.)
_GITHUB_NATIVE_AUTOMATION: frozenset = frozenset(
    {
        "github-actions[bot]",
        "github-actions",
        "dependabot[bot]",
    }
)


def automation_identities(*, self_login, config) -> frozenset:
    """Lowercased automation logins the approver must NOT be (D3 hybrid set).

    Base floor = hardcoded known framework/CI bots:
      - review_readiness._REST_COPILOT_LOGINS (copilot[bot], github-copilot[bot],
        copilot-pull-request-reviewer[bot], copilot)
      - the GitHub-native logins (github-actions[bot], github-actions, dependabot[bot])
    PLUS the framework's own gh-authenticated *self* login when truthy (lowercased).
    PLUS any extra logins from config review.automation_identities (list[str]), so an
    org can name its own service accounts (and, for multi-account separation-of-duties,
    its committing CI identity) WITHOUT a code change.

    F2 — self_login is resolved by the CALLER (human_approved_on_head) and an
    UNRESOLVABLE self_login is handled fail-CLOSED there (the caller returns False
    BEFORE building this set), NOT here. This function only ever receives a known
    self_login (or None when the caller is building the set for a detail string).
    Adding a truthy self_login is meaningful because on a user-PAT install the
    framework's apply path would label as that exact self login (actor.type=="User"),
    so without it a self-applied label would pass the human-actor floor.

    Type-safe / total: non-dict config or review, non-list automation_identities are
    ignored gracefully.
    """
    import review_readiness  # noqa: E402 — in _shared/ beside this file

    members = set(review_readiness._REST_COPILOT_LOGINS) | set(_GITHUB_NATIVE_AUTOMATION)

    if isinstance(self_login, str) and self_login:
        members.add(self_login.lower())

    if isinstance(config, dict):
        review = config.get("review")
        if isinstance(review, dict):
            extra = review.get("automation_identities")
            if isinstance(extra, list):
                for login in extra:
                    if isinstance(login, str) and login:
                        members.add(login.lower())

    return frozenset(members)


# ============================================================
# Task 1.5: _actor_is_human (bot/App/automation floor, F2)
# ============================================================


def _is_bot_login(login) -> bool:
    """Catch-all backstop: a `[bot]`-suffixed login is an App/bot actor.

    Covers any unenumerated `[bot]` actor not in the hardcoded automation set.
    Total over non-str input.
    """
    return isinstance(login, str) and login.endswith("[bot]")


def _actor_is_human(event, automation: frozenset) -> bool:
    """Bot/App/automation-login FLOOR for the most-recent label event's actor.

    Requires ALL:
      - actor.type != "Bot"           (App-installation tokens surface as Bot)
      - login (lowercased) ∉ automation (configured/self/known-bot logins)
      - not _is_bot_login(login)       ([bot]-suffix catch-all backstop)

    NOTE (F2): a "User"-type actor on a user-PAT install is NOT proof of a human;
    this is the FLOOR, paired with the mechanical never-applies + auto-strip +
    currency triad for the real spoof proof. Total / fail-closed: missing/malformed
    actor → False, never raises.
    """
    if not isinstance(event, dict):
        return False
    actor = event.get("actor")
    if not isinstance(actor, dict):
        return False
    if actor.get("type") == "Bot":
        return False
    login = actor.get("login")
    if not isinstance(login, str) or not login:
        return False
    login = login.lower()
    if login in automation:
        return False
    if _is_bot_login(login):
        return False
    return True


# ============================================================
# Task 1.6: _approver_not_automation (distinctness, F3)
# ============================================================


def _approver_not_automation(event, automation: frozenset) -> bool:
    """F3 distinctness: the approver is not a PROVABLE automation identity.

    Distinct ⟺ approver.login (lowercased) ∉ automation. The approver MAY equal the
    head committer/author login (the solo-operator case) — committer-equality is
    ADVISORY and does NOT fail this conjunct. This fn deliberately takes NO committer
    parameter: there is NO approver≠committer hard rule (which would make the gate
    un-satisfiable for the single-account operator). A team enforces
    separation-of-duties by naming the committing identity in
    review.automation_identities, which DOES land it in `automation` and hard-rejects.

    Total / fail-closed: missing/malformed actor → False, never raises.
    """
    if not isinstance(event, dict):
        return False
    actor = event.get("actor")
    if not isinstance(actor, dict):
        return False
    login = actor.get("login")
    if not isinstance(login, str) or not login:
        return False
    return login.lower() not in automation


# ============================================================
# Task 1.7: _approval_current_on_head (currency, load-bearing)
# ============================================================


def _approval_current_on_head(event, head) -> bool:
    """Load-bearing currency conjunct: the label event was applied to THIS exact head.

    SOUND BINDING (immutable head OID, carried in the label NAME). GitHub `labeled`
    timeline events ALWAYS carry `commit_id: null` (only commit-associated events like
    reviews get a real SHA), so the prior `commit_id == head_oid` test was structurally
    un-passable via a label — the gate could never reach PASS on a human approval. The
    head SHA is instead carried in the label NAME the human applies:

        tp:human-approved:<sha7+>        (e.g. tp:human-approved:a1b2c3d4e5f6)

    Currency is SHA-PREFIX-EQUALITY: the tag (the part after the family prefix) must be
    a hex prefix of `head["headRefOid"]`. A new head has a different OID, so the prior
    tag no longer prefix-matches and the label is correctly treated as stale.

        current ⟺ tag is hex ∧ len(tag) ≥ 7 ∧ head_oid.lower().startswith(tag.lower())

    Why NOT a timestamp compare (the original, rejected approach): comparing the label's
    `created_at` to the head commit's `committedDate` is UNSOUND — `committedDate` is the
    git committer timestamp, which the autonomous pipeline (the exact actor this gate
    constrains) controls via `GIT_COMMITTER_DATE`; it could back-date a NEW head below a
    PRIOR approval's timestamp and carry that approval onto content no human ever saw.
    The name-carried SHA closes that spoof the same way `commit_id` intended to, but via
    a field GitHub actually populates on label events.

    Case-folded (GitHub returns lowercase hex `headRefOid`; a human may type uppercase).
    Total / fail-closed: a non-dict event, a missing/non-family/bare label name (no tag),
    a non-hex or <7-char tag, a missing/empty `headRefOid`, or any malformed shape →
    False, never raises. (We do NOT fall back to the timestamp compare — fail-closed,
    never fail-open to the forgeable predicate.) A 7-hex prefix collision is ~1/16^7
    (≈268M); the howto recommends a longer tag to shrink it.
    """
    if not isinstance(event, dict):
        return False
    label = event.get("label")
    if not isinstance(label, dict):
        return False
    name = label.get("name")
    if not isinstance(name, str) or not name.startswith(HUMAN_APPROVED_LABEL_PREFIX):
        return False
    tag = name[len(HUMAN_APPROVED_LABEL_PREFIX):].strip().lower()
    if len(tag) < 7 or any(c not in "0123456789abcdef" for c in tag):
        return False
    if not isinstance(head, dict):
        return False
    head_oid = head.get("headRefOid")
    if not isinstance(head_oid, str) or not head_oid:
        return False
    return head_oid.lower().startswith(tag)


# ============================================================
# Task 1.8: live runners (per-key F4) + human_approved_on_head
# ============================================================

# The five runner keys, resolved PER-KEY against live defaults (F4). evaluate_gate
# passes the raw `r = runners or {}` (never None), so a whole-dict `if runners is
# None` fallback would be skipped by the non-None {} and KeyError on first subscript.
# Each key is resolved `(runners or {}).get(k) or _live[k]` instead.
_HUMAN_APPROVAL_KEYS = (
    "labels_fn",
    "timeline_fn",
    "head_fn",
    "commits_fn",
    "self_login_fn",
    "reviews_fn",
)


def _gh_json(args: list) -> object:
    """Run `gh <args>` and parse JSON stdout. Raises on gh failure (fail-CLOSED:
    the caller's per-fetch handling turns a raise into a fail-closed False)."""
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _build_live_runners(pr_url: str) -> dict:
    """Build the five live `*_fn`s (calls live `gh`). Each fails CLOSED — it raises
    on a gh/JSON failure so human_approved_on_head's per-fetch try/except yields a
    fail-closed False (NEVER fail-open). Reuses thread_resolver._parse_pr_url (it is
    intra-_shared/ and on-path, unlike label_manager._parse_pr_url which lives in
    tp-pr-fix/scripts/ off the _shared/ shim)."""
    import thread_resolver  # noqa: E402 — in _shared/ beside this file

    owner, repo, number = thread_resolver._parse_pr_url(pr_url)

    def labels_fn(url: str) -> list:
        payload = _gh_json(["pr", "view", url, "--json", "labels"])
        return (payload or {}).get("labels") or []

    def timeline_fn(url: str) -> list:
        return _gh_json(
            ["api", f"repos/{owner}/{repo}/issues/{number}/timeline", "--paginate"]
        )

    def head_fn(url: str) -> dict:
        return _gh_json(["pr", "view", url, "--json", "headRefOid,commits"])

    def commits_fn(url: str) -> list:
        return _gh_json(
            ["api", f"repos/{owner}/{repo}/pulls/{number}/commits", "--paginate"]
        )

    def self_login_fn() -> str:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh api user failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def reviews_fn(url: str) -> list:
        # REST pulls/<n>/reviews — the proven shape (review_readiness.reviews_fn): each
        # entry carries user.login/user.type/state/commit_id/submitted_at. _gh_json raises
        # on a gh/JSON failure so human_approved_on_head's _safe_fetch yields a fail-closed
        # [] (review path → not satisfied), never fail-open.
        return _gh_json(
            ["api", f"repos/{owner}/{repo}/pulls/{number}/reviews", "--paginate"]
        )

    return {
        "labels_fn": labels_fn,
        "timeline_fn": timeline_fn,
        "head_fn": head_fn,
        "commits_fn": commits_fn,
        "self_login_fn": self_login_fn,
        "reviews_fn": reviews_fn,
    }


def _safe_fetch(fn, *args, default):
    """Call fn(*args); on any raise OR a result whose type doesn't match `default`'s
    type return `default` (fail-closed). Used for the four list/dict fetches."""
    try:
        result = fn(*args)
    except Exception:
        return default
    if not isinstance(result, type(default)):
        return default
    return result


def human_approved_on_head(pr_url: str, *, runners=None, config=None) -> bool:
    """True ⟺ a HUMAN (not bot/automation) has a CURRENT approval on THIS head.

    DUAL PATH (review-as-human-approval): satisfied by EITHER an APPROVED native PR
    review current on the head (Path B, primary — `human_approval_review`) OR the
    SHA-tagged label (Path A, single-account fallback — the conjuncts below). Both paths
    reuse the same `automation` identity set, so bot/App/self-login rejection is identical
    across them; either path alone is sufficient, and the predicate stays total/fail-closed.

    Path A — all BINDING conjuncts must hold:
      1. the `tp:human-approved` label is currently present;
      2. the most-recent `labeled` event for it is a human actor (bot/App/automation
         floor — F2); AND
      3. that event is current on the head SHA (event.commit_id == head.headRefOid —
         SHA-equality on the immutable head OID, NOT a forgeable committer timestamp);
    PLUS the defense-in-depth distinctness conjunct (F3):
      4. the approver login ∉ the automation set (committer-equality is ADVISORY, the
         solo single-account operator is satisfiable).

    F4 per-key live-default wiring: each runner key is resolved `(runners or {}).get(k)
    or _live[k]` — never a whole-dict None fallback (evaluate_gate passes a non-None {}).

    F2 fail-CLOSED self: the FIRST thing done after wiring is resolve
    `self_login = self_login_fn()`; if it raises or is falsy, return False immediately
    (→ INDETERMINATE at the gate). We do NOT shrink the automation set and proceed
    (that would fail-OPEN on a user-PAT install).

    Total — NEVER raises (the gate predicate wraps it anyway, but this is total too).
    Any failed conjunct, any fetch failure, any ambiguity → False (fail-closed).
    """
    try:
        provided = runners or {}
        live = None

        def _resolve(key):
            nonlocal live
            fn = provided.get(key)
            if fn is not None:
                return fn
            if live is None:
                live = _build_live_runners(pr_url)
            return live[key]

        labels_fn = _resolve("labels_fn")
        timeline_fn = _resolve("timeline_fn")
        head_fn = _resolve("head_fn")
        commits_fn = _resolve("commits_fn")
        self_login_fn = _resolve("self_login_fn")
        reviews_fn = _resolve("reviews_fn")

        # F2: self login is REQUIRED-resolvable. Unresolvable → fail-CLOSED.
        try:
            self_login = self_login_fn()
        except Exception:
            return False
        if not self_login or not isinstance(self_login, str):
            return False

        automation = automation_identities(self_login=self_login, config=config)

        labels = _safe_fetch(labels_fn, pr_url, default=[])
        timeline = _safe_fetch(timeline_fn, pr_url, default=[])
        head = _safe_fetch(head_fn, pr_url, default={})
        # commits is advisory-only (F3 detail note); a failure must not block.
        _safe_fetch(commits_fn, pr_url, default=[])
        reviews = _safe_fetch(reviews_fn, pr_url, default=[])

        # ---- Path A: SHA-tagged label (single-account fallback) ----
        # Computed as a boolean (NOT an early return) so Path B is still evaluated when
        # the label is absent. The conjuncts are byte-identical to the original tail.
        label_ok = False
        if _label_present(labels, HUMAN_APPROVED_LABEL):
            ev = _latest_label_event(timeline, HUMAN_APPROVED_LABEL)
            if ev:
                label_ok = bool(
                    _actor_is_human(ev, automation)
                    and _approver_not_automation(ev, automation)
                    and _approval_current_on_head(ev, head)
                )

        # ---- Path B: native APPROVED review (primary, low-friction) ----
        # Lazy import (mirrors the review_readiness/thread_resolver lazy-import style and
        # avoids the human_approval_review -> human_approval import cycle). Reuses the same
        # `automation` set built above, so identity rejection is identical across paths.
        import human_approval_review  # noqa: E402 — in _shared/ beside this file

        review_ok = human_approval_review.review_path_satisfied(
            reviews, head, automation=automation
        )

        return label_ok or review_ok
    except Exception:
        return False


# ============================================================
# Task 3.1: strip_stale_approval (REST DELETE, fail-open, D2)
# ============================================================


def strip_stale_approval(pr_url: str, head_oid: str, *, runners=None) -> bool:
    """Remove `tp:human-approved` when the present label is NOT current on head_oid.

    This is the push-time write site (D2): after a push advances the PR head, the
    previously-applied human approval is stale and must be cleared to keep the GitHub
    UI honest about what is authorized. It mirrors GitHub's dismiss-stale-reviews.

    Idempotent and fail-OPEN on its OWN errors: a strip-helper failure (fetch error,
    DELETE failure, malformed URL, label already absent / 404) returns False and NEVER
    raises — a strip failure must not block a push. The GATE remains the independent
    fail-CLOSED backstop: even if the strip never runs, `pred_human_approved` re-checks
    currency at gate time and treats a pre-head label as stale (INDETERMINATE). The
    strip is defense-in-depth convenience, NOT the sole correctness mechanism.

    Returns True iff it removed the label; False otherwise (absent / already current /
    no provable staleness / any error). The removal uses the REST issues/labels DELETE
    endpoint, never `gh pr edit` (mirrors label_manager._add_label_rest's
    classic-Projects-safe REST choice):

        gh api --method DELETE repos/{owner}/{repo}/issues/{number}/labels/tp:human-approved

    Runner keys (test seam; live defaults wired PER-KEY when absent, mirroring
    human_approved_on_head's F4 resolution): `labels_fn`, `timeline_fn`. Staleness is
    judged against the passed `head_oid` (the just-pushed head SHA) by SHA-PREFIX-equality
    with the tag carried in the approving label's NAME (`tp:human-approved:<sha7+>`) — no
    `head_fn` fetch is needed, removing the benign TOCTOU window where the live head could
    race ahead of the pushed head. The DELETE targets the EXACT present label name (the
    tagged name), not the bare family base — a bare-base DELETE would no-op on tagged labels.
    """
    try:
        provided = runners or {}
        live = None

        def _resolve(key):
            nonlocal live
            fn = provided.get(key)
            if fn is not None:
                return fn
            if live is None:
                live = _build_live_runners(pr_url)
            return live[key]

        labels_fn = _resolve("labels_fn")
        timeline_fn = _resolve("timeline_fn")

        # Each fetch is fail-OPEN-to-no-action: a fetch error means we CANNOT prove
        # the label is stale, so we do NOT strip (return False). This differs from the
        # read path's _safe_fetch-to-default — defaulting to a value that looks "stale"
        # could trigger a spurious DELETE.
        labels = labels_fn(pr_url)
        # Idempotent: the label isn't present -> nothing to strip.
        if not _label_present(labels, HUMAN_APPROVED_LABEL):
            return False

        timeline = timeline_fn(pr_url)

        ev = _latest_label_event(timeline, HUMAN_APPROVED_LABEL)
        # No provable label event -> cannot reason about staleness -> conservatively
        # do NOT strip (the gate re-check remains the fail-closed backstop).
        if not ev:
            return False

        # Bind currency to the IMMUTABLE head OID we were handed (the just-pushed head),
        # NOT a re-fetched/timestamp-derived value. The label is stale ⟺ the approving
        # event's server-stamped commit_id != the new head_oid. We require a concrete
        # head_oid to act: an empty/missing head_oid means we CANNOT prove staleness, so
        # fail-OPEN-to-no-action (do NOT strip). A non-matching commit_id is provable
        # staleness; a matching one means the approval is still current -> nothing to do.
        if not isinstance(head_oid, str) or not head_oid:
            return False
        if _approval_current_on_head(ev, {"headRefOid": head_oid}):
            return False

        # Stale: remove the label via the REST DELETE endpoint. Fail-OPEN — a DELETE
        # failure (non-zero return / raise / 404 already-absent) must not propagate.
        import thread_resolver  # noqa: E402 — in _shared/ beside this file

        owner, repo, number = thread_resolver._parse_pr_url(pr_url)
        # DELETE the EXACT present label name (the tagged variant), not the bare base —
        # a hardcoded `/labels/tp:human-approved` would no-op on `tp:human-approved:<sha>`.
        lbl = ev.get("label") if isinstance(ev, dict) else None
        del_name = lbl.get("name") if isinstance(lbl, dict) else None
        if not isinstance(del_name, str) or not del_name.startswith(HUMAN_APPROVED_LABEL):
            return False
        endpoint = (
            f"repos/{owner}/{repo}/issues/{number}/labels/{del_name}"
        )
        result = subprocess.run(
            ["gh", "api", "--method", "DELETE", endpoint],
            capture_output=True,
            text=True,
            check=False,
        )
        # A non-zero return (e.g. 404 label already absent) is tolerated — idempotent,
        # fail-open. We only report True when the DELETE succeeded.
        return result.returncode == 0
    except Exception:
        # fail-OPEN: never raise out of the strip path.
        return False


# ============================================================
# Task 2.1: _require_human_approval config interpreter (D4)
# ============================================================


def _require_human_approval(config) -> bool:
    """Whether the human-approval predicate is REQUIRED on this repo's PRs (D4).

    Reads `review.require_human_approval` from .three-pillars/config.json (threaded
    in as `config`). Default True (strict): a missing subsection, a missing key, a
    non-dict `review`, or a None/absent config ALL fold to True so a missing/corrupt
    config NEVER relaxes the gate. ONLY an explicit `review.require_human_approval:
    false` opts the repo out (the human-approval predicate is then OMITTED from the
    fold, restoring the pre-existing predicate set verbatim — backward-compat).

    Mirrors `loop_driver._expects_copilot_review` semantics. Type-safe: any non-dict
    `review` falls back to the strict default rather than raising on `.get`.
    """
    review = (config or {}).get("review") if isinstance(config, dict) else None
    if not isinstance(review, dict):
        return True
    return bool(review.get("require_human_approval", True))
