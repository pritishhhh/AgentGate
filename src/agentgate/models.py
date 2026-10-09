from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Principal(StrictModel):
    id: str
    name: str
    role: Literal["support", "finance", "admin"]
    tenant: str
    active: bool = True


class ToolCall(StrictModel):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = Field(default=None, max_length=80)


class SearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class ReadArgs(StrictModel):
    document_id: str = Field(min_length=1, max_length=80)


class QueryArgs(StrictModel):
    dataset: Literal["tickets", "payroll"]
    limit: int = Field(default=10, ge=1, le=50)


class ExportArgs(StrictModel):
    dataset: Literal["tickets", "payroll"]
    limit: int = Field(default=10, ge=1, le=50)


class ConnectorArgs(StrictModel):
    connector: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(StrictModel):
    prompt: str = Field(min_length=1, max_length=6000)
    max_steps: int = Field(default=6, ge=1, le=10)


class RegisterPrincipal(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    role: Literal["support", "finance", "admin"]
    tenant: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class Policy(StrictModel):
    version: int = Field(ge=1)
    roles: dict[str, list[str]]
    classifications: dict[str, list[str]]
    approval_tools: list[str] = Field(default_factory=lambda: ["export_report"])


class PolicyUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    policy: Policy


class ApprovalDecision(StrictModel):
    decision: Literal["approved", "rejected"]
