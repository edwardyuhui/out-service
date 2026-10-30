"""Runtime Agent configuration API tests; no request reaches an external model service."""

from collections.abc import Iterator

import pytest
from algorithms.agent.llm import OpenAiCompatibleProvider, StaticProvider
from app.core.config import Settings
from app.main import create_app
from app.services import agent_service, report_service
from app.services.llm_runtime_config_service import reset_agent_llm_config
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    environment_settings = Settings(
        llm_provider="none",
        llm_base_url="",
        llm_model="",
        llm_api_key="",
    )
    monkeypatch.setattr(
        "app.services.llm_runtime_config_service.get_settings",
        lambda: environment_settings,
    )
    reset_agent_llm_config()
    with TestClient(create_app()) as test_client:
        yield test_client
    reset_agent_llm_config()


def _runtime_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider": "deepseek",
        "base_url": "https://example.invalid/v1",
        "model": "planner-model",
        "api_key": "secret-for-test-only",
        "timeout_seconds": 12,
    }
    payload.update(overrides)
    return payload


def test_runtime_configuration_is_effective_without_returning_the_secret(
    client: TestClient,
) -> None:
    secret = "secret-for-test-only"
    response = client.put("/api/v1/system/agent-config", json=_runtime_payload())

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["source"] == "runtime"
    assert data["persistence"] == "process_memory"
    assert data["enabled"] is True
    assert data["has_api_key"] is True
    assert secret not in response.text

    agent_provider = agent_service._resolve_provider()
    report_provider = report_service._resolve_provider()
    assert isinstance(agent_provider, OpenAiCompatibleProvider)
    assert isinstance(report_provider, OpenAiCompatibleProvider)
    assert agent_provider.model == "planner-model"
    assert report_provider.model == "planner-model"


def test_omitted_key_keeps_it_and_clear_flag_removes_it(client: TestClient) -> None:
    client.put("/api/v1/system/agent-config", json=_runtime_payload())

    retained = client.put(
        "/api/v1/system/agent-config",
        json=_runtime_payload(api_key=None, model="new-model"),
    )
    assert retained.status_code == 200, retained.text
    assert retained.json()["data"]["has_api_key"] is True
    assert retained.json()["data"]["model"] == "new-model"

    cleared = client.put(
        "/api/v1/system/agent-config",
        json=_runtime_payload(api_key=None, clear_api_key=True),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["has_api_key"] is False


def test_reset_restores_environment_configuration(client: TestClient) -> None:
    client.put("/api/v1/system/agent-config", json=_runtime_payload())

    response = client.delete("/api/v1/system/agent-config")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "source": "environment",
        "persistence": "process_memory",
        "enabled": False,
        "provider": "none",
        "base_url": "",
        "model": "",
        "has_api_key": False,
        "timeout_seconds": 60.0,
        "updated_at": None,
    }


def test_connection_test_uses_the_effective_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put("/api/v1/system/agent-config", json=_runtime_payload())
    monkeypatch.setattr(
        "app.services.llm_runtime_config_service.build_effective_llm_provider",
        lambda: StaticProvider(responses=["connection-ok"], name="test-provider", model="m1"),
    )

    response = client.post("/api/v1/system/agent-config/test")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "connected": True,
        "provider": "test-provider",
        "model": "m1",
        "latency_ms": 0.0,
        "message": "模型服务连接成功。",
    }


@pytest.mark.parametrize(
    "payload",
    [
        _runtime_payload(base_url="file:///tmp/model"),
        _runtime_payload(base_url="https://user:password@example.com/v1"),
        _runtime_payload(base_url="https://example.com/v1?api_key=secret-in-url"),
        _runtime_payload(api_key="new", clear_api_key=True),
        _runtime_payload(model=""),
    ],
)
def test_invalid_or_credential_bearing_configuration_is_rejected(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.put("/api/v1/system/agent-config", json=payload)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    if payload.get("api_key"):
        assert str(payload["api_key"]) not in response.text


def test_field_level_key_validation_does_not_echo_the_key(client: TestClient) -> None:
    oversized_secret = "s" * 8_193

    response = client.put(
        "/api/v1/system/agent-config",
        json=_runtime_payload(api_key=oversized_secret),
    )

    assert response.status_code == 422, response.text
    assert oversized_secret not in response.text
    assert "[REDACTED]" in response.text
