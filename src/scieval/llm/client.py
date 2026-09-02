"""OpenAI-compatible chat client (LM Studio, OpenRouter, anything else with /v1)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Config, ConfigError


class LLMError(RuntimeError):
    """Raised when the endpoint cannot be reached or refuses the request."""


@dataclass
class ChatResult:
    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0
    finish_reason: str = ""


class LLMClient:
    """Thin wrapper over the OpenAI SDK, holding provider settings and call defaults."""

    def __init__(
        self, config: Config, *, timeout: float | None = None, http_client: Any = None
    ) -> None:
        from openai import OpenAI

        self.config = config
        self.provider = config.provider
        # `http_client` lets tests and proxy setups supply their own transport. The
        # OpenAI SDK vendors its own httpx build, so the object must come from there.
        extra = {"http_client": http_client} if http_client is not None else {}
        self._client = OpenAI(
            base_url=self.provider.base_url,
            api_key=self.provider.resolve_api_key(),
            timeout=timeout if timeout is not None else config.request_timeout_s,
            max_retries=2,
            **extra,
        )
        self._models_cache: list[dict[str, Any]] | None = None

    @property
    def base_url(self) -> str:
        return str(self.provider.base_url)

    def list_models(self) -> list[dict[str, Any]]:
        if self._models_cache is None:
            try:
                response = self._client.models.list()
            except Exception as exc:  # network, auth, wrong port
                raise LLMError(f"cannot list models at {self.base_url}: {exc}") from exc
            self._models_cache = [m.model_dump() for m in response.data]
        return self._models_cache

    def resolve_model(self, requested: str | None) -> str:
        """Use the requested model, or the first chat model the server reports."""
        if requested:
            return requested
        models = self.list_models()
        if not models:
            raise ConfigError(
                f"no model configured and {self.base_url} reports none; "
                f"set [models].default in scieval.toml or pass --model"
            )
        for entry in models:
            model_id = str(entry.get("id", ""))
            if not _looks_like_embedding(model_id, entry):
                return model_id
        raise ConfigError(
            f"{self.base_url} reports only embedding models; load a chat model in the server "
            f"or set [models].default in scieval.toml"
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        response_format: dict[str, Any] | None = None,
        seed: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
        }
        effective_seed = self.config.seed if seed is None else seed
        if effective_seed is not None:
            kwargs["seed"] = effective_seed
        if response_format is not None:
            kwargs["response_format"] = response_format
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMError(f"chat completion failed on {model}: {exc}") from exc
        duration = time.monotonic() - started

        choice = response.choices[0] if response.choices else None
        text = (choice.message.content or "") if choice else ""
        usage = response.usage.model_dump() if response.usage else {}
        return ChatResult(
            text=text,
            model=getattr(response, "model", model) or model,
            usage={k: v for k, v in usage.items() if isinstance(v, int)},
            duration_s=round(duration, 2),
            finish_reason=(choice.finish_reason or "") if choice else "",
        )

    def native_model_info(self, model_id: str) -> dict[str, Any]:
        """Provider-specific metadata (quantization), best effort."""
        if self.provider.native_api:
            info = _lmstudio_model_info(self.provider.native_api, model_id)
            if info:
                return info
        if "openrouter" in self.base_url:
            return _openrouter_model_info(model_id)
        return {}


def _looks_like_embedding(model_id: str, entry: dict[str, Any]) -> bool:
    """Embedding models are listed alongside chat models and cannot answer a pass."""
    if str(entry.get("type") or "").lower() in {"embedding", "embeddings"}:
        return True
    lowered = model_id.lower()
    return any(marker in lowered for marker in ("embed", "reranker", "rerank"))


def _lmstudio_model_info(native_api: str, model_id: str) -> dict[str, Any]:
    try:
        response = httpx.get(f"{native_api.rstrip('/')}/models", timeout=5.0)
        response.raise_for_status()
        for entry in response.json().get("data", []):
            if entry.get("id") == model_id:
                return {
                    "quantization": entry.get("quantization"),
                    "architecture": entry.get("arch"),
                    "context_length": entry.get("max_context_length"),
                    "publisher": entry.get("publisher"),
                    "source": "lmstudio_native_api",
                }
    except Exception:
        return {}
    return {}


def _openrouter_model_info(model_id: str) -> dict[str, Any]:
    try:
        response = httpx.get(
            f"https://openrouter.ai/api/v1/models/{model_id}/endpoints", timeout=10.0
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        endpoints = data.get("endpoints", [])
        quantizations = sorted({e.get("quantization") for e in endpoints if e.get("quantization")})
        return {
            "quantization": "|".join(quantizations) if quantizations else None,
            "architecture": (data.get("architecture") or {}).get("modality"),
            "context_length": data.get("context_length"),
            "providers": sorted(
                {e.get("provider_name") for e in endpoints if e.get("provider_name")}
            ),
            "source": "openrouter_endpoints_api",
        }
    except Exception:
        return {}
