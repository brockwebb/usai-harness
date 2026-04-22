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
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_MODELS_YAML = REPO_ROOT / "configs" / "models.yaml"


def _write_project_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "project.yaml"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def test_load_default_models_yaml():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    assert set(loader.list_models()) == {
        "llama-4-maverick", "claude-opus-4-5", "gemini-2-5-pro",
    }
    assert loader.get_default_model().name == "llama-4-maverick"


def test_get_model_valid():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    m = loader.get_model("llama-4-maverick")
    assert m.name == "llama-4-maverick"
    assert m.provider == "meta"
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
    assert "llama-4-maverick" in msg


def test_load_project_config_valid(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: llama-4-maverick
        temperature: 0.7
        max_tokens: 4096
        system_prompt: "You are a helpful assistant."
        workers: 2
        batch_size: 100
    """)
    pc = loader.load_project_config(cfg)

    assert isinstance(pc, ProjectConfig)
    assert pc.model.name == "llama-4-maverick"
    assert pc.temperature == 0.7
    assert pc.max_tokens == 4096
    assert pc.system_prompt == "You are a helpful assistant."
    assert pc.workers == 2
    assert pc.batch_size == 100


def test_project_config_defaults(tmp_path):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: llama-4-maverick
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
        model: llama-4-maverick
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
        model: llama-4-maverick
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
    m = loader.get_model("llama-4-maverick")
    with pytest.raises(ConfigValidationError) as exc:
        loader.validate_request(m, prompt_tokens=130000, max_tokens=2000)
    assert "131072" in str(exc.value)


def test_validate_request_within_limits():
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    m = loader.get_model("llama-4-maverick")
    # Should not raise
    loader.validate_request(m, prompt_tokens=1000, max_tokens=2000)


def test_unknown_fields_warns(tmp_path, caplog):
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        model: llama-4-maverick
        foo: bar
    """)
    caplog.set_level(logging.WARNING, logger="usai_harness.config")
    pc = loader.load_project_config(cfg)

    assert pc.model.name == "llama-4-maverick"
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
    m = loader.get_model("llama-4-maverick")
    with pytest.raises(FrozenInstanceError):
        m.name = "hacked"  # type: ignore[misc]
