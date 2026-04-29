"""Tests for `usai-harness project-init` multi-rater pool flags (ADR-013 amendment, 2026-04-29)."""

import textwrap
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from usai_harness import setup_commands
from usai_harness.config import ConfigLoader
from usai_harness.transport import BaseTransport


class _MockTransport(BaseTransport):
    def __init__(self, *, status_code: int = 200, content: str = "OK"):
        self.status_code = status_code
        self.content = content
        self.calls: list[dict] = []
        self.closed = False

    async def send(self, base_url, api_key, model, messages, **kw):
        self.calls.append({"model": model, "messages": messages, **kw})
        body = {
            "choices": [{"message": {"role": "assistant", "content": self.content}}],
            "usage": {"prompt_tokens": 6, "completion_tokens": 1, "total_tokens": 7},
            "model": model,
        }
        if 200 <= self.status_code < 300:
            return body, self.status_code
        return {"error_body": "simulated failure"}, self.status_code

    async def close(self):
        self.closed = True


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USAI_API_KEY", "test-key-AAAAAAAA")
    monkeypatch.setenv("ALPHA_API_KEY", "test-alpha-key")
    return tmp_path


def _scripted_prompts(*answers: str):
    iterator: Iterator[str] = iter(answers)

    def _fn(_prompt: str) -> str:
        return next(iterator)

    return _fn


def _read_project_yaml(project_root: Path) -> dict:
    return yaml.safe_load((project_root / "usai_harness.yaml").read_text())


# Real names from the shipped configs/models.yaml seed (7 USAi entries).
# Tests that pass through to the TEVV smoke step must use these so the
# USAiClient's own ConfigLoader (which uses the default seed path) can
# resolve them. Tests that fail at bootstrap (cross-provider, empty
# catalog) inject a custom loader and never reach TEVV.

_SEED_USAI_MODELS = [
    "claude-3-5-haiku-20241022",
    "claude-opus-4-5-20250521",
    "claude-sonnet-4-5-20241022",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "meta-llama/Llama-3.2-11B-Vision-Instruct",
    "meta-llama/Llama-4-Maverick-17B-128E-Instruct",
]


def _multi_provider_loader(tmp_path: Path) -> ConfigLoader:
    catalog = tmp_path / "multiprov.yaml"
    catalog.write_text(textwrap.dedent("""
        providers:
          usai:
            base_url: https://usai.example/v1
            api_key_env: USAI_API_KEY
          alpha:
            base_url: https://alpha.example/v1
            api_key_env: ALPHA_API_KEY

        models:
          usai-only-model:
            provider: usai
            context_window: 1000
            supports_temperature: true
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0
          alpha-model:
            provider: alpha
            context_window: 1000
            supports_temperature: true
            supports_system_prompt: true
            cost_per_1k_input_tokens: 0.0
            cost_per_1k_output_tokens: 0.0

        default_model: usai-only-model
    """).lstrip())
    return ConfigLoader(models_config_path=catalog)


def _empty_loader(tmp_path: Path) -> ConfigLoader:
    catalog = tmp_path / "empty.yaml"
    catalog.write_text(textwrap.dedent("""
        providers:
          usai:
            base_url: https://usai.example/v1
            api_key_env: USAI_API_KEY
        models: {}
    """).lstrip())
    return ConfigLoader(models_config_path=catalog)


def test_project_init_with_models_flag(project_root):
    rc = setup_commands.handle_project_init(
        transport=_MockTransport(),
        models_arg="gemini-2.5-flash,claude-sonnet-4-5-20241022",
        default_arg="gemini-2.5-flash",
    )
    assert rc == 0
    cfg = _read_project_yaml(project_root)
    assert [m["name"] for m in cfg["models"]] == [
        "gemini-2.5-flash", "claude-sonnet-4-5-20241022",
    ]
    assert cfg["default_model"] == "gemini-2.5-flash"
    assert cfg["provider"] == "usai"


def test_project_init_with_models_flag_unknown_model(project_root, capsys):
    rc = setup_commands.handle_project_init(
        transport=_MockTransport(),
        models_arg="gemini-2.5-flash,fake_model",
        default_arg="gemini-2.5-flash",
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "fake_model" in err
    assert "claude-sonnet-4-5-20241022" in err
    assert not (project_root / "usai_harness.yaml").exists()


def test_project_init_with_models_no_default_single_member(project_root):
    rc = setup_commands.handle_project_init(
        transport=_MockTransport(),
        models_arg="gemini-2.5-flash",
    )
    assert rc == 0
    cfg = _read_project_yaml(project_root)
    assert [m["name"] for m in cfg["models"]] == ["gemini-2.5-flash"]
    assert cfg["default_model"] == "gemini-2.5-flash"


def test_project_init_with_models_no_default_multi_member(project_root):
    rc = setup_commands.handle_project_init(
        transport=_MockTransport(),
        models_arg="gemini-2.5-flash,claude-sonnet-4-5-20241022",
        prompt_fn=_scripted_prompts("2"),
    )
    assert rc == 0
    cfg = _read_project_yaml(project_root)
    assert cfg["default_model"] == "claude-sonnet-4-5-20241022"


def test_project_init_interactive_prompt(project_root, capsys):
    sorted_seed = sorted(_SEED_USAI_MODELS)
    # Pick indices 1 and 3 → claude-3-5-haiku and claude-sonnet, default 2 → claude-sonnet.
    rc = setup_commands.handle_project_init(
        transport=_MockTransport(),
        prompt_fn=_scripted_prompts("1,3", "2"),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Available models:" in out
    cfg = _read_project_yaml(project_root)
    assert [m["name"] for m in cfg["models"]] == [sorted_seed[0], sorted_seed[2]]
    assert cfg["default_model"] == sorted_seed[2]


def test_project_init_cross_provider_pool_rejected(project_root, capsys):
    loader = _multi_provider_loader(project_root)
    rc = setup_commands.handle_project_init(
        transport=_MockTransport(),
        models_arg="usai-only-model,alpha-model",
        default_arg="usai-only-model",
        loader=loader,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "cross-provider" in err.lower() or "multiple providers" in err.lower()
    assert not (project_root / "usai_harness.yaml").exists()


def test_project_init_empty_catalog_handled(project_root, capsys):
    loader = _empty_loader(project_root)
    rc = setup_commands.handle_project_init(
        transport=_MockTransport(),
        loader=loader,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "init" in err or "discover-models" in err
    assert not (project_root / "usai_harness.yaml").exists()
