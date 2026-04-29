"""Tests for `usai-harness list-models`.

Each test writes a controlled `models.yaml` and passes it as
`models_config_path` to `handle_list_models`. The user-level catalog is
isolated by the global `_isolate_user_config` fixture in conftest.py.
"""

import textwrap
from pathlib import Path

import pytest
import yaml

from usai_harness.setup_commands import handle_list_models


def _write_seed(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


_TWO_PROVIDER_SEED = """
    providers:
      usai:
        base_url: https://usai.example/v1
        api_key_env: USAI_API_KEY
      openrouter:
        base_url: https://or.example/v1
        api_key_env: OPENROUTER_API_KEY

    models:
      model-a:
        provider: usai
        context_window: 1000
        supports_temperature: true
        supports_system_prompt: true
        cost_per_1k_input_tokens: 0.0
        cost_per_1k_output_tokens: 0.0
      model-b:
        provider: openrouter
        context_window: 1000
        supports_temperature: true
        supports_system_prompt: true
        cost_per_1k_input_tokens: 0.0
        cost_per_1k_output_tokens: 0.0

    default_model: model-a
"""

_EMPTY_CATALOG = """
    providers:
      usai:
        base_url: https://usai.example/v1
        api_key_env: USAI_API_KEY

    models: {}
"""


def test_list_models_table_format(tmp_path, capsys):
    seed = _write_seed(tmp_path, _TWO_PROVIDER_SEED)
    rc = handle_list_models(output_format="table", models_config_path=seed)
    assert rc == 0
    out = capsys.readouterr().out
    assert "model-a" in out
    assert "model-b" in out
    assert "usai" in out
    assert "openrouter" in out
    # Header row visible.
    assert "name" in out
    assert "provider" in out


def test_list_models_yaml_format(tmp_path, capsys):
    seed = _write_seed(tmp_path, _TWO_PROVIDER_SEED)
    rc = handle_list_models(output_format="yaml", models_config_path=seed)
    assert rc == 0
    out = capsys.readouterr().out

    parsed = yaml.safe_load(out)
    assert "providers" in parsed
    assert set(parsed["providers"].keys()) == {"usai", "openrouter"}
    assert parsed["providers"]["usai"]["models"] == ["model-a"]
    assert parsed["providers"]["openrouter"]["models"] == ["model-b"]


def test_list_models_names_format(tmp_path, capsys):
    seed = _write_seed(tmp_path, _TWO_PROVIDER_SEED)
    rc = handle_list_models(output_format="names", models_config_path=seed)
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert sorted(lines) == ["model-a", "model-b"]


def test_list_models_provider_filter(tmp_path, capsys):
    seed = _write_seed(tmp_path, _TWO_PROVIDER_SEED)
    rc = handle_list_models(
        provider="usai", output_format="names", models_config_path=seed,
    )
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines == ["model-a"]


def test_list_models_empty_catalog(tmp_path, capsys):
    seed = _write_seed(tmp_path, _EMPTY_CATALOG)
    rc = handle_list_models(output_format="table", models_config_path=seed)
    assert rc == 1
    err = capsys.readouterr().err
    assert "discover-models" in err or "init" in err


def test_list_models_unknown_provider_filter(tmp_path, capsys):
    seed = _write_seed(tmp_path, _TWO_PROVIDER_SEED)
    rc = handle_list_models(
        provider="nonexistent", output_format="table",
        models_config_path=seed,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "nonexistent" in err
    assert "usai" in err
    assert "openrouter" in err
