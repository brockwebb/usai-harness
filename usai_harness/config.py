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
