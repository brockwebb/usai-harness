"""Tests for the project-config JSON Schema artifact (ADR-015)."""

import jsonschema
import pytest

from usai_harness.config import load_project_config_schema


def test_schema_loads_as_valid_draft_2020_12():
    schema = load_project_config_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"]
    jsonschema.Draft202012Validator.check_schema(schema)


def _validator():
    return jsonschema.Draft202012Validator(load_project_config_schema())


def test_minimal_valid_config_with_legacy_model():
    _validator().validate({"model": "claude-sonnet-4-5-20241022"})


def test_minimal_valid_config_with_pool():
    _validator().validate({
        "models": [{"name": "gemini-2.5-flash"}],
        "default_model": "gemini-2.5-flash",
    })


def test_models_as_bare_strings_is_valid():
    _validator().validate({
        "models": ["gemini-2.5-flash", "claude-sonnet-4-5-20241022"],
        "default_model": "gemini-2.5-flash",
    })


def test_neither_model_nor_models_fails():
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate({"workers": 3})


def test_both_model_and_models_fails():
    """`oneOf` rejects configs with both forms."""
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate({
            "model": "gemini-2.5-flash",
            "models": [{"name": "gemini-2.5-flash"}],
        })


def test_unknown_top_level_field_fails():
    with pytest.raises(jsonschema.ValidationError) as exc:
        _validator().validate({
            "model": "gemini-2.5-flash",
            "ledger_path": "output/cost_ledger.jsonl",
        })
    assert "additionalProperties" in str(exc.value) or "ledger_path" in str(exc.value)


def test_workers_out_of_range_fails():
    for bad in (0, 11, 99):
        with pytest.raises(jsonschema.ValidationError):
            _validator().validate({
                "model": "gemini-2.5-flash",
                "workers": bad,
            })


def test_max_tokens_zero_or_negative_fails():
    for bad in (0, -1):
        with pytest.raises(jsonschema.ValidationError):
            _validator().validate({
                "model": "gemini-2.5-flash",
                "max_tokens": bad,
            })


def test_max_tokens_must_be_integer():
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate({
            "model": "gemini-2.5-flash",
            "max_tokens": "not-a-number",
        })


def test_models_empty_list_fails():
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate({
            "models": [],
            "default_model": "gemini-2.5-flash",
        })


def test_credentials_unknown_backend_fails():
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate({
            "model": "gemini-2.5-flash",
            "credentials": {"backend": "magic-vault"},
        })


def test_credentials_extra_kwargs_pass_through():
    """Backend-specific kwargs are accepted as additional properties under
    `credentials`."""
    _validator().validate({
        "model": "gemini-2.5-flash",
        "credentials": {
            "backend": "azure_keyvault",
            "vault_url": "https://x.vault.azure.net",
        },
    })


def test_pool_member_extra_keys_pass_through():
    """Per-model overrides like `temperature: 0.1` are not in the schema's
    explicit property list but are allowed via additionalProperties on the
    pool-member object form."""
    _validator().validate({
        "models": [
            {"name": "gemini-2.5-flash", "temperature": 0.1, "top_p": 0.9},
        ],
        "default_model": "gemini-2.5-flash",
    })
