"""Config Loader/Validator: Model configs and project config management.

Responsibilities:
    - Load configs/models.yaml for known model definitions
    - Load project-specific config (model selection, parameters)
    - Validate at load time:
        - Model name exists in known models
        - Temperature within model's valid range
        - Prompt + max_output_tokens does not exceed context window
        - Required fields present
    - Fail loud with actionable error messages on any validation failure

Inputs:
    - models_config_path: str — path to models.yaml
    - project_config_path: Optional[str] — path to project config

Outputs:
    - ModelConfig dataclass with validated parameters
    - get_model(name) — returns validated model config or raises

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

_KNOWN_PROJECT_FIELDS = frozenset({
    "model", "temperature", "max_tokens",
    "system_prompt", "workers", "batch_size",
    "credentials",
})

_VALID_CREDENTIALS_BACKENDS = frozenset({"dotenv", "env_var", "azure_keyvault"})


class ConfigValidationError(Exception):
    """Raised when config validation fails. Message includes the specific field and reason."""
    pass


@dataclass(frozen=True)
class ModelConfig:
    """Validated configuration for a specific model."""
    name: str
    provider: str
    context_window: int
    max_output_tokens: int
    supports_temperature: bool
    temperature_range: tuple[float, float]
    supports_system_prompt: bool
    cost_per_1k_input_tokens: float
    cost_per_1k_output_tokens: float


@dataclass(frozen=True)
class ProviderConfig:
    """Endpoint-provider metadata loaded from the 'providers' block in models.yaml."""
    name: str
    base_url: str
    api_key_env: str


@dataclass
class ProjectConfig:
    """Validated project-level configuration."""
    model: ModelConfig
    temperature: float = 0.0
    max_tokens: Optional[int] = None  # defaults to model's max_output_tokens
    system_prompt: Optional[str] = None
    workers: int = DEFAULT_WORKERS
    batch_size: int = DEFAULT_BATCH_SIZE
    credentials_backend: str = "dotenv"
    credentials_kwargs: dict = field(default_factory=dict)


class ConfigLoader:
    """Loads and validates model and project configurations."""

    def __init__(self, models_config_path=None):
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

        self._models: dict[str, ModelConfig] = {}
        for name, spec in raw["models"].items():
            try:
                self._models[name] = ModelConfig(
                    name=name,
                    provider=spec["provider"],
                    context_window=int(spec["context_window"]),
                    max_output_tokens=int(spec["max_output_tokens"]),
                    supports_temperature=bool(spec["supports_temperature"]),
                    temperature_range=tuple(spec["temperature_range"]),
                    supports_system_prompt=bool(spec["supports_system_prompt"]),
                    cost_per_1k_input_tokens=float(spec["cost_per_1k_input_tokens"]),
                    cost_per_1k_output_tokens=float(spec["cost_per_1k_output_tokens"]),
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
            try:
                self._providers[prov_name] = ProviderConfig(
                    name=prov_name,
                    base_url=str(prov_spec["base_url"]),
                    api_key_env=str(prov_spec["api_key_env"]),
                )
            except KeyError as e:
                raise ConfigValidationError(
                    f"Provider '{prov_name}' in {self.models_config_path} is "
                    f"missing required field: {e}."
                ) from e

        for model_name, model_cfg in self._models.items():
            if model_cfg.provider not in self._providers:
                raise ConfigValidationError(
                    f"Model '{model_name}' references provider "
                    f"'{model_cfg.provider}' which is not defined in the "
                    f"'providers' block. Known providers: {sorted(self._providers)}."
                )

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
        """Return {provider_name: api_key_env} for handing to make_credential_provider."""
        return {name: cfg.api_key_env for name, cfg in self._providers.items()}

    def get_default_model(self) -> ModelConfig:
        """Return the ModelConfig for the yaml's default_model."""
        if not self._default_model_name:
            raise ConfigValidationError(
                f"No default_model set in {self.models_config_path}."
            )
        return self._models[self._default_model_name]

    def load_project_config(self, config_path) -> ProjectConfig:
        """Load, validate, and return a project-specific config."""
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

        model_name = raw.get("model")
        if not model_name:
            raise ConfigValidationError(
                f"Project config {config_path} is missing required field 'model'. "
                f"Available models: {sorted(self._models)}."
            )
        model = self.get_model(model_name)

        for unknown in sorted(set(raw.keys()) - _KNOWN_PROJECT_FIELDS):
            log.warning(
                "Unknown field '%s' in project config %s — ignoring. "
                "Valid fields: %s.",
                unknown, config_path, sorted(_KNOWN_PROJECT_FIELDS),
            )

        temperature = 0.0
        if "temperature" in raw:
            temperature = float(raw["temperature"])
            if not model.supports_temperature:
                raise ConfigValidationError(
                    f"Model '{model.name}' does not support a temperature "
                    f"parameter, but project config sets temperature={temperature}."
                )
            low, high = model.temperature_range
            if not (low <= temperature <= high):
                raise ConfigValidationError(
                    f"temperature={temperature} out of range for model "
                    f"'{model.name}'. Valid range: [{low}, {high}]."
                )

        max_tokens = raw.get("max_tokens")
        if max_tokens is not None:
            max_tokens = int(max_tokens)
            if max_tokens <= 0:
                raise ConfigValidationError(
                    f"max_tokens must be > 0, got {max_tokens}."
                )
            if max_tokens > model.max_output_tokens:
                raise ConfigValidationError(
                    f"max_tokens={max_tokens} exceeds model '{model.name}' "
                    f"limit of {model.max_output_tokens}."
                )
        else:
            max_tokens = model.max_output_tokens

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
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=raw.get("system_prompt"),
            workers=workers,
            batch_size=batch_size,
            credentials_backend=credentials_backend,
            credentials_kwargs=credentials_kwargs,
        )

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
