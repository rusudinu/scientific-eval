"""Configuration: TOML file + environment + CLI overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "scieval.toml"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

PASS_NAMES = ("pass0", "pass1", "pass2", "pass3", "pass4", "synthesis")


class ConfigError(RuntimeError):
    """Raised when the configuration is unusable."""


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    native_api: str | None = None

    def resolve_api_key(self) -> str:
        """Return the API key, reading the env var when the profile names one."""
        if self.api_key_env:
            value = os.environ.get(self.api_key_env)
            if not value:
                raise ConfigError(
                    f"provider '{self.name}' needs the {self.api_key_env} environment "
                    f"variable; set it in .env or the shell"
                )
            return value
        return self.api_key or "not-needed"


@dataclass
class SpellcheckConfig:
    backend: str = "pyspellchecker"
    min_token_length: int = 3
    max_candidates_per_section: int = 120


@dataclass
class SearchConfig:
    reference_provider: str = "crossref"
    web_provider: str = "none"
    max_results_per_query: int = 5
    searxng_url: str | None = None


@dataclass
class LimitsConfig:
    pass0_max_chars: int = 120000
    pass1_section_max_chars: int = 24000
    pass3_batch_size: int = 10


@dataclass
class Config:
    provider_name: str = "lmstudio"
    seed: int = 42
    temperature: float = 0.0
    request_timeout_s: float = 900.0
    output_dir: Path = Path("out")
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=dict)
    spellcheck: SpellcheckConfig = field(default_factory=SpellcheckConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    prompts_dir: Path = PROMPTS_DIR
    source_path: Path | None = None

    @property
    def provider(self) -> ProviderConfig:
        try:
            return self.providers[self.provider_name]
        except KeyError:
            known = ", ".join(sorted(self.providers)) or "none"
            raise ConfigError(
                f"unknown provider '{self.provider_name}'; configured providers: {known}"
            ) from None

    def model_for(self, pass_name: str) -> str | None:
        """Model id for a pass: per-pass override, else the default, else None."""
        return self.models.get(pass_name) or self.models.get("default")


def _find_config(explicit: Path | None) -> Path | None:
    if explicit:
        if not explicit.is_file():
            raise ConfigError(f"config file not found: {explicit}")
        return explicit
    cwd_config = Path.cwd() / "scieval.toml"
    if cwd_config.is_file():
        return cwd_config
    if DEFAULT_CONFIG_PATH.is_file():
        return DEFAULT_CONFIG_PATH
    return None


def load_config(
    path: Path | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    model_overrides: dict[str, str] | None = None,
    seed: int | None = None,
    temperature: float | None = None,
    output_dir: Path | None = None,
    web_provider: str | None = None,
) -> Config:
    """Load configuration from TOML, then apply env and explicit overrides."""
    config_path = _find_config(path)
    raw: dict[str, Any] = {}
    if config_path:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))

    cfg = Config(source_path=config_path)
    cfg.provider_name = raw.get("provider", cfg.provider_name)
    cfg.seed = int(raw.get("seed", cfg.seed))
    cfg.temperature = float(raw.get("temperature", cfg.temperature))
    cfg.request_timeout_s = float(raw.get("request_timeout_s", cfg.request_timeout_s))
    cfg.output_dir = Path(raw.get("output_dir", cfg.output_dir))

    for name, values in (raw.get("providers") or {}).items():
        cfg.providers[name] = ProviderConfig(
            name=name,
            base_url=values["base_url"],
            api_key=values.get("api_key"),
            api_key_env=values.get("api_key_env"),
            native_api=values.get("native_api"),
        )
    if not cfg.providers:
        cfg.providers["lmstudio"] = ProviderConfig(
            name="lmstudio",
            base_url="http://localhost:1234/v1",
            api_key="lm-studio",
            native_api="http://localhost:1234/api/v0",
        )

    cfg.models = {str(k): str(v) for k, v in (raw.get("models") or {}).items()}

    sc = raw.get("spellcheck") or {}
    cfg.spellcheck = SpellcheckConfig(
        backend=sc.get("backend", "pyspellchecker"),
        min_token_length=int(sc.get("min_token_length", 3)),
        max_candidates_per_section=int(sc.get("max_candidates_per_section", 120)),
    )

    se = raw.get("search") or {}
    cfg.search = SearchConfig(
        reference_provider=se.get("reference_provider", "crossref"),
        web_provider=se.get("web_provider", "none"),
        max_results_per_query=int(se.get("max_results_per_query", 5)),
        searxng_url=se.get("searxng_url") or os.environ.get("SEARXNG_URL"),
    )

    li = raw.get("limits") or {}
    cfg.limits = LimitsConfig(
        pass0_max_chars=int(li.get("pass0_max_chars", 120000)),
        pass1_section_max_chars=int(li.get("pass1_section_max_chars", 24000)),
        pass3_batch_size=int(li.get("pass3_batch_size", 10)),
    )

    # Environment overrides.
    if env_provider := os.environ.get("SCIEVAL_PROVIDER"):
        cfg.provider_name = env_provider
    if env_model := os.environ.get("SCIEVAL_MODEL"):
        cfg.models["default"] = env_model
    if env_base := os.environ.get("SCIEVAL_BASE_URL"):
        target = cfg.providers.get(cfg.provider_name)
        if target:
            target.base_url = env_base

    # Explicit overrides win.
    if provider:
        cfg.provider_name = provider
    if model:
        cfg.models["default"] = model
    for pass_name, value in (model_overrides or {}).items():
        cfg.models[pass_name] = value
    if seed is not None:
        cfg.seed = seed
    if temperature is not None:
        cfg.temperature = temperature
    if output_dir is not None:
        cfg.output_dir = output_dir
    if web_provider is not None:
        cfg.search.web_provider = web_provider

    return cfg
