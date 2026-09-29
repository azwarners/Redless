"""Versioned, transport-neutral contracts for machine-callable Redless runs."""

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "1"

WorkspaceMode = Literal["existing", "clone", "create", "ephemeral"]
CleanupPolicy = Literal["preserve", "on_success", "always"]
LifecycleState = Literal[
    "accepted",
    "running",
    "cancellation_requested",
    "succeeded",
    "failed",
    "cancelled",
]


class ContractModel(BaseModel):
    """Common validation for the public contract models."""

    model_config = ConfigDict(extra="forbid")
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION


class WorkspaceSpec(ContractModel):
    """Declarative workspace request owned by Redless."""

    mode: WorkspaceMode
    path: str | None = None
    repository_url: str | None = None
    ref: str | None = None
    cleanup_policy: CleanupPolicy = "preserve"

    @model_validator(mode="after")
    def validate_shape(self) -> "WorkspaceSpec":
        if self.mode == "existing" and not self.path:
            raise ValueError("existing workspaces require path")
        if self.mode == "clone" and not self.repository_url:
            raise ValueError("clone workspaces require repository_url")
        if self.mode in {"create", "ephemeral"} and self.repository_url:
            raise ValueError(f"{self.mode} workspaces cannot set repository_url")
        return self


class ModelReference(ContractModel):
    """Non-secret model configuration reference."""

    profile: str | None = None
    model_name: str | None = None
    endpoint_url: str | None = None

    @model_validator(mode="after")
    def require_reference(self) -> "ModelReference":
        if not any((self.profile, self.model_name, self.endpoint_url)):
            raise ValueError("model reference requires profile, model_name, or endpoint_url")
        return self

    @field_validator("endpoint_url")
    @classmethod
    def reject_url_credentials(cls, value: str | None) -> str | None:
        if value is not None and urlsplit(value).username is not None:
            raise ValueError("endpoint_url must not contain credentials")
        return value


class ExecutionPolicy(ContractModel):
    """Requested execution limits; enforcement is owned by the selected environment."""

    environment_class: str | None = None
    allowed_tools: list[str] | None = None
    network_access: Literal["inherit", "none", "restricted"] = "inherit"
    timeout_seconds: int | None = Field(default=None, ge=1)
    wall_time_limit_seconds: int | None = Field(default=None, ge=1)


class ResultDestinations(ContractModel):
    """Optional filesystem destinations selected by the caller."""

    result_path: str | None = None
    trajectory_path: str | None = None


class TaskRequest(ContractModel):
    """A versioned request to execute one bounded Redless task."""

    run_id: str = Field(min_length=1)
    correlation_id: str | None = None
    task: str = Field(min_length=1)
    workspace: WorkspaceSpec
    model: ModelReference | None = None
    identity_context: dict[str, Any] | None = None
    execution_policy: ExecutionPolicy | None = None
    destinations: ResultDestinations | None = None
    required_capabilities: list[str] = Field(default_factory=list)


class TaskStatus(ContractModel):
    """A non-terminal or terminal lifecycle observation."""

    run_id: str = Field(min_length=1)
    state: LifecycleState
    started_at: datetime | None = None
    updated_at: datetime
    message: str | None = None
    cancellation_requested: bool = False


class Artifact(ContractModel):
    """A filesystem reference produced by a task."""

    kind: str = Field(min_length=1)
    path: str = Field(min_length=1)
    media_type: str | None = None
    description: str | None = None


class StructuredError(ContractModel):
    """Stable machine-readable failure information."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] | None = None


class TaskResult(ContractModel):
    """The terminal result of a Redless task."""

    run_id: str = Field(min_length=1)
    state: Literal["succeeded", "failed", "cancelled"]
    started_at: datetime
    finished_at: datetime
    final_answer: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    trajectory: Artifact | None = None
    error: StructuredError | None = None
    cancellation_requested: bool = False


class CancellationRequest(ContractModel):
    """A request to stop a run; it does not prove that execution has stopped."""

    run_id: str = Field(min_length=1)
    reason: str | None = None


class CapabilityReport(ContractModel):
    """Capabilities actually supported by the current Redless process."""

    supported: list[str] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)
