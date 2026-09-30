"""Real Redless execution adapter for the public task contract."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from minisweagent.agents import get_agent
from minisweagent.config import get_config_from_spec
from minisweagent.environments import get_environment
from minisweagent.models import get_model
from redless.contracts import Artifact, CapabilityReport, StructuredError, TaskRequest, TaskResult

SUPPORTED_CAPABILITIES = {
    "task_execution",
    "structured_results",
    "artifact_references",
    "cancellation_request_support",
    "cancellation_confirmation_support",
    "native_tools",
    "status_events",
}

UNAVAILABLE_CAPABILITIES = {
    "workspace_containment",
    "resume_checkpoint",
    "sidecaravan_tools",
    "identity_context_semantics",
    "token_streaming",
}

_SECRET_KEYS = {"api_key", "authorization", "password", "secret", "token"}


class _CancellationRequested(Exception):
    """Raised inside the agent adapter when cooperative cancellation is observed."""


class _CancellationAwareModel:
    def __init__(self, model: Any, cancellation: threading.Event):
        self._model = model
        self._cancellation = cancellation

    def query(self, messages: list[dict[str, str]], **kwargs) -> dict:
        _raise_if_cancelled(self._cancellation)
        result = self._model.query(messages, **kwargs)
        _raise_if_cancelled(self._cancellation)
        return result

    def serialize(self) -> dict[str, Any]:
        return _redact_secrets(self._model.serialize())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


class _CancellationAwareEnvironment:
    def __init__(self, environment: Any, cancellation: threading.Event):
        self._environment = environment
        self._cancellation = cancellation

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        _raise_if_cancelled(self._cancellation)
        result = self._environment.execute(action, cwd=cwd, timeout=timeout)
        _raise_if_cancelled(self._cancellation)
        return result

    def execute_text(self, action: dict) -> dict[str, Any]:
        _raise_if_cancelled(self._cancellation)
        result = self._environment.execute_text(action)
        _raise_if_cancelled(self._cancellation)
        return result

    def serialize(self) -> dict[str, Any]:
        return _redact_secrets(self._environment.serialize())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._environment, name)


@dataclass
class _Workspace:
    path: Path
    owned: bool
    cleanup_policy: str

    def cleanup(self, *, succeeded: bool) -> None:
        if not self.owned:
            return
        if self.cleanup_policy == "always" or (self.cleanup_policy == "on_success" and succeeded):
            shutil.rmtree(self.path)


ModelFactory = Callable[..., Any]
EnvironmentFactory = Callable[..., Any]
AgentFactory = Callable[..., Any]
ConfigLoader = Callable[[str | Path], dict]


class RedlessExecutor:
    """Adapt a public task request to the existing Redless execution stack."""

    supported_capabilities = SUPPORTED_CAPABILITIES

    @staticmethod
    def capability_report() -> CapabilityReport:
        return CapabilityReport(
            supported=sorted(SUPPORTED_CAPABILITIES),
            unavailable=sorted(UNAVAILABLE_CAPABILITIES),
        )

    def __init__(
        self,
        *,
        model_factory: ModelFactory = get_model,
        environment_factory: EnvironmentFactory = get_environment,
        agent_factory: AgentFactory = get_agent,
        config_loader: ConfigLoader = get_config_from_spec,
    ):
        self._model_factory = model_factory
        self._environment_factory = environment_factory
        self._agent_factory = agent_factory
        self._config_loader = config_loader

    def execute(self, request: TaskRequest, cancellation: threading.Event) -> TaskResult:
        started = _now()
        workspace: _Workspace | None = None
        result: TaskResult
        try:
            unsupported = sorted(set(request.required_capabilities) - self.supported_capabilities)
            if unsupported:
                return _failure(
                    request,
                    started,
                    "unsupported_capability",
                    "Redless does not support one or more requested capabilities.",
                    {"capabilities": unsupported},
                )
            policy_error = _policy_error(request)
            if policy_error is not None:
                return _failure(request, started, "unsupported_execution_policy", policy_error)
            _raise_if_cancelled(cancellation)
            workspace = _prepare_workspace(request)
            config = self._load_config(request, workspace.path)
            model = self._model_factory(config=config["model"])
            environment = self._environment_factory(config["environment"])
            agent = self._agent_factory(
                _CancellationAwareModel(model, cancellation),
                _CancellationAwareEnvironment(environment, cancellation),
                config["agent"],
                default_type="default",
            )
            agent_result = agent.run(request.task)
            if cancellation.is_set():
                result = _cancelled(request, started)
            elif agent_result.get("exit_status") == "Submitted":
                result = TaskResult(
                    run_id=request.run_id,
                    state="succeeded",
                    started_at=started,
                    finished_at=_now(),
                    final_answer=agent_result.get("submission") or None,
                    artifacts=_artifacts(workspace),
                    trajectory=_trajectory_artifact(config["agent"].get("output_path")),
                )
            else:
                result = _failure(
                    request,
                    started,
                    "agent_exit",
                    "The Redless agent stopped without submitting a final result.",
                    {"exit_status": agent_result.get("exit_status", "")},
                )
        except _CancellationRequested:
            result = _cancelled(request, started)
        except Exception as exc:
            result = _failure(
                request,
                started,
                "execution_error",
                "Redless execution failed.",
                {"exception_type": type(exc).__name__},
            )

        if workspace is not None:
            try:
                workspace.cleanup(succeeded=result.state == "succeeded")
            except Exception as exc:
                result = _failure(
                    request,
                    started,
                    "workspace_cleanup_error",
                    "Redless could not apply the requested workspace cleanup policy.",
                    {"exception_type": type(exc).__name__},
                )
        return _write_result_destination(request, result)

    def _load_config(self, request: TaskRequest, workspace_path: Path) -> dict[str, dict]:
        reference = request.model
        profile = reference.profile if reference and reference.profile else "slow_local.yaml"
        config = self._config_loader(profile)
        if not isinstance(config, dict):
            raise ValueError("model profile did not contain a mapping")
        model_config = dict(config.get("model", {}))
        environment_config = dict(config.get("environment", {}))
        agent_config = dict(config.get("agent", {}))
        if reference is not None:
            if reference.model_name:
                model_config["model_name"] = reference.model_name
            if reference.endpoint_url:
                model_kwargs = dict(model_config.get("model_kwargs", {}))
                model_kwargs["api_base"] = reference.endpoint_url
                model_config["model_kwargs"] = model_kwargs
        policy = request.execution_policy
        if policy is not None and policy.environment_class:
            environment_config["environment_class"] = policy.environment_class
        if policy is not None and policy.timeout_seconds is not None:
            environment_config["timeout"] = policy.timeout_seconds
        if policy is not None and policy.wall_time_limit_seconds is not None:
            agent_config["wall_time_limit_seconds"] = policy.wall_time_limit_seconds
        agent_config["output_path"] = _trajectory_path(request)
        environment_config["cwd"] = str(workspace_path)
        return {"model": model_config, "environment": environment_config, "agent": agent_config}


def _prepare_workspace(request: TaskRequest) -> _Workspace:
    spec = request.workspace
    if spec.mode == "existing":
        path = Path(spec.path or "").resolve()
        if not path.is_dir():
            raise ValueError(f"existing workspace does not exist: {path}")
        if spec.cleanup_policy != "preserve":
            raise ValueError("existing workspaces only support preserve cleanup")
        return _Workspace(path, False, spec.cleanup_policy)

    temporary_path = spec.path is None
    if spec.path:
        path = Path(spec.path).resolve()
        if path.exists():
            raise ValueError(f"workspace path already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = Path(tempfile.mkdtemp(prefix="redless-run-"))
    if spec.mode == "clone":
        subprocess.run(
            ["git", "clone", spec.repository_url or "", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        if spec.ref:
            try:
                subprocess.run(
                    ["git", "-C", str(path), "checkout", "--detach", spec.ref],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError:
                subprocess.run(
                    ["git", "-C", str(path), "checkout", "--detach", f"origin/{spec.ref}"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
    elif not temporary_path:
        path.mkdir(parents=True, exist_ok=False)
    return _Workspace(path, True, spec.cleanup_policy)


def _trajectory_path(request: TaskRequest) -> Path | None:
    if request.destinations is None or request.destinations.trajectory_path is None:
        return None
    return Path(request.destinations.trajectory_path)


def _artifacts(workspace: _Workspace) -> list[Artifact]:
    artifacts = []
    if workspace.cleanup_policy == "preserve":
        artifacts.append(Artifact(kind="workspace", path=str(workspace.path), media_type="application/x-directory"))
    return artifacts


def _trajectory_artifact(path: Path | None) -> Artifact | None:
    if path is None or not path.exists():
        return None
    return Artifact(kind="trajectory", path=str(path), media_type="application/json")


def _write_result_destination(request: TaskRequest, result: TaskResult) -> TaskResult:
    if request.destinations is None or request.destinations.result_path is None:
        return result
    path = Path(request.destinations.result_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        return _failure(request, result.started_at, "result_write_error", "Redless could not write the result artifact.", {"exception_type": type(exc).__name__})
    return result


def _policy_error(request: TaskRequest) -> str | None:
    policy = request.execution_policy
    if policy is None:
        return None
    if policy.allowed_tools:
        return "allowed_tools is not yet enforceable by the existing agent tool adapters"
    if policy.network_access != "inherit":
        return "network_access policies other than inherit are not yet enforceable by every environment"
    return None


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in _SECRET_KEYS else _redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _raise_if_cancelled(cancellation: threading.Event) -> None:
    if cancellation.is_set():
        raise _CancellationRequested


def _cancelled(request: TaskRequest, started: datetime) -> TaskResult:
    return TaskResult(
        run_id=request.run_id,
        state="cancelled",
        started_at=started,
        finished_at=_now(),
        cancellation_requested=True,
    )


def _failure(
    request: TaskRequest,
    started: datetime,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> TaskResult:
    return TaskResult(
        run_id=request.run_id,
        state="failed",
        started_at=started,
        finished_at=_now(),
        error=StructuredError(code=code, message=message, details=details),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
