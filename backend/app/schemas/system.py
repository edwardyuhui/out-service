from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from app.schemas.common import Schema


class LivenessData(Schema):
    status: Literal["ok"] = "ok"
    service: str = "indusopt-backend"


class ReadinessData(Schema):
    status: Literal["ready"] = "ready"
    database: Literal["connected"] = "connected"
    queue: Literal["connected"] = "connected"


class SystemInfoData(Schema):
    service: str = "indusopt-backend"
    version: str
    environment: str
    api_version: str = "v1"
    database_driver: str = "SQLAlchemy Async"
    queue_backend: str = "Redis + RQ"
    algorithm_contract_version: str = Field(default="ALG-0.1")


class AgentLlmConfigUpdate(Schema):
    """A process-local LLM override; secrets are accepted but never returned."""

    provider: str = Field(default="none", min_length=1, max_length=80, pattern=r"^[\w.-]+$")
    base_url: str = Field(default="", max_length=2_048)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, min_length=1, max_length=8_192, repr=False)
    clear_api_key: bool = False
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    @model_validator(mode="after")
    def validate_provider_configuration(self) -> "AgentLlmConfigUpdate":
        provider = self.provider.strip().lower()
        self.provider = provider
        self.base_url = self.base_url.strip()
        self.model = self.model.strip()

        if self.api_key is not None and self.clear_api_key:
            raise ValueError("不能同时提交新 API Key 和清除 API Key。")
        if provider in {"none", "disabled", "off"}:
            self.provider = "none"
            self.base_url = ""
            self.model = ""
            self.clear_api_key = True
            return self
        if not self.base_url or not self.model:
            raise ValueError("启用大模型时必须填写接口地址和模型名称。")

        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("接口地址必须是有效的 HTTP 或 HTTPS 地址。")
        if parsed.username or parsed.password:
            raise ValueError("接口地址不能包含用户名或密码。")
        if parsed.query or parsed.fragment:
            raise ValueError("接口地址不能包含查询参数或片段。")
        return self


class AgentLlmConfigData(Schema):
    source: Literal["environment", "runtime"]
    persistence: Literal["process_memory"] = "process_memory"
    enabled: bool
    provider: str
    base_url: str
    model: str
    has_api_key: bool
    timeout_seconds: float
    updated_at: datetime | None = None


class AgentLlmConnectionData(Schema):
    connected: Literal[True] = True
    provider: str
    model: str
    latency_ms: float
    message: str = "模型服务连接成功。"
