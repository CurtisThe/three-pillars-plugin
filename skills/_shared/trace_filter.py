"""trace_filter.py — Fail-closed secret/PII filter (OD-8 security floor).

Public API:
  redact(value: Any) -> Any
      Recursively walk dict/list/str; return a redacted copy (never mutates
      input). Delegates to redact_with_report and discards the counts.

  redact_with_report(value: Any) -> tuple[Any, dict[str, int]]
      Return (redacted_copy, counts) where counts tallies:
        "secret"        — value-level credential pattern matches
        "sensitive-key" — key-level blanking
        "fail-closed"   — unknown type or any error during walk

Behaviors:
  - Secret patterns (value-level): env-var assignments, Authorization:/Bearer/
    token= headers, ghp_/gho_/ghs_/ghr_/ghu_/github_pat_/sk-/AKIA prefix
    tokens → "[REDACTED:secret]". URL userinfo credentials and PEM private-key
    blocks are also redacted as whole-value matches.
    For whole-value patterns (Authorization:, Bearer, token=, URL userinfo,
    private-key blocks), the entire string is replaced. For prefix-token
    patterns (ghp_ family, sk-, AKIA, env-var), only the matched token is
    substituted so surrounding text is preserved.
  - Dict keys: if a key string itself contains a credential pattern, the key
    is replaced by a redacted key in the output dict. The original key name
    is still used for sensitive-key VALUE-blanking checks (password, token,
    etc.), so a key named `password` still has its value blanked even if
    its own text is not a credential token.
  - Sensitive keys (key-level): password, token, secret, authorization,
    api_key, credential, notion_*, task_body, design_draft, prompt,
    response_body → value replaced with "[REDACTED:sensitive-key]"
  - Fail-closed: unknown types or any error → "[REDACTED:fail-closed]"
  - Pure function, stdlib-only, zero I/O.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Compile credential patterns once at module load (value-level redaction)
# ---------------------------------------------------------------------------

# Whole-value patterns: if any of these match anywhere in the string, the
# ENTIRE string value is replaced with [REDACTED:secret].
_WHOLE_VALUE_PATTERNS = [
    # Authorization header line
    re.compile(r"(?i)^authorization\s*:", re.IGNORECASE),
    # Bearer token (may appear as value without "Authorization:" prefix)
    re.compile(r"(?i)\bbearer\s+\S+"),
    # token= query param or config value
    re.compile(r"(?i)\btoken\s*=\s*\S+"),
    # URL userinfo: scheme://user:pass@host — redact entire string
    re.compile(r"[a-zA-Z][a-zA-Z0-9+\-.]*://[^@\s/]+:[^@\s/]+@"),
    # PEM private-key block (single-line or multi-line)
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

# Substitution patterns: these replace only the MATCHED TOKEN within the
# string (word-boundary-aware), preserving surrounding non-secret text.
# Each tuple is (compiled_pattern_for_sub, description).
# Using \b at the start ensures we match token boundaries.
# The replacement is [REDACTED:secret] for each matched span.
_SUBSTITUTION_PATTERNS = [
    # GitHub fine-grained PAT (github_pat_ prefix) — check BEFORE gh[posru]_ family
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    # GitHub token family: classic (ghp_), OAuth (gho_), server-to-server (ghs_),
    # refresh (ghr_), and user-to-server (ghu_)
    re.compile(r"\bgh[posru]_[A-Za-z0-9]{36,}"),
    # OpenAI / Anthropic style secret key (sk- prefix)
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    # AWS access key ID (AKIA prefix)
    re.compile(r"\bAKIA[A-Z0-9]{16,}"),
    # Environment variable assignment with high-entropy value:
    # SOME_KEY=<value> where value may contain base64 padding, dashes, dots, slashes
    re.compile(r"(?<!\w)[A-Z][A-Z0-9_]{2,}=[A-Za-z0-9+/=\-_.]{16,}"),
]

# ---------------------------------------------------------------------------
# Sensitive key predicate (key-level redaction)
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS_EXACT = frozenset({
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "credential",
    "task_body",
    "design_draft",
    "prompt",
    "response_body",
})

_SENSITIVE_KEY_PREFIX = "notion_"


def _is_sensitive_key(key: str) -> bool:
    """Return True if the dict key name warrants value-level blanking."""
    lower = key.lower()
    return lower in _SENSITIVE_KEYS_EXACT or lower.startswith(_SENSITIVE_KEY_PREFIX)


# ---------------------------------------------------------------------------
# Core walk — internal, counter-threaded
# ---------------------------------------------------------------------------

_MARKER_SECRET = "[REDACTED:secret]"
_MARKER_SENSITIVE = "[REDACTED:sensitive-key]"
_MARKER_FAIL_CLOSED = "[REDACTED:fail-closed]"


def _redact_string(value: str, counts: dict[str, int]) -> str:
    """Redact a single string value, returning a redacted copy.

    Two-pass strategy:
    1. Check whole-value patterns — if any match, replace the whole string.
    2. Apply substitution patterns — replace embedded tokens in-place,
       preserving surrounding text. Each substitution increments the counter.
    """
    # Pass 1: whole-value replacement (existing behavior for Authorization/Bearer/token=)
    for pattern in _WHOLE_VALUE_PATTERNS:
        if pattern.search(value):
            counts["secret"] = counts.get("secret", 0) + 1
            return _MARKER_SECRET

    # Pass 2: substitution of embedded prefix-tokens
    result = value
    for pattern in _SUBSTITUTION_PATTERNS:
        new, n = pattern.subn(_MARKER_SECRET, result)
        if n > 0:
            counts["secret"] = counts.get("secret", 0) + n
            result = new

    return result


def _walk(value: Any, counts: dict[str, int]) -> Any:
    """Recursively walk value, incrementing counts, and return a redacted copy."""
    try:
        # bool must be tested before int (bool is a subclass of int)
        if value is None or isinstance(value, (bool, int, float)):
            return value

        if isinstance(value, str):
            return _redact_string(value, counts)

        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for k, v in value.items():
                # Redact the key string itself if it contains a credential token.
                # Use the ORIGINAL key name for the sensitive-key value-blanking
                # check so that `password`, `token`, etc. still blank their values.
                try:
                    out_key = _redact_string(str(k), counts) if isinstance(k, str) else k
                except Exception:  # noqa: BLE001
                    counts["fail-closed"] = counts.get("fail-closed", 0) + 1
                    out_key = _MARKER_FAIL_CLOSED

                # Collision-safe: if the redacted key already exists in result
                # (two distinct secrets both redact to the same marker), append
                # a numeric suffix so no entry is silently overwritten.
                if out_key in result:
                    suffix = 2
                    while f"{out_key}#{suffix}" in result:
                        suffix += 1
                    out_key = f"{out_key}#{suffix}"

                if _is_sensitive_key(k) if isinstance(k, str) else False:
                    counts["sensitive-key"] = counts.get("sensitive-key", 0) + 1
                    result[out_key] = _MARKER_SENSITIVE
                else:
                    result[out_key] = _walk(v, counts)
            return result

        if isinstance(value, list):
            return [_walk(item, counts) for item in value]

        # Unrecognized type — fail closed
        counts["fail-closed"] = counts.get("fail-closed", 0) + 1
        return _MARKER_FAIL_CLOSED

    except Exception:  # noqa: BLE001
        counts["fail-closed"] = counts.get("fail-closed", 0) + 1
        return _MARKER_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def redact_with_report(value: Any) -> tuple[Any, dict[str, int]]:
    """Return (redacted_copy, counts_dict) without mutating the input."""
    counts: dict[str, int] = {}
    redacted = _walk(value, counts)
    return redacted, counts


def redact(value: Any) -> Any:
    """Return a redacted copy of value; discard the report counts."""
    redacted, _ = redact_with_report(value)
    return redacted
