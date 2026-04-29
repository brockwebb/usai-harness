"""Tests for config loading, validation, error messages."""

import logging
import textwrap
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from usai_harness.config import (
    ConfigLoader,
    ConfigValidationError,
    ModelConfig,
    ProjectConfig,
    ProviderConfig,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_MODELS_YAML = REPO_ROOT / "configs" / "models.yaml"


def _write_project_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "project.yaml"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def test_load_default_models_yaml():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    expected = {
        "meta-llama/Llama-4-Maverick-17B-128E-Instruct",
        "meta-llama/Llama-3.2-11B-Vision-Instruct",
        "claude-opus-4-5-20250521",
        "claude-sonnet-4-5-20241022",
        "claude-3-5-haiku-20241022",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    }
    assert expected.issubset(set(loader.list_models()))
    assert loader.get_default_model().name == "claude-sonnet-4-5-20241022"


def test_get_model_valid():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    m = loader.get_model("meta-llama/Llama-4-Maverick-17B-128E-Instruct")
    assert m.name == "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
    assert m.provider == "usai"
    assert m.context_window == 131072
    assert m.supports_temperature is True
    assert m.supports_system_prompt is True
    assert m.cost_per_1k_input_tokens == 0.0
    assert m.cost_per_1k_output_tokens == 0.0


def test_get_model_invalid_raises():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    with pytest.raises(ConfigValidationError) as exc:
        loader.get_model("gpt-4-turbo")
    msg = str(exc.value)
    assert "gpt-4-turbo" in msg
    assert "meta-llama/Llama-4-Maverick-17B-128E-Instruct" in msg


def test_load_project_config_valid(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
        temperature: 0.7
        max_tokens: 4096
        system_prompt: "You are a helpful assistant."
        workers: 2
        batch_size: 100
    """)
    pc = loader.load_project_config(cfg)

    assert isinstance(pc, ProjectConfig)
    assert pc.default_model.name == "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
    assert pc.temperature == 0.7
    assert pc.max_tokens == 4096
    assert pc.system_prompt == "You are a helpful assistant."
    assert pc.workers == 2
    assert pc.batch_size == 100


def test_project_config_defaults(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
    """)
    pc = loader.load_project_config(cfg)

    assert pc.temperature == 0.0
    assert pc.max_tokens is None
    assert pc.workers == 3
    assert pc.batch_size == 50
    assert pc.system_prompt is None


def test_unknown_model_in_project_config_raises(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: nonexistent-model
    """)
    with pytest.raises(ConfigValidationError):
        loader.load_project_config(cfg)


def test_missing_model_field_raises(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        temperature: 0.5
    """)
    with pytest.raises(ConfigValidationError) as exc:
        loader.load_project_config(cfg)
    msg = str(exc.value).lower()
    assert "model" in msg
    assert "required" in msg


def test_validate_request_context_overflow():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    m = loader.get_model("meta-llama/Llama-4-Maverick-17B-128E-Instruct")
    with pytest.raises(ConfigValidationError) as exc:
        loader.validate_request(m, prompt_tokens=130000, max_tokens=2000)
    assert "131072" in str(exc.value)


def test_validate_request_within_limits():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    m = loader.get_model("meta-llama/Llama-4-Maverick-17B-128E-Instruct")
    # Should not raise
    loader.validate_request(m, prompt_tokens=1000, max_tokens=2000)


def test_unknown_fields_warns(tmp_path, caplog):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
        foo: bar
    """)
    caplog.set_level(logging.WARNING, logger="usai_harness.config")
    pc = loader.load_project_config(cfg)

    assert pc.default_model.name == "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING for unknown field"
    assert any("foo" in r.getMessage() for r in warnings)


def test_models_yaml_missing_raises(tmp_path):
    missing = tmp_path / "nonexistent.yaml"
    with pytest.raises(ConfigValidationError) as exc:
        ConfigLoader(models_config_path=missing)
    assert str(missing) in str(exc.value)


def test_model_config_is_frozen():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    m = loader.get_model("meta-llama/Llama-4-Maverick-17B-128E-Instruct")
    with pytest.raises(FrozenInstanceError):
        m.name = "hacked"  # type: ignore[misc]


# ---------- providers block (ADR-003, ADR-008) ----------------------------


def _write_models_yaml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


_MINIMAL_MODEL_BLOCK = """
models:
  demo-model:
    provider: usai
    context_window: 1000
    supports_temperature: true
    supports_system_prompt: true
    cost_per_1k_input_tokens: 0.0
    cost_per_1k_output_tokens: 0.0

default_model: demo-model
"""


def test_providers_block_parsed(tmp_path):
    yaml_body = (
        """
        providers:
          usai:
            base_url: https://example.com/v1
            api_key_env: USAI_API_KEY
        """
        + _MINIMAL_MODEL_BLOCK
    )
    path = _write_models_yaml(tmp_path, yaml_body)
    loader = ConfigLoader(models_config_path=path)

    assert loader.list_providers() == ["usai"]
    p = loader.get_provider("usai")
    assert isinstance(p, ProviderConfig)
    assert p.base_url == "https://example.com/v1"
    assert p.api_key_env == "USAI_API_KEY"


def test_model_provider_mismatch_raises(tmp_path):
    yaml_body = (
        """
        providers:
          other:
            base_url: https://other.example.com/v1
            api_key_env: OTHER_KEY
        """
        + _MINIMAL_MODEL_BLOCK
    )
    path = _write_models_yaml(tmp_path, yaml_body)
    with pytest.raises(ConfigValidationError) as exc:
        ConfigLoader(models_config_path=path)
    msg = str(exc.value)
    assert "demo-model" in msg
    assert "usai" in msg


def test_providers_missing_base_url_raises(tmp_path):
    yaml_body = (
        """
        providers:
          usai:
            api_key_env: USAI_API_KEY
        """
        + _MINIMAL_MODEL_BLOCK
    )
    path = _write_models_yaml(tmp_path, yaml_body)
    with pytest.raises(ConfigValidationError, match="base_url"):
        ConfigLoader(models_config_path=path)


def test_providers_missing_api_key_env_raises(tmp_path):
    yaml_body = (
        """
        providers:
          usai:
            base_url: https://example.com/v1
        """
        + _MINIMAL_MODEL_BLOCK
    )
    path = _write_models_yaml(tmp_path, yaml_body)
    with pytest.raises(ConfigValidationError, match="api_key_env"):
        ConfigLoader(models_config_path=path)


def test_providers_to_env_map():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    assert loader.providers_to_env_map() == {"usai": "USAI_API_KEY"}


def test_project_config_credentials_backend(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
        credentials:
          backend: azure_keyvault
          vault_url: https://my-vault.vault.azure.net
    """)
    pc = loader.load_project_config(cfg)

    assert pc.credentials_backend == "azure_keyvault"
    assert pc.credentials_kwargs == {
        "vault_url": "https://my-vault.vault.azure.net",
    }


