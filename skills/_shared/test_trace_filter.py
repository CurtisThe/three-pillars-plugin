"""test_trace_filter.py — Tests for trace_filter.redact / redact_with_report.

Split by task:
  - test_redacts_secret_value_shapes      (Task 1.1)
  - test_redacts_sensitive_keys_and_recurses (Task 1.2)
  - test_fails_closed_and_reports         (Task 1.3)
"""

import copy
import trace_filter


# ---------------------------------------------------------------------------
# Task 1.1: Value-level secret redaction
# ---------------------------------------------------------------------------

class TestRedactsSecretValueShapes:
    """Task 1.1 — string values matching credential patterns are redacted."""

    def test_bearer_header_redacted(self):
        val = "Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.sig"
        assert trace_filter.redact(val) == "[REDACTED:secret]"

    def test_authorization_header_redacted(self):
        val = "Authorization: Bearer some-token-value"
        assert trace_filter.redact(val) == "[REDACTED:secret]"

    def test_token_eq_param_redacted(self):
        val = "token=abc123secretvalue"
        assert trace_filter.redact(val) == "[REDACTED:secret]"

    def test_ghp_prefix_token_redacted(self):
        # Build at runtime to avoid tripping the repo secret scanner
        val = "ghp_" + "A" * 36
        assert trace_filter.redact(val) == "[REDACTED:secret]"

    def test_sk_prefix_token_redacted(self):
        val = "sk-" + "a" * 48
        assert trace_filter.redact(val) == "[REDACTED:secret]"

    def test_akia_prefix_token_redacted(self):
        # AWS access key ID shape
        val = "AKIA" + "A" * 16
        assert trace_filter.redact(val) == "[REDACTED:secret]"

    def test_env_var_value_shape_redacted(self):
        # High-entropy env var assignment — built at runtime to avoid scanner
        # Pattern: ALL_CAPS_KEY=<base62-ish value with 20+ chars>
        entropy_val = "xK9pL2mZ" + "Qr8vNtWs" + "3FjHdEaY"
        val = "MY_SECRET_KEY=" + entropy_val
        assert trace_filter.redact(val) == "[REDACTED:secret]"

    def test_clean_string_unchanged(self):
        val = "hello world, this is a clean string with no secrets"
        assert trace_filter.redact(val) == val

    def test_empty_string_unchanged(self):
        assert trace_filter.redact("") == ""

    def test_short_word_unchanged(self):
        assert trace_filter.redact("ok") == "ok"

    def test_normal_sentence_unchanged(self):
        val = "The design is complete and ready for review."
        assert trace_filter.redact(val) == val


# ---------------------------------------------------------------------------
# Task 1.2: Key-level blanking + non-mutation + recursion
# ---------------------------------------------------------------------------

