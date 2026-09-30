import io
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from redless.contracts import StructuredError, TaskRequest, TaskResult, WorkspaceSpec
from redless.fixture import FixtureExecutor
from redless.machine import MachineServer


def _request(run_id: str = "run-1") -> TaskRequest:
    return TaskRequest(run_id=run_id, task="test task", workspace=WorkspaceSpec(mode="create"))


def _result(request: TaskRequest, state: str = "succeeded") -> TaskResult:
    now = datetime.now(timezone.utc)
    return TaskResult(
        run_id=request.run_id,
        state=state,
        started_at=now,
        finished_at=now,
        final_answer="done" if state == "succeeded" else None,
        error=None if state != "failed" else StructuredError(code="fixture_failure", message="failed"),
    )


class ImmediateExecutor:
    def execute(self, request: TaskRequest, cancellation: threading.Event) -> TaskResult:
        return _result(request)


class BlockingExecutor:
    def execute(self, request: TaskRequest, cancellation: threading.Event) -> TaskResult:
        cancellation.wait(timeout=1)
        return _result(request, "cancelled" if cancellation.is_set() else "failed")


def _records(output: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_machine_transport_emits_only_json_status_and_result_records():
    request = _request()
    output = io.StringIO()
    server = MachineServer(ImmediateExecutor(), output=output, error=io.StringIO())

    assert server.run(io.StringIO(json.dumps({"type": "task", "payload": request.model_dump(mode="json")}) + "\n")) == 0

    records = _records(output)
    assert [record["type"] for record in records] == ["status", "status", "result"]
    assert records[0]["payload"]["state"] == "accepted"
    assert records[1]["payload"]["state"] == "running"
    assert records[2]["payload"]["state"] == "succeeded"


def test_machine_transport_distinguishes_cancellation_request_and_confirmation():
    request = _request()
    output = io.StringIO()
    input_data = "\n".join(
        [
            json.dumps({"type": "task", "payload": request.model_dump(mode="json")}),
            json.dumps({"type": "cancel", "payload": {"run_id": request.run_id, "reason": "stop"}}),
        ]
    ) + "\n"
    server = MachineServer(BlockingExecutor(), output=output, error=io.StringIO())

    server.run(io.StringIO(input_data))

    records = _records(output)
    assert records[-2]["type"] == "status"
    assert records[-2]["payload"]["state"] == "cancellation_requested"
    assert records[-1]["type"] == "result"
    assert records[-1]["payload"]["state"] == "cancelled"


def test_machine_transport_reports_invalid_input_as_structured_json():
    output = io.StringIO()
    server = MachineServer(output=output, error=io.StringIO())

    server.run(io.StringIO("not-json\n{" + '"type":"unknown"}' + "\n"))

    records = _records(output)
    assert records[0]["type"] == "error"
    assert records[0]["payload"]["code"] == "invalid_json"
    assert records[1]["payload"]["code"] == "unsupported_record_type"


def test_machine_transport_reports_honest_capabilities():
    output = io.StringIO()
    server = MachineServer(FixtureExecutor(), output=output, error=io.StringIO())

    server.run(io.StringIO(json.dumps({"type": "capabilities"}) + chr(10)))

    report = _records(output)[0]
    assert report["type"] == "capabilities"
    assert "task_execution" in report["payload"]["supported"]
    assert "resume_checkpoint" in report["payload"]["unavailable"]
    assert "workspace_containment" in report["payload"]["unavailable"]


def test_machine_cli_emits_only_jsonl_records(tmp_path):
    request = {
        "type": "task",
        "payload": {
            "run_id": "subprocess-1",
            "task": "fixture:success",
            "workspace": {"mode": "existing", "path": str(tmp_path)},
        },
    }
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    completed = subprocess.run(
        [sys.executable, "-m", "redless.machine", "--fixture"],
        input=json.dumps({"type": "capabilities"}) + "\n" + json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        env=environment,
        check=True,
    )

    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [record["type"] for record in records] == ["capabilities", "status", "status", "result"]
    assert records[-1]["payload"]["state"] == "succeeded"
    assert completed.stderr == ""