def test_project_config_credentials_default_is_dotenv(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
    """)
    pc = loader.load_project_config(cfg)

    assert pc.credentials_backend == "dotenv"
    assert pc.credentials_kwargs == {}


def test_project_config_unknown_credentials_backend_raises(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
        credentials:
          backend: sorcery
    """)
    with pytest.raises(ConfigValidationError, match="sorcery"):
        loader.load_project_config(cfg)


# ---------- live catalog merge (ADR-009, FR-040) --------------------------


@pytest.fixture
def live_catalog(monkeypatch, tmp_path):
    """Redirect user_config_models_path into tmp_path and return write helper."""
    catalog_path = tmp_path / "user" / "models.yaml"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "usai_harness.setup_commands.user_config_models_path",
        lambda: catalog_path,
    )

    def _write(data):
        import yaml as _yaml
        catalog_path.write_text(_yaml.safe_dump(data, sort_keys=False))

    return _write, catalog_path


def test_live_catalog_absent_leaves_repo_config_unchanged(live_catalog):
    _, catalog_path = live_catalog
    assert not catalog_path.exists()
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    # Repo config has 7 verified IDs; merge skipped when no user catalog.
    assert "meta-llama/Llama-4-Maverick-17B-128E-Instruct" in loader.list_models()
    assert "claude-sonnet-4-5-20241022" in loader.list_models()


def test_live_catalog_two_providers_five_models(live_catalog, tmp_path):
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["meta-llama/Llama-4-Maverick-17B-128E-Instruct", "claude-opus-4-5"],
            },
            "openrouter": {
                "base_url": "https://or.example/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "models": ["or-a", "or-b", "or-c"],
            },
        }
    })
    # Need a repo config that references openrouter too, or the provider integrity
    # check fires first. Write a custom models.yaml.
    repo = tmp_path / "repo.models.yaml"
    repo.write_text(textwrap.dedent("""
        providers:
          usai:
            base_url: https://usai.example/v1
            api_key_env: USAI_API_KEY
          openrouter:
            base_url: https://or.example/v1
            api_key_env: OPENROUTER_API_KEY
        models:
          "meta-llama/Llama-4-Maverick-17B-128E-Instruct":
            provider: usai
            context_window: 131072
            supports_temperature: true
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0
        default_model: "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
    """).lstrip())

    loader = ConfigLoader(models_config_path=repo)
    assert set(loader.list_models()) == {
        "meta-llama/Llama-4-Maverick-17B-128E-Instruct", "claude-opus-4-5", "or-a", "or-b", "or-c",
    }
    # Live-only models get synthesized defaults with the correct provider.
    assert loader.get_model("or-a").provider == "openrouter"


