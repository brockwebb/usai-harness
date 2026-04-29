"""Tests for the family catalog (ADR-014)."""

import pytest
import yaml

from usai_harness.config import FamilyCatalog


def test_family_catalog_loads():
    catalog = FamilyCatalog()
    assert catalog.metadata.get("catalog_version")
    assert catalog.families
    assert catalog.aliases


def test_family_catalog_resolve_known():
    catalog = FamilyCatalog()
    entry = catalog.resolve("usai", "claude_4_5_sonnet")
    assert entry is not None
    assert entry["vendor"] == "anthropic"
    assert entry["accepts_temperature"]["value"] is False


def test_family_catalog_resolve_unknown():
    catalog = FamilyCatalog()
    assert catalog.resolve("usai", "imaginary_model") is None
    assert catalog.resolve("nonexistent_provider", "claude_4_5_sonnet") is None


def test_family_catalog_aliases_preserve_major_version():
    """Aliases must NOT strip the major version. claude_4_5_sonnet → claude-sonnet-4,
    never claude-sonnet or claude. (Smoke against the BS draft we explicitly rejected.)"""
    catalog = FamilyCatalog()
    assert catalog.family_key("usai", "claude_4_5_sonnet") == "claude-sonnet-4"
    assert catalog.family_key("usai", "claude_4_5_opus") == "claude-opus-4"
    assert catalog.family_key("usai", "claude_4_5_haiku") == "claude-haiku-4"
    assert catalog.family_key("anthropic", "claude-sonnet-4-5-20241022") == "claude-sonnet-4"
    assert catalog.family_key("google", "gemini-2.5-flash") == "gemini-2.5"
    assert catalog.family_key("google", "gemini-2.0-flash") == "gemini-2.0"
    # Make sure no alias resolves to a version-stripped key.
    # `o-reasoning` is a deliberate exception that covers o1 and o3 together
    # (both reject sampling parameters); see the family catalog comment.
    versionless_exceptions = {"o-reasoning"}
    for prov, table in catalog.aliases.items():
        for alias, fam_key in table.items():
            assert fam_key in catalog.families, (
                f"alias {prov}.{alias!r} → {fam_key!r} which is not a family"
            )
            if fam_key in versionless_exceptions:
                continue
            assert any(c.isdigit() for c in fam_key), (
                f"family key {fam_key!r} for {prov}.{alias!r} has no version"
            )


def test_family_catalog_list_families():
    catalog = FamilyCatalog()
    families = catalog.list_families()
    assert "claude-sonnet-4" in families
    assert "gemini-2.5" in families
    assert "gpt-5" in families
    assert "o-reasoning" in families
