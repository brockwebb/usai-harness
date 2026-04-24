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
    assert m.max_output_tokens == 32768
    assert m.supports_temperature is True
    assert m.temperature_range == (0.0, 2.0)
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
    assert pc.model.name == "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
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
    assert pc.max_tokens == pc.model.max_output_tokens
    assert pc.workers == 3
    assert pc.batch_size == 50
    assert pc.system_prompt is None


def test_temperature_out_of_range_raises(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
        temperature: 3.0
    """)
    with pytest.raises(ConfigValidationError) as exc:
        loader.load_project_config(cfg)
    msg = str(exc.value)
    assert "temperature" in msg.lower()
    assert "2.0" in msg


def test_max_tokens_exceeds_model_raises(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
        max_tokens: 999999
    """)
    with pytest.raises(ConfigValidationError) as exc:
        loader.load_project_config(cfg)
    msg = str(exc.value)
    assert "max_tokens" in msg.lower()
    assert "32768" in msg


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

    assert pc.model.name == "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
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
    max_output_tokens: 100
    supports_temperature: true
    temperature_range: [0.0, 1.0]
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
            max_output_tokens: 32768
            supports_temperature: true
            temperature_range: [0.0, 2.0]
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
    assert m.max_output_tokens == 4096
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
