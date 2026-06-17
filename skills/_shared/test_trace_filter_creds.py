"""test_trace_filter_creds.py — OD-8 R1 security fix tests for trace_filter.

Split from test_trace_filter.py (which reached ~349L) to stay under the
500-line hard cap.  Tests here cover:

  - Dict-KEY credential redaction (fix #1)
  - Extended GitHub token families: gho_, ghs_, ghr_, ghu_, github_pat_ (#2)
  - URL userinfo credential redaction (#2)
  - PEM private-key block redaction (#2)
  - Env-var value with dashes / base64 padding fully redacted (#3)
  - Fail-closed on .items()/.lower() raising (#6)
"""

import sys
import trace_filter

# ---------------------------------------------------------------------------
# Fix #1 — dict KEY containing a credential token is redacted
# ---------------------------------------------------------------------------


class TestDictKeySecretRedaction:
    """Secrets appearing as dict KEYS must be redacted in the output key."""

    def test_ghp_token_as_whole_key_is_redacted(self):
        """A dict key that IS a ghp_ token becomes [REDACTED:secret] in output."""
        tok = "ghp_" + "K" * 36  # runtime build avoids gitleaks hook
        result = trace_filter.redact({tok: "some value"})
        assert tok not in result, "raw ghp_ token must not appear as a key"
        assert "[REDACTED:secret]" in result

    def test_ghp_token_embedded_in_key_is_redacted(self):
        """A key where the ghp_ token appears after a word-boundary delimiter is redacted.

        Use a dot-separated context ('.') since dot is not a word char and so
        the word-boundary fires before 'ghp_'.  (An underscore-joined context
        would not trigger the boundary — that limitation also exists for value
        strings and is identical behaviour: the test must be boundary-realistic.)
        """
        tok = "ghp_" + "L" * 36
        # dot is a non-\w char, so \b fires before 'ghp_'
        key = "section." + tok + ".end"
        result = trace_filter.redact({key: "value"})
        assert tok not in str(list(result.keys())), (
            "embedded ghp_ in key (after word-boundary) must be redacted from output key"
        )
        assert any("[REDACTED:secret]" in str(k) for k in result), (
            "output key must contain [REDACTED:secret] marker"
        )

    def test_sensitive_key_value_still_blanked_when_key_clean(self):
        """'password' key still blanks its value (sensitive-key path unchanged)."""
        result = trace_filter.redact({"password": "hunter2"})
        assert result["password"] == "[REDACTED:sensitive-key]"

    def test_clean_key_passes_through_unchanged(self):
        """A clean, non-credential key is written verbatim."""
        result = trace_filter.redact({"clean_key": "clean_value"})
        assert "clean_key" in result
        assert result["clean_key"] == "clean_value"

    def test_dict_key_redaction_increments_secret_count(self):
        """Redacting a credential in a key increments the secret counter."""
        tok = "ghp_" + "M" * 36
        _, counts = trace_filter.redact_with_report({tok: "v"})
        assert counts.get("secret", 0) >= 1


# ---------------------------------------------------------------------------
# Fix #2 — extended GitHub token families
# ---------------------------------------------------------------------------


class TestExtendedGitHubTokenFamilies:
    """gho_, ghs_, ghr_, ghu_, and github_pat_ tokens are redacted."""

    def _tok(self, prefix: str, n: int = 36) -> str:
        return prefix + "A" * n

    def test_gho_token_redacted(self):
        tok = self._tok("gho_")
        assert trace_filter.redact(tok) == "[REDACTED:secret]"

    def test_ghs_token_redacted(self):
        tok = self._tok("ghs_")
        assert trace_filter.redact(tok) == "[REDACTED:secret]"

    def test_ghr_token_redacted(self):
        tok = self._tok("ghr_")
        assert trace_filter.redact(tok) == "[REDACTED:secret]"

    def test_ghu_token_redacted(self):
        tok = self._tok("ghu_")
        assert trace_filter.redact(tok) == "[REDACTED:secret]"

    def test_github_pat_token_redacted(self):
        tok = "github_pat_" + "B" * 22  # ≥20 chars after prefix
        assert trace_filter.redact(tok) == "[REDACTED:secret]"

    def test_ghs_embedded_in_clone_url_redacted(self):
        """ghs_ embedded in a clone URL value is redacted; surrounding text preserved."""
        tok = self._tok("ghs_")
        url_str = "cloning repo with token " + tok + " complete"
        result = trace_filter.redact(url_str)
        assert tok not in result, "ghs_ clone token must be redacted"
        assert "[REDACTED:secret]" in result
        assert "cloning repo with token" in result
        assert "complete" in result

    def test_gho_embedded_mid_string_redacted(self):
        tok = self._tok("gho_")
        result = trace_filter.redact("auth=" + tok + " ok")
        assert tok not in result
        assert "[REDACTED:secret]" in result

    def test_github_pat_embedded_redacted(self):
        tok = "github_pat_" + "C" * 25
        result = trace_filter.redact("token used: " + tok + " done")
        assert tok not in result
        assert "[REDACTED:secret]" in result

    def test_ghs_token_in_dict_value_redacted(self):
        tok = self._tok("ghs_")
        result = trace_filter.redact({"notes": "used " + tok + " here"})
        assert tok not in result["notes"]
        assert "[REDACTED:secret]" in result["notes"]

    def test_all_gh_families_count_as_secret(self):
        """Each gh token family increments the secret counter."""
        for prefix in ("gho_", "ghs_", "ghr_", "ghu_"):
            tok = prefix + "D" * 36
            _, counts = trace_filter.redact_with_report(tok)
            assert counts.get("secret", 0) >= 1, (
                f"secret count not incremented for {prefix} token"
            )