class TestRedactsSensitiveKeysAndRecurses:
    """Task 1.2 — sensitive dict keys blanked; input not mutated; recursion."""

    def test_password_key_blanked(self):
        result = trace_filter.redact({"password": "hunter2"})
        assert result["password"] == "[REDACTED:sensitive-key]"

    def test_token_key_blanked(self):
        result = trace_filter.redact({"token": "abc123"})
        assert result["token"] == "[REDACTED:sensitive-key]"

    def test_secret_key_blanked(self):
        result = trace_filter.redact({"secret": "mysecret"})
        assert result["secret"] == "[REDACTED:sensitive-key]"

    def test_authorization_key_blanked(self):
        result = trace_filter.redact({"authorization": "Bearer x"})
        assert result["authorization"] == "[REDACTED:sensitive-key]"

    def test_api_key_blanked(self):
        result = trace_filter.redact({"api_key": "some-key"})
        assert result["api_key"] == "[REDACTED:sensitive-key]"

    def test_credential_key_blanked(self):
        result = trace_filter.redact({"credential": "secret"})
        assert result["credential"] == "[REDACTED:sensitive-key]"

    def test_notion_prefix_key_blanked(self):
        result = trace_filter.redact({"notion_token": "ntn_xxxx"})
        assert result["notion_token"] == "[REDACTED:sensitive-key]"

    def test_notion_any_suffix_blanked(self):
        result = trace_filter.redact({"notion_database_id": "some-id"})
        assert result["notion_database_id"] == "[REDACTED:sensitive-key]"

    def test_task_body_key_blanked(self):
        result = trace_filter.redact({"task_body": "do some work"})
        assert result["task_body"] == "[REDACTED:sensitive-key]"

    def test_design_draft_key_blanked(self):
        result = trace_filter.redact({"design_draft": "draft content"})
        assert result["design_draft"] == "[REDACTED:sensitive-key]"

    def test_prompt_key_blanked(self):
        result = trace_filter.redact({"prompt": "tell me about..."})
        assert result["prompt"] == "[REDACTED:sensitive-key]"

    def test_response_body_key_blanked(self):
        result = trace_filter.redact({"response_body": "some response"})
        assert result["response_body"] == "[REDACTED:sensitive-key]"

    def test_case_insensitive_key_match(self):
        result = trace_filter.redact({"PASSWORD": "hunter2"})
        assert result["PASSWORD"] == "[REDACTED:sensitive-key]"

    def test_non_sensitive_key_unchanged(self):
        result = trace_filter.redact({"name": "Alice", "age": 30})
        assert result["name"] == "Alice"
        assert result["age"] == 30

    def test_nested_dict_recursion(self):
        obj = {"outer": {"password": "secret", "clean": "value"}}
        result = trace_filter.redact(obj)
        assert result["outer"]["password"] == "[REDACTED:sensitive-key]"
        assert result["outer"]["clean"] == "value"

    def test_list_recursion(self):
        obj = [{"token": "abc"}, {"name": "clean"}]
        result = trace_filter.redact(obj)
        assert result[0]["token"] == "[REDACTED:sensitive-key]"
        assert result[1]["name"] == "clean"

    def test_deeply_nested(self):
        obj = {"a": {"b": {"c": {"password": "deep-secret"}}}}
        result = trace_filter.redact(obj)
        assert result["a"]["b"]["c"]["password"] == "[REDACTED:sensitive-key]"

    def test_input_dict_not_mutated(self):
        original = {"password": "hunter2", "name": "Alice"}
        original_copy = copy.deepcopy(original)
        trace_filter.redact(original)
        assert original == original_copy

    def test_input_list_not_mutated(self):
        original = [{"token": "secret"}, "clean"]
        original_copy = copy.deepcopy(original)
        trace_filter.redact(original)
        assert original == original_copy

    def test_mixed_list_in_dict(self):
        obj = {"items": [{"password": "p"}, "clean", 42]}
        result = trace_filter.redact(obj)
        assert result["items"][0]["password"] == "[REDACTED:sensitive-key]"
        assert result["items"][1] == "clean"
        assert result["items"][2] == 42


# ---------------------------------------------------------------------------
# Task 1.3: Fail-closed on error/unknown type + redaction report
# ---------------------------------------------------------------------------

class TestFailsClosedAndReports:
    """Task 1.3 — unknown types and errors yield fail-closed marker; report."""

    def test_unknown_type_fails_closed(self):
        # An object type that is not str/dict/list/int/float/bool/None
        class Weird:
            pass
        result = trace_filter.redact(Weird())
        assert result == "[REDACTED:fail-closed]"

    def test_none_passes_through(self):
        assert trace_filter.redact(None) is None

    def test_int_passes_through(self):
        assert trace_filter.redact(42) == 42

    def test_float_passes_through(self):
        assert trace_filter.redact(3.14) == 3.14

    def test_bool_passes_through(self):
        assert trace_filter.redact(True) is True
        assert trace_filter.redact(False) is False

    def test_redact_with_report_returns_tuple(self):
        result, counts = trace_filter.redact_with_report("clean string")
        assert isinstance(counts, dict)
        assert result == "clean string"

    def test_report_counts_secret(self):
        val = "ghp_" + "B" * 36
        _, counts = trace_filter.redact_with_report(val)
        assert counts.get("secret", 0) >= 1

    def test_report_counts_sensitive_key(self):
        obj = {"password": "hunter2"}
        _, counts = trace_filter.redact_with_report(obj)
        assert counts.get("sensitive-key", 0) >= 1

    def test_report_counts_fail_closed(self):
        class Weird:
            pass
        _, counts = trace_filter.redact_with_report(Weird())
        assert counts.get("fail-closed", 0) >= 1

    def test_report_counts_are_cumulative(self):
        obj = {
            "password": "p",
            "token": "t",
            "name": "clean",
        }
        _, counts = trace_filter.redact_with_report(obj)
        assert counts.get("sensitive-key", 0) >= 2

    def test_redact_delegates_to_with_report(self):
        # redact(x) == redact_with_report(x)[0] for any input
        inputs = [
            "clean",
            {"password": "x"},
            ["ghp_" + "c" * 36, "clean"],
            42,
            None,
        ]
        for inp in inputs:
            assert trace_filter.redact(inp) == trace_filter.redact_with_report(inp)[0]

    def test_zero_counts_when_nothing_redacted(self):
        obj = {"name": "Alice", "age": 30}
        _, counts = trace_filter.redact_with_report(obj)
        total = sum(counts.values())
        assert total == 0