def test_live_model_not_in_repo_gets_synthesized_defaults(live_catalog):
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["new-synth-model"],
            },
        }
    })
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)

    m = loader.get_model("new-synth-model")
    assert m.provider == "usai"
    assert m.context_window == 0
    assert m.supports_temperature is True


def test_repo_model_not_in_live_is_dropped(live_catalog):
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["meta-llama/Llama-4-Maverick-17B-128E-Instruct"],
            },
        }
    })
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    assert loader.list_models() == ["meta-llama/Llama-4-Maverick-17B-128E-Instruct"]
    with pytest.raises(ConfigValidationError):
        loader.get_model("claude-opus-4-5")


def test_live_catalog_overrides_repo_base_url(live_catalog):
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://live.example.com/api/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["meta-llama/Llama-4-Maverick-17B-128E-Instruct"],
            },
        }
    })
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    assert loader.get_provider("usai").base_url == "https://live.example.com/api/v1"


def test_default_model_dropped_falls_back_with_warning(live_catalog, caplog):
    import logging as _logging
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["claude-opus-4-5", "gemini-2-5-pro"],
            },
        }
    })
    caplog.set_level(_logging.WARNING, logger="usai_harness.config")
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)

    assert loader.get_default_model().name in {"claude-opus-4-5", "gemini-2-5-pro"}
    warnings = [r for r in caplog.records if r.levelno == _logging.WARNING]
    assert any(
        "default_model" in r.getMessage() and "dropped" in r.getMessage()
        for r in warnings
    )


def test_default_model_becomes_none_when_all_dropped(live_catalog):
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": [],  # empty — every repo model gets dropped
            },
        }
    })
    # An empty models list means no authoritative set, which the impl treats as
    # "no live data; leave repo state untouched". So we need a non-empty list
    # that contains no overlap with the repo. Use a model the repo does not have.
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["only-live-one"],
            },
        }
    })
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    # Only one live model survives, and default_model was llama-4-maverick.
    assert loader.list_models() == ["only-live-one"]
    assert loader.get_default_model().name == "only-live-one"


# ---------- api_key_secret for Azure backend (Task 07) ----------------------


def test_provider_with_api_key_secret_loads(tmp_path):
    yaml_body = """
        providers:
          usai:
            base_url: https://example.com/api/v1
            api_key_secret: usai-vault-secret-name
        models:
          test-model:
            provider: usai
            context_window: 1000
            supports_temperature: true
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0
        default_model: test-model
    """
    path = tmp_path / "models.yaml"
    path.write_text(textwrap.dedent(yaml_body).lstrip())
    loader = ConfigLoader(models_config_path=path)

    p = loader.get_provider("usai")
    assert p.api_key_secret == "usai-vault-secret-name"
    assert p.api_key_env is None
    assert loader.providers_to_secret_map() == {"usai": "usai-vault-secret-name"}


def test_provider_with_neither_field_raises(tmp_path):
    yaml_body = """
        providers:
          usai:
            base_url: https://example.com/api/v1
        models:
          test-model:
            provider: usai
            context_window: 1000
            supports_temperature: true
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0
        default_model: test-model
    """
    path = tmp_path / "models.yaml"
    path.write_text(textwrap.dedent(yaml_body).lstrip())
    with pytest.raises(ConfigValidationError, match="api_key"):
        ConfigLoader(models_config_path=path)


def test_secret_map_requires_api_key_secret_for_azure(tmp_path):
    """Azure backend rejects api_key_env-only providers; ConfigValidationError, no warning."""
    yaml_body = """
        providers:
          usai:
            base_url: https://example.com/api/v1
            api_key_env: USAI_API_KEY
        models:
          test-model:
            provider: usai
            context_window: 1000
            supports_temperature: true
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0
        default_model: test-model
    """
    path = tmp_path / "models.yaml"
    path.write_text(textwrap.dedent(yaml_body).lstrip())
    loader = ConfigLoader(models_config_path=path)

    with pytest.raises(ConfigValidationError) as exc:
        loader.providers_to_secret_map()
    msg = str(exc.value)
    assert "api_key_secret" in msg
    assert "usai" in msg


