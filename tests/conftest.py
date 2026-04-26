"""Shared pytest fixtures.

Global isolation: every test runs with the user-level credential and model
catalog paths redirected into the test's tmp_path. Without this, a developer
who runs `usai-harness init` on their machine ends up with a populated
~/.config/usai-harness/models.yaml that bleeds into the live-catalog merge
and breaks tests that rely on the seed config. Tests that explicitly need a
populated user-level catalog override the fixture (see `live_catalog` in
test_config.py).
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_config(monkeypatch, tmp_path_factory):
    """Redirect user-level config paths to an empty tmp dir for every test."""
    empty_dir = tmp_path_factory.mktemp("isolated_user_config")
    env_path = empty_dir / ".env"
    catalog_path = empty_dir / "models.yaml"

    # setup_commands is the module that config.py reaches through.
    monkeypatch.setattr(
        "usai_harness.setup_commands.user_config_env_path",
        lambda: env_path,
    )
    monkeypatch.setattr(
        "usai_harness.setup_commands.user_config_models_path",
        lambda: catalog_path,
    )
    # Tests that exercise key_manager directly use this binding.
    monkeypatch.setattr(
        "usai_harness.key_manager.user_config_env_path",
        lambda: env_path,
    )