# ---------------------------------------------------------------------------
# OD-8 embedded-token redaction (substitution, not whole-value blanking)
# ---------------------------------------------------------------------------

class TestEmbeddedTokenRedaction:
    """Tokens embedded inside longer strings are redacted by substitution.

    These are the regression cases for the OD-8 leak: a credential token
    inside a larger value (e.g. summary/notes field) must be removed from
    the output, and surrounding non-secret text must be preserved.
    """

    def test_ghp_embedded_mid_string(self):
        """ghp_ token inside a summary field is redacted; surrounding text kept."""
        token = "ghp_" + "x" * 36  # runtime build avoids gitleaks hook
        result = trace_filter.redact("worker used token " + token + " to push")
        assert token not in result, "ghp_ embedded token must be redacted"
        assert "worker used token" in result, "prefix text before token must survive"
        assert "to push" in result, "suffix text after token must survive"
        assert "[REDACTED:secret]" in result

    def test_ghp_embedded_in_dict_value(self):
        """ghp_ token in a non-sensitive dict value is redacted."""
        token = "ghp_" + "A" * 36
        result = trace_filter.redact({"summary": "used " + token + " here"})
        assert token not in result["summary"]
        assert "[REDACTED:secret]" in result["summary"]
        assert "used" in result["summary"]
        assert "here" in result["summary"]

    def test_sk_embedded_mid_string(self):
        """sk- token embedded inside a longer string is redacted."""
        token = "sk-" + "b" * 48
        result = trace_filter.redact("api key is " + token + " end")
        assert token not in result
        assert "[REDACTED:secret]" in result
        assert "api key is" in result
        assert "end" in result

    def test_akia_embedded_mid_string(self):
        """AKIA token embedded inside a longer string is redacted."""
        token = "AKIA" + "B" * 16
        result = trace_filter.redact("aws key=" + token + " loaded")
        assert token not in result
        assert "[REDACTED:secret]" in result
        assert "aws key=" in result
        assert "loaded" in result

    def test_env_var_value_embedded(self):
        """Env-var assignment embedded in surrounding text is redacted."""
        envval = "MY_SECRET_KEY=" + "xK9pL2mZ" + "Qr8vNtWs" + "3FjHdEaY"
        result = trace_filter.redact("config: " + envval + " loaded")
        assert envval not in result
        assert "[REDACTED:secret]" in result

    def test_ghp_embedded_count_increments(self):
        """Embedded ghp_ increments secret count."""
        token = "ghp_" + "C" * 36
        _, counts = trace_filter.redact_with_report("prefix " + token + " suffix")
        assert counts.get("secret", 0) >= 1

    def test_multiple_tokens_in_one_string(self):
        """Two embedded tokens in one string are both redacted."""
        t1 = "ghp_" + "D" * 36
        t2 = "ghp_" + "E" * 36
        result = trace_filter.redact("first=" + t1 + " second=" + t2)
        assert t1 not in result
        assert t2 not in result
        assert result.count("[REDACTED:secret]") >= 2

    def test_multiple_tokens_count_each(self):
        """Each embedded token increments the count separately."""
        t1 = "ghp_" + "F" * 36
        t2 = "ghp_" + "G" * 36
        _, counts = trace_filter.redact_with_report("a=" + t1 + " b=" + t2)
        assert counts.get("secret", 0) >= 2

    def test_clean_string_not_altered_by_substitution(self):
        """A clean string with no credential tokens is returned unchanged."""
        val = "everything looks fine here"
        result = trace_filter.redact(val)
        assert result == val

    def test_sk_standalone_still_whole_redacted(self):
        """Standalone sk- token (no surrounding text) is still redacted."""
        token = "sk-" + "h" * 24
        result = trace_filter.redact(token)
        assert result == "[REDACTED:secret]"

    def test_embedded_token_in_nested_dict(self):
        """Embedded token survives recursion into nested dict."""
        token = "ghp_" + "H" * 36
        result = trace_filter.redact({"outer": {"notes": "leaked " + token + " here"}})
        assert token not in result["outer"]["notes"]
        assert "[REDACTED:secret]" in result["outer"]["notes"]
        assert "leaked" in result["outer"]["notes"]
        assert "here" in result["outer"]["notes"]

    def test_embedded_token_in_list(self):
        """Embedded token inside list items is redacted."""
        token = "ghp_" + "I" * 36
        result = trace_filter.redact(["clean", "prefix " + token + " suffix"])
        assert token not in result[1]
        assert "[REDACTED:secret]" in result[1]
        assert result[0] == "clean"
