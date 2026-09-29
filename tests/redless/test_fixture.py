import io
import json
import threading
from pathlib import Path

from redless.contracts import TaskRequest, WorkspaceSpec
from redless.fixture import FixtureExecutor
from redless.machine import MachineServer


def _request(tmp_path, *, task="fixture:success", run_id="fixture-1", required_capabilities=None):
    return TaskRequest(
        run_id=run_id,
        correlation_id="consumer-1",
        task=task,
        workspace=WorkspaceSpec(mode="existing", path=str(tmp_path)),
        required_capabilities=required_capabilities or [],
    )


def _records(output):
    return [json.loads(line) for line in output.getvalue().splitlines()]


def _run(server, records):
    output = io.StringIO()
    server.output = output
    server.run(io.StringIO("\n".join(json.dumps(record) for record in records) + "\n"))
    return _records(output)


def test_fixture_creates_discoverable_artifact(tmp_path):
    request = _request(tmp_path)
    records = _run(
        MachineServer(FixtureExecutor(), output=io.StringIO(), error=io.StringIO()),
        [{"type": "task", "payload": request.model_dump(mode="json")}],
    )

    result = records[-1]["payload"]
    assert result["state"] == "succeeded"
    assert result["run_id"] == request.run_id
    assert result["artifacts"]
    artifact_path = result["artifacts"][0]["path"]
    assert Path(artifact_path).read_text(encoding="utf-8") == "run_id=fixture-1\ntask=fixture:success\n"


def test_fixture_returns_structured_failure(tmp_path):
    request = _request(tmp_path, task="fixture:failure")
    records = _run(
        MachineServer(FixtureExecutor(), output=io.StringIO(), error=io.StringIO()),
        [{"type": "task", "payload": request.model_dump(mode="json")}],
    )

    result = records[-1]["payload"]
    assert result["state"] == "failed"
    assert result["error"]["code"] == "fixture_failure"


def test_fixture_rejects_unsupported_capabilities(tmp_path):
    request = _request(tmp_path, required_capabilities=["resume_checkpoint"])
    records = _run(
        MachineServer(FixtureExecutor(), output=io.StringIO(), error=io.StringIO()),
        [{"type": "task", "payload": request.model_dump(mode="json")}],
    )

    assert records[-1]["payload"]["error"]["code"] == "unsupported_capability"
    assert records[-1]["payload"]["error"]["details"]["capabilities"] == ["resume_checkpoint"]


def test_fixture_confirms_cancellation_after_request(tmp_path):
    request = _request(tmp_path, task="fixture:block", run_id="blocking-fixture")
    records = _run(
        MachineServer(FixtureExecutor(), output=io.StringIO(), error=io.StringIO()),
        [
            {"type": "task", "payload": request.model_dump(mode="json")},
            {"type": "cancel", "payload": {"contract_version": "1", "run_id": request.run_id}},
        ],
    )

    assert records[-2]["payload"]["state"] == "cancellation_requested"
    assert records[-1]["payload"]["state"] == "cancelled"


def test_fixture_executor_is_not_retried_after_caller_input_ends(tmp_path):
    class CountingExecutor(FixtureExecutor):
        calls = 0

        def execute(self, request, cancellation: threading.Event):
            self.calls += 1
            return super().execute(request, cancellation)

    executor = CountingExecutor()
    request = _request(tmp_path)
    _run(
        MachineServer(executor, output=io.StringIO(), error=io.StringIO()),
        [{"type": "task", "payload": request.model_dump(mode="json")}],
    )

    assert executor.calls == 1