def test_secret_map_uses_secret_when_both_set(tmp_path):
    """api_key_secret is the only field consulted; api_key_env is ignored silently."""
    yaml_body = """
        providers:
          usai:
            base_url: https://example.com/api/v1
            api_key_env: USAI_API_KEY
            api_key_secret: usai-vault-secret
        models:
          test-model:
            provider: usai
            context_window: 1000
            supports_temperature: true
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0
        default_model: test-model
    """
    path = tmp_path / "models.yaml"
    path.write_text(textwrap.dedent(yaml_body).lstrip())
    loader = ConfigLoader(models_config_path=path)

    assert loader.providers_to_secret_map() == {"usai": "usai-vault-secret"}


def test_apply_live_catalog_warns_on_dropped_models(live_catalog, caplog):
    """A seed model absent from the live catalog must trigger a WARN with the path."""
    import logging as _logging
    write, catalog_path = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                # Only Llama-4 is in live; the other 6 repo models are dropped.
                "models": ["meta-llama/Llama-4-Maverick-17B-128E-Instruct"],
            },
        }
    })
    caplog.set_level(_logging.WARNING, logger="usai_harness.config")
    ConfigLoader(models_config_path=REAL_MODELS_YAML)

    warnings = [
        r for r in caplog.records
        if r.levelno == _logging.WARNING
        and "dropped" in r.getMessage()
        and "live catalog" in r.getMessage()
    ]
    assert warnings, "expected WARN about dropped models"
    msg = warnings[0].getMessage()
    assert str(catalog_path) in msg
    # At least one of the dropped repo IDs must appear.
    assert "claude-sonnet-4-5-20241022" in msg


# ---------- error_body_snippet_max_chars (Task 10) ------------------------


def test_error_body_snippet_max_chars_default(tmp_path):
    yaml_body = (
        """
        providers:
          usai:
            base_url: https://example.com/v1
            api_key_env: USAI_API_KEY
        """
        + _MINIMAL_MODEL_BLOCK
    )
    path = _write_models_yaml(tmp_path, yaml_body)
    loader = ConfigLoader(models_config_path=path)
    assert loader.error_body_snippet_max_chars == 200


_BASE_PROVIDER_BLOCK = """
providers:
  usai:
    base_url: https://example.com/v1
    api_key_env: USAI_API_KEY
"""


def test_error_body_snippet_max_chars_override(tmp_path):
    yaml_body = (
        "error_body_snippet_max_chars: 500\n"
        + _BASE_PROVIDER_BLOCK
        + _MINIMAL_MODEL_BLOCK
    )
    path = _write_models_yaml(tmp_path, yaml_body)
    loader = ConfigLoader(models_config_path=path)
    assert loader.error_body_snippet_max_chars == 500


@pytest.mark.parametrize("bad", [0, -5, 5000])
def test_error_body_snippet_max_chars_validation(tmp_path, bad):
    yaml_body = (
        f"error_body_snippet_max_chars: {bad}\n"
        + _BASE_PROVIDER_BLOCK
        + _MINIMAL_MODEL_BLOCK
    )
    path = _write_models_yaml(tmp_path, yaml_body)
    with pytest.raises(ConfigValidationError, match="error_body_snippet_max_chars"):
        ConfigLoader(models_config_path=path)


def test_error_body_snippet_max_chars_non_integer_raises(tmp_path):
    yaml_body = (
        'error_body_snippet_max_chars: "two hundred"\n'
        + _BASE_PROVIDER_BLOCK
        + _MINIMAL_MODEL_BLOCK
    )
    path = _write_models_yaml(tmp_path, yaml_body)
    with pytest.raises(ConfigValidationError, match="positive integer"):
        ConfigLoader(models_config_path=path)


# ---------- model pool schema (ADR-012, FR-046..052) ----------------------


def test_project_config_pool_one_member(tmp_path):
    """Single-member pool with default_model omitted; that member is the default."""
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        models:
          - name: claude-sonnet-4-5-20241022
    """)
    pc = loader.load_project_config(cfg)

    assert [m.name for m in pc.models] == ["claude-sonnet-4-5-20241022"]
    assert pc.default_model.name == "claude-sonnet-4-5-20241022"
    assert pc.provider == "usai"


def test_project_config_pool_multiple_members_with_default(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        models:
          - name: claude-sonnet-4-5-20241022
          - name: claude-opus-4-5-20250521
          - name: gemini-2.5-flash
        default_model: claude-opus-4-5-20250521
    """)
    pc = loader.load_project_config(cfg)

    assert {m.name for m in pc.models} == {
        "claude-sonnet-4-5-20241022",
        "claude-opus-4-5-20250521",
        "gemini-2.5-flash",
    }
    assert pc.default_model.name == "claude-opus-4-5-20250521"


