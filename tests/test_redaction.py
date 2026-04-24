"""Tests for usai_harness.redaction (SEC-001, ADR-007)."""

from usai_harness.redaction import redact_secrets


def test_bearer_token_redacted():
    out = redact_secrets("Authorization: Bearer abc123def456ghi789")
    assert "abc123def456ghi789" not in out
    assert "REDACTED" in out
    assert "Bearer " in out  # prefix preserved


def test_bearer_short_token_not_matched():
    """Tokens under 16 chars are not key-shaped and are left alone."""
    out = redact_secrets("Bearer tooShort")
    assert out == "Bearer tooShort"


def test_api_key_assignment_redacted():
    out = redact_secrets("USAI_API_KEY=sk-abcdef1234567890abcdef")
    assert "sk-abcdef1234567890abcdef" not in out
    assert "REDACTED" in out
    assert "USAI_API_KEY" in out


def test_multiple_provider_key_forms():
    for provider in ("USAI", "OPENROUTER", "ANTHROPIC", "OPENAI",
                     "AZURE", "AWS", "GOOGLE"):
        name = f"{provider}_API_KEY"
        s = f'{name} = "abc1234567890xyz0987"'
        out = redact_secrets(s)
        assert "abc1234567890xyz0987" not in out, f"leak for {provider}"
        assert "REDACTED" in out


def test_sk_prefix_redacted():
    out = redact_secrets("token = sk-abcdef1234567890abcdef")
    assert "abcdef1234567890abcdef" not in out
    assert "REDACTED" in out


def test_dict_recurses():
    d = {
        "auth": "Bearer abcdef1234567890abcdef",
        "nested": {"headers": {"Authorization": "Bearer xyz1234567890abcdef"}},
        "list": ["Bearer qrs1234567890abcdef"],
    }
    out = redact_secrets(d)
    assert "abcdef1234567890abcdef" not in str(out)
    assert "xyz1234567890abcdef" not in str(out)
    assert "qrs1234567890abcdef" not in str(out)


def test_tuple_recurses():
    t = ("safe", "Bearer abcdef1234567890abcdef")
    out = redact_secrets(t)
    assert isinstance(out, tuple)
    assert "abcdef1234567890abcdef" not in out[1]


def test_non_string_non_container_unchanged():
    assert redact_secrets(42) == 42
    assert redact_secrets(3.14) == 3.14
    assert redact_secrets(None) is None
    assert redact_secrets(True) is True


def test_no_mutation_of_input():
    original = {"auth": "Bearer abcdef1234567890abcdef"}
    copy = {"auth": "Bearer abcdef1234567890abcdef"}
    redact_secrets(original)
    assert original == copy
