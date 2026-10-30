"""Process-local LLM configuration shared by Agent planning and report narration.

The API key is accepted only on update, kept in process memory, and never included in a
response model. Restarting the backend discards the override and restores environment
settings. This deliberately avoids pretending that the application has encrypted secret
storage or administrator identity before either capability exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock

from algorithms.agent.llm import LlmMessage, LlmProvider, build_provider

from app.core.config import get_settings
from app.schemas.system import AgentLlmConfigData, AgentLlmConfigUpdate, AgentLlmConnectionData


@dataclass(frozen=True)
class EffectiveLlmConfig:
    provider: str
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = 60.0
    source: str = "environment"
    updated_at: datetime | None = None

    @property
    def enabled(self) -> bool:
        return self.provider not in {"", "none", "disabled", "off"} and bool(
            self.base_url and self.model
        )


_lock = RLock()
_runtime_override: EffectiveLlmConfig | None = None


def get_effective_llm_config() -> EffectiveLlmConfig:
    with _lock:
        if _runtime_override is not None:
            return _runtime_override

    settings = get_settings()
    return EffectiveLlmConfig(
        provider=settings.llm_provider.strip().lower() or "none",
        base_url=settings.llm_base_url.strip(),
        model=settings.llm_model.strip(),
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def get_agent_llm_config_data() -> AgentLlmConfigData:
    config = get_effective_llm_config()
    return AgentLlmConfigData(
        source="runtime" if config.source == "runtime" else "environment",
        enabled=config.enabled,
        provider=config.provider,
        base_url=config.base_url,
        model=config.model,
        has_api_key=bool(config.api_key),
        timeout_seconds=config.timeout_seconds,
        updated_at=config.updated_at,
    )


def update_agent_llm_config(payload: AgentLlmConfigUpdate) -> AgentLlmConfigData:
    global _runtime_override

    with _lock:
        previous = get_effective_llm_config()
        if payload.clear_api_key:
            api_key = ""
        elif payload.api_key is not None:
            api_key = payload.api_key
        else:
            api_key = previous.api_key

        _runtime_override = EffectiveLlmConfig(
            provider=payload.provider,
            base_url=payload.base_url,
            model=payload.model,
            api_key=api_key,
            timeout_seconds=payload.timeout_seconds,
            source="runtime",
            updated_at=datetime.now(UTC),
        )
    return get_agent_llm_config_data()


def reset_agent_llm_config() -> AgentLlmConfigData:
    global _runtime_override

    with _lock:
        _runtime_override = None
    return get_agent_llm_config_data()


def build_effective_llm_provider() -> LlmProvider:
    config = get_effective_llm_config()
    return build_provider(
        provider=config.provider,
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key,
        timeout_seconds=config.timeout_seconds,
    )


def test_agent_llm_connection() -> AgentLlmConnectionData:
    provider = build_effective_llm_provider()
    result = provider.complete(
        [
            LlmMessage(
                role="system",
                content="你是连接测试助手。请只回复 connection-ok，不要执行任何其他任务。",
            ),
            LlmMessage(role="user", content="connection-test"),
        ],
        temperature=0.0,
    )
    return AgentLlmConnectionData(
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
    )
