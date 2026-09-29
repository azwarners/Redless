"""Deterministic execution backend for Redless consumer-contract tests."""

from __future__ import annotations

import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from redless.contracts import Artifact, CapabilityReport, StructuredError, TaskRequest, TaskResult


class FixtureExecutor:
    """Execute deterministic tasks without a model or external service."""

    supported_capabilities = {
        "task_execution",
        "structured_results",
        "artifact_references",
        "cancellation_request_support",
        "cancellation_confirmation_support",
        "status_events",
    }

    @classmethod
    def capability_report(cls) -> CapabilityReport:
        return CapabilityReport(
            supported=sorted(cls.supported_capabilities),
            unavailable=["resume_checkpoint", "workspace_containment"],
        )

    def execute(self, request: TaskRequest, cancellation: threading.Event) -> TaskResult:
        started = _now()
        unsupported = sorted(set(request.required_capabilities) - self.supported_capabilities)
        if unsupported:
            return _failure(
                request,
                started,
                "unsupported_capability",
                "The deterministic fixture does not support one or more requested capabilities.",
                {"capabilities": unsupported},
            )

        workspace, error = _workspace_for(request)
        if error is not None:
            return _failure(request, started, "workspace_error", error)

        if request.task == "fixture:failure":
            return _failure(request, started, "fixture_failure", "The deterministic fixture was asked to fail.")
        if request.task == "fixture:block":
            cancellation.wait()
            if cancellation.is_set():
                return TaskResult(
                    run_id=request.run_id,
                    state="cancelled",
                    started_at=started,
                    finished_at=_now(),
                    cancellation_requested=True,
                )
        if cancellation.is_set():
            return TaskResult(
                run_id=request.run_id,
                state="cancelled",
                started_at=started,
                finished_at=_now(),
                cancellation_requested=True,
            )

        output_path = workspace / "redless-fixture-output.txt"
        output_path.write_text(f"run_id={request.run_id}\ntask={request.task}\n", encoding="utf-8")
        return TaskResult(
            run_id=request.run_id,
            state="succeeded",
            started_at=started,
            finished_at=_now(),
            final_answer="deterministic fixture completed",
            artifacts=[
                Artifact(
                    kind="fixture_output",
                    path=str(output_path),
                    media_type="text/plain",
                    description="Deterministic fixture output",
                )
            ],
        )


def _workspace_for(request: TaskRequest) -> tuple[Path, str | None]:
    spec = request.workspace
    if spec.mode == "clone":
        return Path(), "the deterministic fixture does not clone repositories"
    if spec.mode == "existing":
        workspace = Path(spec.path or "")
        if not workspace.is_dir():
            return Path(), f"existing workspace does not exist: {workspace}"
        return workspace, None
    if spec.path:
        workspace = Path(spec.path)
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace, None
    return Path(tempfile.mkdtemp(prefix="redless-fixture-")), None


def _failure(
    request: TaskRequest,
    started: datetime,
    code: str,
    message: str,
    details: dict | None = None,
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
