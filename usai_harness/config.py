"""Config Loader/Validator: Model configs and project config management.

Responsibilities:
    - Load configs/models.yaml for known model definitions
    - Load project-specific config (model pool, defaults)
    - Validate at load time:
        - Model name exists in the merged catalog
        - default_model is a pool member
        - All pool members share the declared provider
        - Required fields present
    - Fail loud with actionable error messages on any validation failure

Per the ADR-012 amendment (2026-04-29), per-model `temperature` and `max_tokens`
overrides are NOT validated against catalog ranges. The harness forwards
whatever the user wrote to the transport; the provider's response is the source
of truth for parameter acceptance.

Inputs:
    - models_config_path: str — path to models.yaml
    - project_config_path: Optional[str] — path to project config

Outputs:
    - ModelConfig dataclass with catalog identity and accounting fields
    - get_model(name) — returns the model config or raises

Errors:
    - ConfigValidationError: raised on any invalid config with specific field/reason
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("usai_harness.config")

DEFAULT_WORKERS = 3
DEFAULT_BATCH_SIZE = 50
MAX_WORKERS = 10

DEFAULT_ERROR_BODY_SNIPPET_MAX_CHARS = 200
MAX_ERROR_BODY_SNIPPET_MAX_CHARS = 2000

_KNOWN_PROJECT_FIELDS = frozenset({
    "model", "models", "default_model", "provider",
    "temperature", "max_tokens",
    "system_prompt", "workers", "batch_size",
    "credentials",
})

_VALID_CREDENTIALS_BACKENDS = frozenset({"dotenv", "env_var", "azure_keyvault"})


class ConfigValidationError(Exception):
    """Raised when config validation fails. Message includes the specific field and reason."""
    pass


class FamilyCatalog:
    """Curated family-level model parameter catalog. Ships with the harness.

    Per ADR-014, the catalog answers "what parameters does this model
    accept" with citation-tier labels per field. It is keyed on
    vendor + product line + major version. Provider-specific identifiers
    (e.g. `claude_4_5_sonnet`, `gemini-2.5-flash`) are mapped to family
    keys via the `provider_aliases` table so that adding a new dated SKU
    under an existing major line is a one-row alias addition, not a new
    family entry.
    """

    def __init__(self, path: Optional[Path] = None):
        if path is None:
            path = (
                Path(__file__).resolve().parent / "data" / "families.yaml"
            )
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (FileNotFoundError, yaml.YAMLError) as e:
            raise ConfigValidationError(
                f"Failed to load family catalog at {path}: {e}"
            ) from e
        if not isinstance(raw, dict):
            raise ConfigValidationError(
                f"Family catalog at {path} is not a YAML mapping."
            )
        self.path = path
        self.metadata: dict = raw.get("metadata", {}) or {}
        self.families: dict = raw.get("families", {}) or {}
        self.aliases: dict = raw.get("provider_aliases", {}) or {}

    def family_key(self, provider: str, name: str) -> Optional[str]:
        """Return the family key for `(provider, name)` or None if unknown."""
        return (self.aliases.get(provider) or {}).get(name)

    def resolve(self, provider: str, name: str) -> Optional[dict]:
        """Resolve a provider-specific model name to its family entry.

        Returns the family entry dict, or None if `name` is not in the
        alias table for the given provider. The caller decides what to do
        on miss (warn and pass through, or strict-reject).
        """
        key = self.family_key(provider, name)
        if key is None:
            return None
        return self.families.get(key)

    def list_families(self) -> list[str]:
        return list(self.families.keys())

    def list_aliases(self, provider: Optional[str] = None) -> dict:
        if provider is None:
            return self.aliases
        return self.aliases.get(provider, {}) or {}


@dataclass(frozen=True)
class ModelConfig:
    """Catalog entry for a specific model.

    Per the ADR-012 amendment (2026-04-29), the runtime catalog describes
    identity (name, provider) and accounting (cost rates, context window).
    Per ADR-014 (2026-04-29), each entry also carries an optional
    `family_entry` resolved through the curated family catalog plus the
    `family_key` it was matched on. The family entry is what supplies the
    parameter-acceptance rules used at config-load time.
    """
    name: str
    provider: str
    context_window: int
    supports_temperature: bool
    supports_system_prompt: bool
    cost_per_1k_input_tokens: float
    cost_per_1k_output_tokens: float
    family_key: Optional[str] = field(default=None, compare=False, hash=False)
    family_entry: Optional[dict] = field(default=None, compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class ProviderConfig:
    """Endpoint-provider metadata loaded from the 'providers' block in models.yaml.

    `api_key_env` names an OS environment variable for DotEnv/EnvVar backends.
    `api_key_secret` names a Key Vault secret for the Azure backend. The two
    fields are scoped per backend; a provider entry that supports multiple
    backends can populate both. The Azure backend strictly requires
    `api_key_secret`; an Azure provider entry that only sets `api_key_env`
    raises `ConfigValidationError`.
    """
    name: str
    base_url: str
    api_key_env: Optional[str] = None
    api_key_secret: Optional[str] = None


@dataclass
class ProjectConfig:
    """Validated project-level configuration.

    Per ADR-012, a project carries a pool of models. `default_model` is the
    pool member used when a task does not select a model explicitly. `provider`
    is the endpoint provider; every pool member's catalog `provider` field
    must equal this value (cross-provider pools are rejected).

    `temperature`, `max_tokens`, and `system_prompt` are project-level defaults
    used when a task does not override them. Per the ADR-012 amendment
    (2026-04-29), these values are not validated against catalog ranges; they
    are forwarded to the transport as-is, and provider response is the source
    of truth for what is accepted.
    """
    models: list[ModelConfig]
    default_model: ModelConfig
    provider: str
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    system_prompt: Optional[str] = None
    workers: int = DEFAULT_WORKERS
    batch_size: int = DEFAULT_BATCH_SIZE
    credentials_backend: str = "dotenv"
    credentials_kwargs: dict = field(default_factory=dict)

    def has_model(self, name: str) -> bool:
        """Return True when `name` is a pool member."""
        return any(m.name == name for m in self.models)

    def get_pool_model(self, name: str) -> ModelConfig:
        """Return the pool member with the given name, or raise ConfigValidationError."""
        for m in self.models:
            if m.name == name:
                return m
        raise ConfigValidationError(
            f"Model '{name}' is not in the project's pool. "
            f"Pool members: {[m.name for m in self.models]}."
        )


def _load_user_catalog(
    path: Optional[Path] = None,
) -> tuple[dict, Optional[Path]]:
    """Load the user-level models.yaml if present.

    Returns (catalog, resolved_path). resolved_path is the location consulted
    even if it does not exist, so callers can include it in log messages.
    Lazy-imports the path helper from setup_commands to avoid circular imports.
    """
    if path is None:
        from usai_harness.setup_commands import user_config_models_path
        path = user_config_models_path()
    if not path.exists():
        return {}, path
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return {}, path
    if not isinstance(raw, dict):
        return {}, path
    return raw, path


_PARAM_TO_FAMILY_KEY = {
    "temperature": "accepts_temperature",
    "top_p": "accepts_top_p",
    "top_k": "accepts_top_k",
    "frequency_penalty": "accepts_frequency_penalty",
    "presence_penalty": "accepts_presence_penalty",
}


class ConfigLoader:
    """Loads and validates model and project configurations."""

    def __init__(self, models_config_path=None, family_catalog=None):
        self.family_catalog: FamilyCatalog = (
            family_catalog if family_catalog is not None else FamilyCatalog()
        )
        if models_config_path is None:
            # Default: <repo_root>/configs/models.yaml (parent of this package dir).
            models_config_path = (
                Path(__file__).resolve().parent.parent / "configs" / "models.yaml"
            )
        self.models_config_path = Path(models_config_path)

        if not self.models_config_path.exists():
            raise ConfigValidationError(
                f"Models config file not found: {self.models_config_path}. "
                f"Create it or pass an explicit models_config_path."
            )

        try:
            raw = yaml.safe_load(self.models_config_path.read_text())
        except yaml.YAMLError as e:
            raise ConfigValidationError(
                f"Failed to parse {self.models_config_path}: {e}"
            ) from e

        if not isinstance(raw, dict) or "models" not in raw:
            raise ConfigValidationError(
                f"Invalid {self.models_config_path}: expected top-level 'models' mapping."
            )

        snippet_raw = raw.get(
            "error_body_snippet_max_chars", DEFAULT_ERROR_BODY_SNIPPET_MAX_CHARS
        )
        if isinstance(snippet_raw, bool) or not isinstance(snippet_raw, int):
            raise ConfigValidationError(
                f"error_body_snippet_max_chars in {self.models_config_path} "
                f"must be a positive integer; got {snippet_raw!r}."
            )
        if snippet_raw < 1 or snippet_raw > MAX_ERROR_BODY_SNIPPET_MAX_CHARS:
            raise ConfigValidationError(
                f"error_body_snippet_max_chars={snippet_raw} out of range. "
                f"Must be 1..{MAX_ERROR_BODY_SNIPPET_MAX_CHARS}."
            )
        self.error_body_snippet_max_chars: int = snippet_raw

        self._models: dict[str, ModelConfig] = {}
        for name, spec in raw["models"].items():
            try:
                provider = spec["provider"]
                fam_key = self.family_catalog.family_key(provider, name)
                fam_entry = self.family_catalog.resolve(provider, name)
                self._models[name] = ModelConfig(
                    name=name,
                    provider=provider,
                    context_window=int(spec["context_window"]),
                    supports_temperature=bool(spec["supports_temperature"]),
                    supports_system_prompt=bool(spec["supports_system_prompt"]),
                    cost_per_1k_input_tokens=float(spec["cost_per_1k_input_tokens"]),
                    cost_per_1k_output_tokens=float(spec["cost_per_1k_output_tokens"]),
                    family_key=fam_key,
                    family_entry=fam_entry,
                )
            except KeyError as e:
                raise ConfigValidationError(
                    f"Model '{name}' in {self.models_config_path} is missing "
                    f"required field: {e}."
                ) from e

        self._default_model_name: Optional[str] = raw.get("default_model")
        if self._default_model_name and self._default_model_name not in self._models:
            raise ConfigValidationError(
                f"default_model '{self._default_model_name}' in "
                f"{self.models_config_path} is not defined in the models list. "
                f"Available: {sorted(self._models)}."
            )

        self._providers: dict[str, ProviderConfig] = {}
        raw_providers = raw.get("providers", {})
        if not isinstance(raw_providers, dict):
            raise ConfigValidationError(
                f"Invalid {self.models_config_path}: 'providers' must be a mapping if present."
            )
        for prov_name, prov_spec in raw_providers.items():
            if not isinstance(prov_spec, dict):
                raise ConfigValidationError(
                    f"Provider '{prov_name}' in {self.models_config_path} "
                    f"must be a mapping."
                )
            if "base_url" not in prov_spec:
                raise ConfigValidationError(
                    f"Provider '{prov_name}' in {self.models_config_path} is "
                    f"missing required field: 'base_url'."
                )
            api_key_env = prov_spec.get("api_key_env")
            api_key_secret = prov_spec.get("api_key_secret")
            if api_key_env is None and api_key_secret is None:
                raise ConfigValidationError(
                    f"Provider '{prov_name}' in {self.models_config_path} "
                    f"must specify either 'api_key_env' or 'api_key_secret'."
                )
            self._providers[prov_name] = ProviderConfig(
                name=prov_name,
                base_url=str(prov_spec["base_url"]),
                api_key_env=str(api_key_env) if api_key_env is not None else None,
                api_key_secret=(
                    str(api_key_secret) if api_key_secret is not None else None
                ),
            )

        for model_name, model_cfg in self._models.items():
            if model_cfg.provider not in self._providers:
                raise ConfigValidationError(
                    f"Model '{model_name}' references provider "
                    f"'{model_cfg.provider}' which is not defined in the "
                    f"'providers' block. Known providers: {sorted(self._providers)}."
                )

        user_catalog, user_catalog_path = _load_user_catalog()
        if user_catalog:
            self._apply_live_catalog(user_catalog, user_catalog_path)

    def _apply_live_catalog(
        self,
        user_catalog: dict,
        catalog_path: Optional[Path] = None,
    ) -> None:
        """Merge the user-level live catalog into providers and models.

        Rules per ADR-009 / FR-040:
            1. User-level provider entries override repo-level base_url and api_key_env.
            2. User-level 'models' list per provider is authoritative.
            3. Repo-level model entries that match a live model ID contribute
               presentation overrides.
            4. Repo-level model entries not present in the live catalog are dropped.
            5. Live model IDs not present in the repo are added with defaults.
        """
        live_providers = user_catalog.get("providers", {})
        if not isinstance(live_providers, dict):
            return

        seed_model_ids = set(self._models.keys())
        authoritative: set[tuple[str, str]] = set()

        for prov_name, prov_spec in live_providers.items():
            if not isinstance(prov_spec, dict):
                continue
            existing = self._providers.get(prov_name)
            base_url = prov_spec.get("base_url") or (existing.base_url if existing else "")
            api_key_env = prov_spec.get("api_key_env") or (
                existing.api_key_env if existing else None
            )
            api_key_secret = prov_spec.get("api_key_secret") or (
                existing.api_key_secret if existing else None
            )
            self._providers[prov_name] = ProviderConfig(
                name=prov_name,
                base_url=str(base_url),
                api_key_env=str(api_key_env) if api_key_env is not None else None,
                api_key_secret=(
                    str(api_key_secret) if api_key_secret is not None else None
                ),
            )
            for model_id in prov_spec.get("models", []) or []:
                authoritative.add((prov_name, str(model_id)))

        if not authoritative:
            return

        new_models: dict[str, ModelConfig] = {}
        for prov_name, model_id in authoritative:
            existing = self._models.get(model_id)
            fam_key = self.family_catalog.family_key(prov_name, model_id)
            fam_entry = self.family_catalog.resolve(prov_name, model_id)
            if existing is not None:
                new_models[model_id] = ModelConfig(
                    name=model_id,
                    provider=prov_name,
                    context_window=existing.context_window,
                    supports_temperature=existing.supports_temperature,
                    supports_system_prompt=existing.supports_system_prompt,
                    cost_per_1k_input_tokens=existing.cost_per_1k_input_tokens,
                    cost_per_1k_output_tokens=existing.cost_per_1k_output_tokens,
                    family_key=fam_key,
                    family_entry=fam_entry,
                )
            else:
                new_models[model_id] = ModelConfig(
                    name=model_id,
                    provider=prov_name,
                    context_window=0,
                    supports_temperature=True,
                    supports_system_prompt=True,
                    cost_per_1k_input_tokens=0.0,
                    cost_per_1k_output_tokens=0.0,
                    family_key=fam_key,
                    family_entry=fam_entry,
                )

        self._models = new_models

        dropped = sorted(seed_model_ids - set(new_models.keys()))
        if dropped:
            log.warning(
                "Models present in seed config but not in live catalog at %s "
                "have been dropped: %s. This is expected if the endpoint no "
                "longer advertises them; verify the live catalog is current "
                "if unexpected.",
                catalog_path, dropped,
            )

        if self._default_model_name and self._default_model_name not in self._models:
            if self._models:
                fallback = next(iter(self._models))
                log.warning(
                    "default_model '%s' was dropped by live catalog merge. "
                    "Falling back to '%s'.",
                    self._default_model_name, fallback,
                )
                self._default_model_name = fallback
            else:
                self._default_model_name = None

    def list_models(self) -> list[str]:
        """Return list of available model names."""
        return list(self._models.keys())

    def get_model(self, name: str) -> ModelConfig:
        """Return the ModelConfig for the given model name, or raise."""
        if name not in self._models:
            raise ConfigValidationError(
                f"Unknown model '{name}'. Available models: {sorted(self._models)}."
            )
        return self._models[name]

    def list_providers(self) -> list[str]:
        """Return list of registered provider names."""
        return list(self._providers.keys())

    def get_provider(self, name: str) -> ProviderConfig:
        """Return the ProviderConfig for the named provider, or raise."""
        if name not in self._providers:
            raise ConfigValidationError(
                f"Unknown provider '{name}'. Available providers: "
                f"{sorted(self._providers)}."
            )
        return self._providers[name]

    def providers_to_env_map(self) -> dict[str, str]:
        """Return {provider_name: api_key_env} for env-based credential backends.

        Skips providers that do not have api_key_env (Azure-only entries).
        """
        return {
            name: cfg.api_key_env
            for name, cfg in self._providers.items()
            if cfg.api_key_env
        }

    def providers_to_secret_map(self) -> dict[str, str]:
        """Return {provider_name: secret_name} for the Azure Key Vault backend.

        Every provider must define `api_key_secret`. A provider that lacks it
        raises `ConfigValidationError`; the previous fallback to `api_key_env`
        was removed when the deprecation window closed.
        """
        out: dict[str, str] = {}
        for name, cfg in self._providers.items():
            if not cfg.api_key_secret:
                raise ConfigValidationError(
                    f"Provider '{name}' has no 'api_key_secret'. The Azure "
                    f"Key Vault backend requires a Key Vault secret name; "
                    f"'api_key_env' is not accepted as a synonym. Update the "
                    f"'providers:' block in your models.yaml."
                )
            out[name] = cfg.api_key_secret
        return out

    def get_default_model(self) -> ModelConfig:
        """Return the ModelConfig for the yaml's default_model."""
        if not self._default_model_name:
            raise ConfigValidationError(
                f"No default_model set in {self.models_config_path}."
            )
        return self._models[self._default_model_name]

    def load_project_config(self, config_path) -> ProjectConfig:
        """Load, validate, and return a project-specific config (ADR-011, ADR-012)."""
        config_path = Path(config_path)
        try:
            raw = yaml.safe_load(config_path.read_text())
        except yaml.YAMLError as e:
            raise ConfigValidationError(
                f"Failed to parse project config {config_path}: {e}"
            ) from e

        if not isinstance(raw, dict):
            raise ConfigValidationError(
                f"Project config {config_path} must be a YAML mapping."
            )

        for unknown in sorted(set(raw.keys()) - _KNOWN_PROJECT_FIELDS):
            log.warning(
                "Unknown field '%s' in project config %s; ignoring. "
                "Valid fields: %s.",
                unknown, config_path, sorted(_KNOWN_PROJECT_FIELDS),
            )

        pool_specs, default_model_name = self._collect_pool_specs(raw, config_path)
        pool = self._validate_pool(pool_specs, config_path)
        self._validate_pool_param_overrides(pool, pool_specs, config_path)

        if default_model_name is None:
            if len(pool) == 1:
                default_model = pool[0]
            else:
                raise ConfigValidationError(
                    f"Project config {config_path} declares {len(pool)} "
                    f"pool members; 'default_model' is required when the "
                    f"pool has more than one member."
                )
        else:
            try:
                default_model = next(m for m in pool if m.name == default_model_name)
            except StopIteration:
                raise ConfigValidationError(
                    f"Project config {config_path}: default_model "
                    f"'{default_model_name}' is not a pool member. "
                    f"Pool: {[m.name for m in pool]}."
                ) from None

        explicit_provider = raw.get("provider")
        if explicit_provider is not None:
            mismatched = [
                m.name for m in pool if m.provider != explicit_provider
            ]
            if mismatched:
                raise ConfigValidationError(
                    f"Project config {config_path}: 'provider' is "
                    f"'{explicit_provider}' but pool members "
                    f"{mismatched} use different providers. Cross-provider "
                    f"pools are not supported (ADR-012)."
                )
            provider = explicit_provider
        else:
            providers_in_pool = {m.provider for m in pool}
            if len(providers_in_pool) > 1:
                raise ConfigValidationError(
                    f"Project config {config_path}: pool members use "
                    f"multiple providers {sorted(providers_in_pool)}. "
                    f"Declare a top-level 'provider:' or split into one "
                    f"client per provider."
                )
            provider = next(iter(providers_in_pool))

        temperature = float(raw.get("temperature", 0.0))
        max_tokens_raw = raw.get("max_tokens")
        max_tokens = int(max_tokens_raw) if max_tokens_raw is not None else None

        if "temperature" in raw:
            self._check_param_against_family(
                default_model, "temperature", float(raw["temperature"]),
                config_path, context="project default",
            )
        if max_tokens is not None:
            self._check_max_tokens_against_family(
                default_model, max_tokens,
                config_path, context="project default",
            )

        workers = int(raw.get("workers", DEFAULT_WORKERS))
        if not (1 <= workers <= MAX_WORKERS):
            raise ConfigValidationError(
                f"workers={workers} out of range. Must be 1..{MAX_WORKERS}."
            )

        batch_size = int(raw.get("batch_size", DEFAULT_BATCH_SIZE))
        if batch_size < 1:
            raise ConfigValidationError(
                f"batch_size={batch_size} must be >= 1."
            )

        creds_block = raw.get("credentials", {})
        if not isinstance(creds_block, dict):
            raise ConfigValidationError(
                f"Project config {config_path}: 'credentials' must be a "
                f"mapping if present."
            )
        credentials_backend = creds_block.get("backend", "dotenv")
        if credentials_backend not in _VALID_CREDENTIALS_BACKENDS:
            raise ConfigValidationError(
                f"Project config {config_path}: unknown credentials.backend "
                f"'{credentials_backend}'. "
                f"Valid: {sorted(_VALID_CREDENTIALS_BACKENDS)}."
            )
        credentials_kwargs = {
            k: v for k, v in creds_block.items() if k != "backend"
        }

        return ProjectConfig(
            models=pool,
            default_model=default_model,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=raw.get("system_prompt"),
            workers=workers,
            batch_size=batch_size,
            credentials_backend=credentials_backend,
            credentials_kwargs=credentials_kwargs,
        )

    def _collect_pool_specs(
        self, raw: dict, config_path: Path,
    ) -> tuple[list[dict], Optional[str]]:
        """Return (list of {name, overrides...}, default_model_name_or_None).

        Translates the legacy single-`model:` form into a one-element pool.
        Rejects configs that declare both `model` and `models`.
        """
        has_legacy = "model" in raw
        has_pool = "models" in raw

        if has_legacy and has_pool:
            raise ConfigValidationError(
                f"Project config {config_path} declares both 'model' "
                f"(legacy single-model form) and 'models' (pool form). "
                f"Use one or the other; the legacy form is auto-translated."
            )

        if has_legacy:
            legacy_name = raw["model"]
            if not isinstance(legacy_name, str) or not legacy_name:
                raise ConfigValidationError(
                    f"Project config {config_path}: 'model' must be a "
                    f"non-empty string in the legacy form."
                )
            return [{"name": legacy_name}], legacy_name

        if not has_pool:
            raise ConfigValidationError(
                f"Project config {config_path} is missing the required "
                f"'models' field (or the legacy single 'model' field). "
                f"Available models: {sorted(self._models)}."
            )

        pool_raw = raw["models"]
        if not isinstance(pool_raw, list) or not pool_raw:
            raise ConfigValidationError(
                f"Project config {config_path}: 'models' must be a "
                f"non-empty list of pool members."
            )

        specs: list[dict] = []
        for i, member in enumerate(pool_raw):
            if isinstance(member, str):
                specs.append({"name": member})
                continue
            if not isinstance(member, dict) or "name" not in member:
                raise ConfigValidationError(
                    f"Project config {config_path}: pool member at index "
                    f"{i} must be a string or a mapping with a 'name' key."
                )
            specs.append(dict(member))

        return specs, raw.get("default_model")

    def _validate_pool_param_overrides(
        self,
        pool: list[ModelConfig],
        specs: list[dict],
        config_path: Path,
    ) -> None:
        """Validate per-member parameter overrides against the family catalog.

        Per ADR-014 (2026-04-29): if the pool member resolves to a family
        entry, walk recognized parameter overrides and apply the family's
        accept-flags and ranges. Unknown aliases warn and pass through.
        """
        for spec, model in zip(specs, pool):
            if model.family_entry is None:
                log.warning(
                    "Pool member '%s' (provider '%s') does not match any "
                    "family-catalog alias; per-model parameter validation "
                    "is skipped for this member. Field values pass through "
                    "to the transport unchanged.",
                    model.name, model.provider,
                )
                continue
            for param_name, value in spec.items():
                if param_name == "name":
                    continue
                if param_name in _PARAM_TO_FAMILY_KEY:
                    self._check_param_against_family(
                        model, param_name, value, config_path,
                        context=f"pool member '{model.name}'",
                    )
                elif param_name == "max_tokens":
                    self._check_max_tokens_against_family(
                        model, int(value), config_path,
                        context=f"pool member '{model.name}'",
                    )

    @staticmethod
    def _check_param_against_family(
        model: ModelConfig,
        param_name: str,
        value,
        config_path: Path,
        context: str,
    ) -> None:
        family_entry = model.family_entry
        if family_entry is None:
            return
        family_field = _PARAM_TO_FAMILY_KEY.get(param_name)
        if family_field is None:
            return
        spec = family_entry.get(family_field)
        if not isinstance(spec, dict):
            return
        accepts = spec.get("value")
        if accepts is False:
            raise ConfigValidationError(
                f"Project config {config_path}: {context} sets "
                f"{param_name}={value!r}, but family '{model.family_key}' "
                f"does not accept {param_name} on this model. Source: "
                f"{spec.get('source', '(no source recorded)')}."
            )
        if accepts == "needs_verification":
            log.warning(
                "Project config %s: %s sets %s=%r, but the family catalog "
                "marks %s.%s as needs_verification. Passing through; "
                "verify behavior empirically before relying on the value.",
                config_path, context, param_name, value,
                model.family_key, family_field,
            )
            return
        if accepts is not True:
            return
        rng = spec.get("range")
        if rng == "needs_verification":
            log.warning(
                "Project config %s: %s sets %s=%r; the family catalog "
                "marks the range as needs_verification. Passing through.",
                config_path, context, param_name, value,
            )
            return
        if isinstance(rng, list) and len(rng) == 2:
            low, high = rng
            if not (low <= value <= high):
                raise ConfigValidationError(
                    f"Project config {config_path}: {context} sets "
                    f"{param_name}={value} which is outside the family "
                    f"'{model.family_key}' range [{low}, {high}]. Source: "
                    f"{spec.get('source', '(no source recorded)')}."
                )

    @staticmethod
    def _check_max_tokens_against_family(
        model: ModelConfig,
        value: int,
        config_path: Path,
        context: str,
    ) -> None:
        family_entry = model.family_entry
        if family_entry is None:
            return
        spec = family_entry.get("max_output_tokens")
        if not isinstance(spec, dict):
            return
        max_val = spec.get("value")
        if max_val == "needs_verification":
            log.warning(
                "Project config %s: %s sets max_tokens=%d; the family "
                "catalog marks max_output_tokens as needs_verification. "
                "Passing through.",
                config_path, context, value,
            )
            return
        if isinstance(max_val, int) and value > max_val:
            raise ConfigValidationError(
                f"Project config {config_path}: {context} sets "
                f"max_tokens={value} which exceeds family "
                f"'{model.family_key}' max_output_tokens={max_val}."
            )

    def _validate_pool(
        self, specs: list[dict], config_path: Path,
    ) -> list[ModelConfig]:
        """Resolve each pool member to a ModelConfig.

        Catalog membership is validated; per-member `temperature` and
        `max_tokens` are accepted as-is and forwarded to the transport at call
        time (per the ADR-012 amendment, 2026-04-29). Provider response is the
        source of truth for whether those values are accepted.
        """
        seen: set[str] = set()
        resolved: list[ModelConfig] = []
        for spec in specs:
            name = spec["name"]
            if name in seen:
                raise ConfigValidationError(
                    f"Project config {config_path}: pool contains duplicate "
                    f"model '{name}'."
                )
            seen.add(name)
            try:
                model = self.get_model(name)
            except ConfigValidationError as e:
                raise ConfigValidationError(
                    f"Project config {config_path}: pool member '{name}' "
                    f"is not in the merged catalog. {e}"
                ) from e
            resolved.append(model)

        return resolved

    def validate_request(self, model_config: ModelConfig,
                         prompt_tokens: int, max_tokens: int) -> None:
        """Pre-flight: ensure prompt + output won't overflow the context window."""
        total = prompt_tokens + max_tokens
        if total > model_config.context_window:
            raise ConfigValidationError(
                f"Request would exceed context window for '{model_config.name}': "
                f"prompt_tokens={prompt_tokens} + max_tokens={max_tokens} "
                f"= {total} > context_window={model_config.context_window}."
            )