def test_project_config_pool_missing_default_with_multiple(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        models:
          - name: claude-sonnet-4-5-20241022
          - name: claude-opus-4-5-20250521
    """)
    with pytest.raises(ConfigValidationError, match="default_model"):
        loader.load_project_config(cfg)


def test_project_config_pool_unknown_model(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        models:
          - name: claude-sonnet-4-5-20241022
          - name: nonexistent-model-xyz
        default_model: claude-sonnet-4-5-20241022
    """)
    with pytest.raises(ConfigValidationError) as exc:
        loader.load_project_config(cfg)
    msg = str(exc.value)
    assert "nonexistent-model-xyz" in msg


def test_project_config_pool_provider_mismatch(tmp_path):
    """Top-level provider must match every pool member's provider field."""
    yaml_body = textwrap.dedent("""
        providers:
          usai:
            base_url: https://example.com/api/v1
            api_key_env: USAI_API_KEY
          alpha:
            base_url: https://alpha.example.com/v1
            api_key_env: ALPHA_API_KEY

        models:
          model-on-usai:
            provider: usai
            context_window: 1000
            supports_temperature: true
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0

          model-on-alpha:
            provider: alpha
            context_window: 1000
            supports_temperature: true
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0

        default_model: model-on-usai
    """).lstrip()
    cat_path = _write_models_yaml(tmp_path, yaml_body)
    loader = ConfigLoader(models_config_path=cat_path)

    cfg = _write_project_config(tmp_path, """
        provider: usai
        models:
          - name: model-on-usai
          - name: model-on-alpha
        default_model: model-on-usai
    """)
    with pytest.raises(ConfigValidationError, match="Cross-provider"):
        loader.load_project_config(cfg)


def test_legacy_catalog_fields_are_ignored_not_rejected(tmp_path):
    """Per the ADR-012 amendment (2026-04-29): a user-level catalog left over
    from a pre-amendment install still loads. Legacy `temperature_range` and
    `max_output_tokens` per-model fields are ignored without warning."""
    yaml_body = """
        providers:
          usai:
            base_url: https://example.com/api/v1
            api_key_env: USAI_API_KEY
        models:
          legacy-model:
            provider: usai
            context_window: 1000
            max_output_tokens: 100
            supports_temperature: true
            temperature_range: [0.0, 1.0]
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0
        default_model: legacy-model
    """
    path = tmp_path / "models.yaml"
    path.write_text(textwrap.dedent(yaml_body).lstrip())
    loader = ConfigLoader(models_config_path=path)

    m = loader.get_model("legacy-model")
    assert m.name == "legacy-model"
    assert not hasattr(m, "temperature_range")
    assert not hasattr(m, "max_output_tokens")


def test_pool_member_passes_through_unrecognized_param(tmp_path):
    """Per the ADR-012 amendment (2026-04-29): values out-of-range for any
    real provider load cleanly. The harness does not validate the value."""
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        models:
          - name: claude-sonnet-4-5-20241022
            temperature: 5.0
    """)
    pc = loader.load_project_config(cfg)
    assert [m.name for m in pc.models] == ["claude-sonnet-4-5-20241022"]


def test_pool_member_passes_through_extra_field(tmp_path):
    """Per the ADR-012 amendment (2026-04-29): unrecognized per-model fields
    load cleanly without rejection."""
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        models:
          - name: claude-sonnet-4-5-20241022
            top_p: 0.9
    """)
    pc = loader.load_project_config(cfg)
    assert [m.name for m in pc.models] == ["claude-sonnet-4-5-20241022"]


def test_project_config_legacy_single_model(tmp_path):
    """Legacy `model:` form translates to a one-element pool."""
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: claude-sonnet-4-5-20241022
    """)
    pc = loader.load_project_config(cfg)

    assert [m.name for m in pc.models] == ["claude-sonnet-4-5-20241022"]
    assert pc.default_model.name == "claude-sonnet-4-5-20241022"


def test_project_config_both_model_and_models_keys(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: claude-sonnet-4-5-20241022
        models:
          - name: claude-sonnet-4-5-20241022
    """)
    with pytest.raises(ConfigValidationError, match="legacy"):
        loader.load_project_config(cfg)
