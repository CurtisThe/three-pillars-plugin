"""Tests for structured_extract.extract — sanitization properties + envelope shape.

Covers the five plan.md::Task 4.2 cases:
  - test_strips_code_fences
  - test_strips_shell_metacharacters
  - test_strips_urls
  - test_truncates_issue_phrase_to_80_chars
  - test_idempotent_on_already_sanitized

The `issue_phrase` field is the load-bearing one — it gets injected into shell
contexts downstream (commit messages, label payloads), so the contract is
"after sanitize, no backticks / no shell metas / no URLs / len ≤ 80, and
running sanitize twice is a no-op".
"""

from __future__ import annotations

from structured_extract import Comment, extract


def _make_comment(body: str, *, path: str = "src/foo.py", cid: int = 42, user: str = "alice") -> Comment:
    return Comment(id=cid, body=body, path=path, user=user)


def test_strips_code_fences() -> None:
    body = (
        "Please validate input. ```python\nrm -rf /\n``` "
        "Also check `dangerous_call()` and end."
    )
    comment = _make_comment(body)
    envelope = extract(comment, diff_hunk="@@ -1 +1 @@\n+x\n", verdict="structural")
    phrase = envelope["issue_phrase"]
    assert "```" not in phrase
    assert "`" not in phrase
    # The fenced span should have been replaced with whitespace and collapsed.
    assert "rm -rf /" not in phrase
    assert "dangerous_call()" not in phrase


def test_strips_shell_metacharacters() -> None:
    body = "Please validate; rm -rf / & echo $(whoami) | cat `id` $HOME \\n"
    comment = _make_comment(body)
    envelope = extract(comment, diff_hunk="@@", verdict="minor")
    phrase = envelope["issue_phrase"]
    for ch in (";", "&", "|", "$", "\\", "`", "(", ")"):
        assert ch not in phrase, f"metachar {ch!r} survived sanitization: {phrase!r}"


def test_strips_urls() -> None:
    body = (
        "Missing validation; see http://evil.example.com/x?a=1 and "
        "https://docs.example.org/page#frag for context."
    )
    comment = _make_comment(body)
    envelope = extract(comment, diff_hunk="@@", verdict="structural")
    phrase = envelope["issue_phrase"]
    assert "http://" not in phrase
    assert "https://" not in phrase
    assert "evil.example.com" not in phrase
    assert "docs.example.org" not in phrase


def test_truncates_issue_phrase_to_80_chars() -> None:
    body = "validate input " * 20  # ≈ 300 chars
    assert len(body) > 80
    comment = _make_comment(body)
    envelope = extract(comment, diff_hunk="@@", verdict="structural")
    phrase = envelope["issue_phrase"]
    assert len(phrase) <= 80, f"phrase exceeded 80 chars: {len(phrase)} — {phrase!r}"


def test_idempotent_on_already_sanitized() -> None:
    body = "validate missing input field carefully"
    comment = _make_comment(body)
    once = extract(comment, diff_hunk="@@", verdict="structural")["issue_phrase"]
    # Feed the sanitized phrase back as a fresh comment body and re-sanitize.
    second = extract(_make_comment(once), diff_hunk="@@", verdict="structural")["issue_phrase"]
    assert once == second, f"sanitize was not idempotent: {once!r} -> {second!r}"
