"""JSONL machine transport for the Redless public contracts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from io import TextIOBase
from typing import Any, Protocol

from redless.contracts import (
    CancellationRequest,
    CapabilityReport,
    StructuredError,
    TaskRequest,
    TaskResult,
    TaskStatus,
)

# The machine boundary reserves stdout for JSONL records. The legacy package
# startup banner is appropriate for the human CLI but corrupts this transport.
os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")

from redless.executor import RedlessExecutor
from redless.fixture import FixtureExecutor


class TaskExecutor(Protocol):
    """Backend interface used by the machine transport."""

    def execute(self, request: TaskRequest, cancellation: threading.Event) -> TaskResult: ...


class UnavailableExecutor:
    """Explicit Stage 3 placeholder until the real adapter is added."""

    def execute(self, request: TaskRequest, cancellation: threading.Event) -> TaskResult:
        now = _now()
        return TaskResult(
            run_id=request.run_id,
            state="failed",
            started_at=now,
            finished_at=_now(),
            error=StructuredError(
                code="execution_backend_unavailable",
                message="The Redless machine transport has no execution backend configured yet.",
            ),
        )

    @staticmethod
    def capability_report() -> CapabilityReport:
        return CapabilityReport(
            supported=["status_events"],
            unavailable=["task_execution", "structured_results", "artifact_references", "resume_checkpoint"],
        )


class MachineServer:
    """Read JSONL requests and emit JSONL status, result, and error records."""

    def __init__(
        self,
        executor: TaskExecutor | None = None,
        *,
        output: TextIOBase,
        error: TextIOBase,
    ):
        self.executor = executor or RedlessExecutor()
        self.output = output
        self.error = error
        self._output_lock = threading.Lock()
        self._active: _ActiveRun | None = None

    def run(self, input_stream: TextIOBase) -> int:
        """Process input until EOF, waiting for an active task before returning."""
        for line_number, line in enumerate(input_stream, start=1):
            if not line.strip():
                continue
            self._handle_line(line, line_number)
        active = self._active
        if active is not None:
            active.thread.join()
        return 0

    def _handle_line(self, line: str, line_number: int) -> None:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            self._emit_error(
                StructuredError(
                    code="invalid_json",
                    message="Input line is not valid JSON.",
                    details={"line": line_number, "column": exc.colno},
                )
            )
            return
        if not isinstance(record, dict):
            self._emit_error(StructuredError(code="invalid_record", message="Each JSONL record must be an object."))
            return

        record_type = record.get("type")
        if record_type == "task":
            self._handle_task(record.get("payload"), line_number)
        elif record_type == "cancel":
            self._handle_cancel(record.get("payload"), line_number)
        elif record_type == "capabilities":
            self._emit_capabilities()
        else:
            self._emit_error(
                StructuredError(
                    code="unsupported_record_type",
                    message="Record type must be 'capabilities', 'task', or 'cancel'.",
                    details={"line": line_number, "type": record_type},
                )
            )

    def _emit_capabilities(self) -> None:
        report_factory = getattr(self.executor, "capability_report", None)
        report = report_factory() if callable(report_factory) else CapabilityReport(supported=["status_events"])
        self._emit("capabilities", report.model_dump(mode="json"))

    def _handle_task(self, payload: Any, line_number: int) -> None:
        try:
            request = TaskRequest.model_validate(payload)
        except Exception as exc:
            self._emit_error(
                StructuredError(
                    code="invalid_task_request",
                    message="Task payload failed contract validation.",
                    details={"line": line_number, "errors": _validation_errors(exc)},
                )
            )
            return
        if self._active is not None:
            self._emit_error(
                StructuredError(
                    code="run_in_progress",
                    message="This machine process already has an active run.",
                    details={"run_id": self._active.request.run_id},
                )
            )
            return

        cancellation = threading.Event()
        active = _ActiveRun(request=request, cancellation=cancellation)
        self._active = active
        now = _now()
        self._emit_status(TaskStatus(run_id=request.run_id, state="accepted", updated_at=now))
        self._emit_status(TaskStatus(run_id=request.run_id, state="running", started_at=now, updated_at=_now()))
        active.thread = threading.Thread(target=self._execute, args=(active,), name=f"redless-{request.run_id}")
        active.thread.start()

    def _handle_cancel(self, payload: Any, line_number: int) -> None:
        try:
            request = CancellationRequest.model_validate(payload)
        except Exception as exc:
            self._emit_error(
                StructuredError(
                    code="invalid_cancellation_request",
                    message="Cancellation payload failed contract validation.",
                    details={"line": line_number, "errors": _validation_errors(exc)},
                )
            )
            return
        active = self._active
        if active is None or active.request.run_id != request.run_id:
            self._emit_error(
                StructuredError(
                    code="run_not_found",
                    message="No active run matches the cancellation request.",
                    details={"run_id": request.run_id},
                )
            )
            return
        if not active.cancellation.is_set():
            active.cancellation.set()
            self._emit_status(
                TaskStatus(
                    run_id=request.run_id,
                    state="cancellation_requested",
                    updated_at=_now(),
                    message=request.reason,
                    cancellation_requested=True,
                )
            )

    def _execute(self, active: _ActiveRun) -> None:
        try:
            result = self.executor.execute(active.request, active.cancellation)
            self._emit_result(result)
        except Exception as exc:
            self._emit_result(
                TaskResult(
                    run_id=active.request.run_id,
                    state="failed",
                    started_at=_now(),
                    finished_at=_now(),
                    error=StructuredError(code="executor_error", message=str(exc)),
                )
            )
        finally:
            if self._active is active:
                self._active = None

    def _emit_status(self, status: TaskStatus) -> None:
        self._emit("status", status.model_dump(mode="json"))

    def _emit_result(self, result: TaskResult) -> None:
        self._emit("result", result.model_dump(mode="json"))

    def _emit_error(self, error: StructuredError) -> None:
        self._emit("error", error.model_dump(mode="json"))

    def _emit(self, record_type: str, payload: dict[str, Any]) -> None:
        with self._output_lock:
            self.output.write(json.dumps({"type": record_type, "payload": payload}, separators=(",", ":")) + "\n")
            self.output.flush()


class _ActiveRun:
    def __init__(self, *, request: TaskRequest, cancellation: threading.Event):
        self.request = request
        self.cancellation = cancellation
        self.thread = threading.Thread()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validation_errors(error: Exception) -> Any:
    errors = getattr(error, "errors", None)
    return errors() if callable(errors) else [{"type": type(error).__name__, "msg": str(error)}]


def main(argv: list[str] | None = None) -> int:
    """Run the JSONL transport without writing human logs to stdout."""
    parser = argparse.ArgumentParser(description="Run Redless using the machine JSONL contract.")
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="Use the deterministic contract fixture instead of the real execution backend.",
    )
    arguments = parser.parse_args(argv)
    executor = FixtureExecutor() if arguments.fixture else None
    server = MachineServer(executor, output=sys.stdout, error=sys.stderr)
    return server.run(sys.stdin)


if __name__ == "__main__":
    raise SystemExit(main())