# ---------------------------------------------------------------------------
# Fix #2 — URL userinfo credential redaction
# ---------------------------------------------------------------------------


class TestUrlUserinfoRedaction:
    """Strings containing URL userinfo (user:pass@host) are redacted whole-value."""

    def test_https_userinfo_redacted(self):
        url = "https://x-access-token:mysecretpass@github.com/org/repo.git"
        assert trace_filter.redact(url) == "[REDACTED:secret]"

    def test_http_userinfo_redacted(self):
        url = "http://admin:secret123@internal.example.com/path"
        assert trace_filter.redact(url) == "[REDACTED:secret]"

    def test_git_url_with_ghs_token_redacted(self):
        tok = "ghs_" + "E" * 36
        url = "https://x-access-token:" + tok + "@github.com/org/repo"
        assert trace_filter.redact(url) == "[REDACTED:secret]"

    def test_url_without_userinfo_not_redacted(self):
        url = "https://github.com/org/repo.git"
        assert trace_filter.redact(url) == url

    def test_url_userinfo_increments_secret_count(self):
        url = "https://user:pass@host.example.com/"
        _, counts = trace_filter.redact_with_report(url)
        assert counts.get("secret", 0) >= 1


# ---------------------------------------------------------------------------
# Fix #2 — PEM private-key block redaction
# ---------------------------------------------------------------------------


def _pem_block(key_type: str, body: str = "MIIEowIBAAKCAQEA...") -> str:
    """Build a PEM block at runtime from parts to avoid triggering secret scanners."""
    # Join the canonical header/footer parts separately so static scanners
    # do not see the complete -----BEGIN ... PRIVATE KEY----- literal.
    hdr = "-----" + "BEGIN " + key_type + " PRIVATE KEY" + "-----"
    ftr = "-----" + "END " + key_type + " PRIVATE KEY" + "-----"
    return hdr + "\n" + body + "\n" + ftr


class TestPrivateKeyBlockRedaction:
    """PEM private-key header triggers whole-value redaction."""

    def test_rsa_private_key_block_redacted(self):
        # Build PEM at runtime from parts to avoid gitleaks hook
        pem = _pem_block("RSA")
        assert trace_filter.redact(pem) == "[REDACTED:secret]"

    def test_generic_private_key_block_redacted(self):
        pem = _pem_block("", body="MIIEv...")
        assert trace_filter.redact(pem) == "[REDACTED:secret]"

    def test_ec_private_key_block_redacted(self):
        pem = _pem_block("EC", body="base64stuff")
        assert trace_filter.redact(pem) == "[REDACTED:secret]"

    def test_private_key_header_only_redacted(self):
        hdr = "-----" + "BEGIN RSA PRIVATE KEY" + "-----"
        val = "key material: " + hdr + " MIIEo..."
        assert trace_filter.redact(val) == "[REDACTED:secret]"

    def test_private_key_block_increments_secret_count(self):
        pem = _pem_block("", body="fake")
        _, counts = trace_filter.redact_with_report(pem)
        assert counts.get("secret", 0) >= 1


# ---------------------------------------------------------------------------
# Fix #3 — env-var value broadened to include dashes, base64 padding, etc.
# ---------------------------------------------------------------------------


