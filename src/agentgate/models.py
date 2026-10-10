from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Principal(StrictModel):
    id: str
    name: str
    role: Identifier
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
    dataset: Identifier
    limit: int = Field(default=10, ge=1, le=50)


class ExportArgs(StrictModel):
    dataset: Identifier
    limit: int = Field(default=10, ge=1, le=50)


class ConnectorArgs(StrictModel):
    connector: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class CreateRecordArgs(StrictModel):
    dataset: Identifier
    record: dict[str, Any]


class DatasetDefinition(StrictModel):
    name: Identifier
    tenant: Identifier
    classification: Identifier
    record_schema: dict[str, Any] | None = None


class AgentRequest(StrictModel):
    prompt: str = Field(min_length=1, max_length=6000)
    max_steps: int = Field(default=6, ge=1, le=10)


class RegisterPrincipal(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    role: Identifier
    tenant: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class Policy(StrictModel):
    version: int = Field(ge=1)
    roles: dict[str, list[str]]
    classifications: dict[str, list[str]]
    approval_tools: list[str] = Field(default_factory=lambda: ["export_report"])

    @field_validator("roles", "classifications")
    @classmethod
    def valid_role_names(cls, value):
        from pydantic import TypeAdapter

        for role in value:
            TypeAdapter(Identifier).validate_python(role)
        return value


class PolicyUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    policy: Policy


class ApprovalDecision(StrictModel):
    decision: Literal["approved", "rejected"]
