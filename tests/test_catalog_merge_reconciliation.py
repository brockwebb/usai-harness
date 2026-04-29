"""Tests for the live-catalog merge reconciliation (0.5.0).

The reconciliation rule: when the live catalog renames a seed model (e.g.
`claude-sonnet-4-5-20241022` → `claude_4_5_sonnet`), the merge layer maps
seed → live via the family-catalog alias table, carries seed accounting
forward onto the new ModelConfig, and exposes the rename to
`load_project_config()` so project pool references that still use the
seed name keep working. Referenced models that are dropped *without*
a reconciliation match cause `ConfigValidationError` rather than silently
falling back, so controlled-variation experiments cannot be corrupted by
a catalog rename.
"""

import logging
import textwrap
from pathlib import Path

import pytest

from usai_harness.config import ConfigLoader, ConfigValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_MODELS_YAML = REPO_ROOT / "configs" / "models.yaml"


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


def _write_project_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "project.yaml"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


# ---------- catalog-level reconciliation ----------------------------------


def test_seed_default_renamed_via_family_alias(live_catalog, caplog):
    """Seed default_model `claude-sonnet-4-5-20241022` → live name
    `claude_4_5_sonnet` (same family, same provider). The loader silently
    substitutes and emits one INFO log line."""
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["claude_4_5_sonnet"],
            },
        }
    })
    caplog.set_level(logging.INFO, logger="usai_harness.config")
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)

    assert loader.list_models() == ["claude_4_5_sonnet"]
    assert loader.get_default_model().name == "claude_4_5_sonnet"
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(
        "renamed" in r.getMessage()
        and "claude_4_5_sonnet" in r.getMessage()
        and "claude-sonnet-4-5-20241022" in r.getMessage()
        for r in info_records
    )


def test_rename_carries_seed_accounting_forward(live_catalog):
    """Reconciled live name inherits the seed entry's context_window and
    cost rates. Synthesized defaults are not used when reconciliation matched."""
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["claude_4_5_sonnet"],
            },
        }
    })
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    m = loader.get_model("claude_4_5_sonnet")
    # Seed value for claude-sonnet-4-5-20241022.
    assert m.context_window == 200000
    assert m.cost_per_1k_input_tokens == 0.0
    assert m.cost_per_1k_output_tokens == 0.0
    assert m.family_key == "claude-sonnet-4"


def test_referenced_default_dropped_without_match_raises(live_catalog):
    """Catalog default that has no family-alias match in the live catalog
    raises ConfigValidationError with the prescribed remediation message."""
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                # Live advertises a model in a totally different family.
                "models": ["gemini-2.0-flash"],
            },
        }
    })
    with pytest.raises(ConfigValidationError) as exc:
        ConfigLoader(models_config_path=REAL_MODELS_YAML)
    msg = str(exc.value)
    assert "claude-sonnet-4-5-20241022" in msg
    assert "discover-models" in msg
    assert "list-models" in msg


def test_unreferenced_drop_just_warns(live_catalog, caplog):
    """A seed model that is dropped but is NOT the catalog default still
    just WARNs (current behavior preserved)."""
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                # claude_4_5_sonnet covers the seed default; opus and others
                # have no live match — they drop.
                "models": ["claude_4_5_sonnet"],
            },
        }
    })
    caplog.set_level(logging.WARNING, logger="usai_harness.config")
    ConfigLoader(models_config_path=REAL_MODELS_YAML)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "dropped" in r.getMessage() and "claude-opus-4-5-20250521" in r.getMessage()
        for r in warnings
    )


def test_unknown_alias_on_both_sides_falls_through_to_dropped(live_catalog, caplog):
    """A seed model with no family alias and no live match drops without
    reconciliation (current behavior preserved). Llama-3.2 is not in the
    family catalog, so it cannot be reconciled even when the live catalog
    advertises a Llama-4 entry."""
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": [
                    "claude_4_5_sonnet",
                    "meta-llama/Llama-4-Maverick-17B-128E-Instruct",
                ],
            },
        }
    })
    caplog.set_level(logging.WARNING, logger="usai_harness.config")
    ConfigLoader(models_config_path=REAL_MODELS_YAML)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "Llama-3.2" in r.getMessage() and "dropped" in r.getMessage()
        for r in warnings
    )


# ---------- project-config rename pickup ----------------------------------


def test_project_pool_member_picks_up_live_rename(live_catalog, tmp_path, caplog):
    """A project config that names the seed identifier transparently picks
    up the live name. INFO log records the substitution."""
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["claude_4_5_sonnet"],
            },
        }
    })
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        models:
          - name: claude-sonnet-4-5-20241022
    """)
    caplog.set_level(logging.INFO, logger="usai_harness.config")
    pc = loader.load_project_config(cfg)

    assert [m.name for m in pc.models] == ["claude_4_5_sonnet"]
    assert pc.default_model.name == "claude_4_5_sonnet"
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(
        "claude-sonnet-4-5-20241022" in r.getMessage()
        and "claude_4_5_sonnet" in r.getMessage()
        and "renamed" in r.getMessage()
        for r in info_records
    )


def test_project_default_model_picks_up_live_rename(live_catalog, tmp_path):
    """When a project's default_model is the seed identifier, it gets
    rewritten to the live name to match the renamed pool member."""
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": [
                    "claude_4_5_sonnet",
                    "meta-llama/Llama-4-Maverick-17B-128E-Instruct",
                ],
            },
        }
    })
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        models:
          - name: claude-sonnet-4-5-20241022
          - name: meta-llama/Llama-4-Maverick-17B-128E-Instruct
        default_model: claude-sonnet-4-5-20241022
    """)
    pc = loader.load_project_config(cfg)
    assert pc.default_model.name == "claude_4_5_sonnet"


def test_project_pool_unknown_name_still_fails_loud(live_catalog, tmp_path):
    """A project pool member that is neither in the live catalog nor in
    the rename map still fails with the standard unknown-model diagnostic."""
    write, _ = live_catalog
    write({
        "providers": {
            "usai": {
                "base_url": "https://usai.example/v1",
                "api_key_env": "USAI_API_KEY",
                "models": ["claude_4_5_sonnet"],
            },
        }
    })
    loader = ConfigLoader(models_config_path=REAL_MODELS_YAML)
    cfg = _write_project_config(tmp_path, """
        models:
          - name: nonexistent-model-zzz
    """)
    with pytest.raises(ConfigValidationError) as exc:
        loader.load_project_config(cfg)
    assert "nonexistent-model-zzz" in str(exc.value)