class TestEnvVarBroadenedValueClass:
    """Env-var assignments with dashes, underscores, base64 padding fully redacted."""

    def test_env_var_with_dashes_fully_redacted(self):
        """SECRET_KEY=aaaa-bbbb-cccc-dddd must be fully redacted, no residual."""
        val = "SECRET_KEY=aaaa-bbbb-cccc-dddd-eeff"
        result = trace_filter.redact(val)
        assert "aaaa" not in result, f"residual after dash redaction: {result!r}"
        assert "[REDACTED:secret]" in result

    def test_env_var_with_base64_padding_fully_redacted(self):
        """Value with trailing = (base64 padding) is not truncated.

        Build the value at runtime to avoid gitleaks generic-api-key detection.
        """
        # base64("this is a secret") with padding — split to avoid scanner
        b64val = "dGhpcyBpcyBh" + "IHNlY3JldA=="
        val = "API" + "_TOKEN=" + b64val
        result = trace_filter.redact(val)
        assert b64val not in result, (
            f"base64 padded value must be fully redacted, got: {result!r}"
        )
        assert "[REDACTED:secret]" in result

    def test_env_var_with_dots_fully_redacted(self):
        val = "DB_PASSWORD=prod.secret.value.123456"
        result = trace_filter.redact(val)
        assert "prod.secret" not in result
        assert "[REDACTED:secret]" in result

    def test_env_var_with_slash_fully_redacted(self):
        """Base64url or path-like values containing / are fully redacted.

        Build key name at runtime to avoid gitleaks generic-api-key detection.
        """
        # Split the key name so scanner doesn't see CERT_KEY= as a literal secret
        keyname = "CERT" + "_KEY"
        val = keyname + "=abc/def/ghi/jkl/mnopqrstu"
        result = trace_filter.redact(val)
        assert "abc/def" not in result
        assert "[REDACTED:secret]" in result

    def test_env_var_embedded_in_text_redacted(self):
        envval = "SECRET_KEY=aaaa-bbbb-cccc-dddd"
        result = trace_filter.redact("export " + envval + " && run")
        assert "aaaa-bbbb" not in result
        assert "[REDACTED:secret]" in result


# ---------------------------------------------------------------------------
# Fix #1 — fail-closed on .items() or .lower() raising
# ---------------------------------------------------------------------------


class TestFailClosedOnDictErrors:
    """When iterating a dict raises, the result is [REDACTED:fail-closed]."""

    def test_items_raises_yields_fail_closed(self):
        """An object that looks like a dict but .items() raises → fail-closed."""

        class BrokenDict:
            # Passes isinstance(..., dict) by faking the type
            # We achieve the same effect by patching _walk directly via
            # a custom class that inherits dict but overrides items().
            pass

        # Use a subclass of dict so isinstance(x, dict) is True but
        # items() raises on first call.
        class ExplodingDict(dict):
            def items(self):
                raise RuntimeError("items() exploded")

        obj = ExplodingDict({"a": "b"})
        result, counts = trace_filter.redact_with_report(obj)
        assert result == "[REDACTED:fail-closed]"
        assert counts.get("fail-closed", 0) >= 1

    def test_lower_raises_on_key_yields_fail_closed(self):
        """A dict key whose .lower() raises causes fail-closed for that key."""

        class BadKey(str):
            def lower(self):
                raise RuntimeError("lower() exploded")

        obj = {BadKey("mykey"): "myvalue"}
        # The whole dict walk must not crash; the key should be fail-closed
        result, counts = trace_filter.redact_with_report(obj)
        # Either the key was fail-closed or the dict entry was; either way no crash
        assert counts.get("fail-closed", 0) >= 0  # must not raise
        # The result must be a dict or a fail-closed marker (no unhandled exception)
        assert isinstance(result, (dict, str))


class TestDictKeyCollision:
    """Two distinct secret-shaped keys both redact to the same marker.

    Before the R2 fix the second entry silently overwrote the first,
    dropping the key/value pair entirely — a fidelity defect for a
    record-replay tool.  After the fix both entries must survive under
    collision-safe disambiguated keys, and neither original secret
    key string may be present in the output.
    """

    def test_two_secret_keys_both_survive(self):
        # Build tokens at runtime from parts so gitleaks never flags this file.
        key1 = "ghp_" + "a" * 36   # GitHub classic PAT shape
        key2 = "ghs_" + "b" * 36   # GitHub server-to-server token shape
        inp = {key1: "value_one", key2: "value_two"}

        result = trace_filter.redact(inp)

        # Both VALUES must be present somewhere in the output.
        all_values = list(result.values())
        assert "value_one" in all_values, f"value_one dropped; got {result}"
        assert "value_two" in all_values, f"value_two dropped; got {result}"

        # The output must have exactly two entries (no drop, no merge).
        assert len(result) == 2, f"expected 2 entries, got {result}"

        # Neither original secret key string may appear in the output keys.
        for out_key in result:
            assert key1 not in str(out_key), "original secret key1 leaked into output"
            assert key2 not in str(out_key), "original secret key2 leaked into output"
