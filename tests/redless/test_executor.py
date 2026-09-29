import json
import subprocess
import threading
import time
from pathlib import Path

from redless.contracts import TaskRequest, WorkspaceSpec
from redless.executor import RedlessExecutor


class RecordingEnvironment:
    def __init__(self, **config):
        self.config = type("Config", (), config)()

    def execute(self, action, cwd="", *, timeout=None):
        path = Path(self.config.cwd) / "agent-output.txt"
        path.write_text(action["command"], encoding="utf-8")
        return {"output": "", "returncode": 0, "exception_info": ""}

    def execute_text(self, action):
        return self.execute(action)

    def get_template_vars(self, **kwargs):
        return kwargs

    def serialize(self):
        return {"info": {"config": {"environment": {"cwd": self.config.cwd}}}}


class RecordingAgent:
    instances = []

    def __init__(self, model, environment, config, *, default_type):
        self.model = model
        self.environment = environment
        self.config = config
        self.__class__.instances.append(self)

    def run(self, task):
        self.model.query([])
        self.environment.execute({"command": task})
        trajectory_path = self.config["output_path"]
        if trajectory_path is not None:
            trajectory_path.parent.mkdir(parents=True, exist_ok=True)
            trajectory_path.write_text(json.dumps({"task": task}), encoding="utf-8")
        return {"exit_status": "Submitted", "submission": "completed"}


class ImmediateModel:
    def query(self, messages, **kwargs):
        return {"role": "assistant", "content": "done", "extra": {}}


def _config_loader(_profile):
    return {
        "model": {"model_class": "fake", "model_kwargs": {"api_key": "secret", "api_base": "old"}},
        "environment": {"environment_class": "local", "timeout": 30},
        "agent": {},
    }


def _executor(captured):
    def model_factory(**kwargs):
        captured["model"] = kwargs["config"]
        return ImmediateModel()

    def environment_factory(config):
        captured["environment"] = config
        return RecordingEnvironment(**config)

    def agent_factory(model, environment, config, *, default_type):
        return RecordingAgent(model, environment, config, default_type=default_type)

    return RedlessExecutor(
        model_factory=model_factory,
        environment_factory=environment_factory,
        agent_factory=agent_factory,
        config_loader=_config_loader,
    )


def test_real_executor_runs_task_in_declared_workspace_and_writes_artifacts(tmp_path):
    captured = {}
    trajectory = tmp_path / "result" / "trajectory.json"
    result_path = tmp_path / "result" / "task-result.json"
    request = TaskRequest(
        run_id="real-1",
        task="echo task",
        workspace=WorkspaceSpec(mode="existing", path=str(tmp_path)),
        model={"model_name": "local-model", "endpoint_url": "http://127.0.0.1:8080/v1"},
        destinations={"trajectory_path": str(trajectory), "result_path": str(result_path)},
    )

    result = _executor(captured).execute(request, threading.Event())

    assert result.state == "succeeded"
    assert (tmp_path / "agent-output.txt").read_text(encoding="utf-8") == "echo task"
    assert trajectory.exists()
    assert result_path.exists()
    assert captured["environment"]["cwd"] == str(tmp_path)
    assert captured["model"]["model_kwargs"]["api_base"] == "http://127.0.0.1:8080/v1"
    assert "api_key" not in json.dumps(captured["model"])
    assert {artifact.kind for artifact in result.artifacts} == {"workspace"}
    assert result.trajectory is not None


def test_real_executor_capability_report_does_not_overclaim():
    report = RedlessExecutor.capability_report()

    assert "task_execution" in report.supported
    assert "status_events" in report.supported
    assert "resume_checkpoint" in report.unavailable
    assert "workspace_containment" in report.unavailable


def test_real_executor_supports_clone_and_cleanup(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("source", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Redless Test",
            "-c",
            "user.email=redless@example.test",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )
    clone_path = tmp_path / "clone"
    request = TaskRequest(
        run_id="real-clone",
        task="clone task",
        workspace=WorkspaceSpec(mode="clone", repository_url=str(source), path=str(clone_path), cleanup_policy="always"),
    )

    result = _executor({}).execute(request, threading.Event())

    assert result.state == "succeeded"
    assert not clone_path.exists()


def test_real_executor_confirms_cancellation_only_after_model_call_stops():
    started = threading.Event()
    release = threading.Event()

    class BlockingModel(ImmediateModel):
        def query(self, messages, **kwargs):
            started.set()
            release.wait(timeout=2)
            return super().query(messages, **kwargs)

    def model_factory(**kwargs):
        return BlockingModel()

    executor = RedlessExecutor(
        model_factory=model_factory,
        environment_factory=lambda config: RecordingEnvironment(**config),
        agent_factory=lambda model, environment, config, *, default_type: RecordingAgent(
            model, environment, config, default_type=default_type
        ),
        config_loader=_config_loader,
    )
    request = TaskRequest(run_id="real-cancel", task="cancel task", workspace=WorkspaceSpec(mode="create"))
    cancellation = threading.Event()
    result_holder = []
    worker = threading.Thread(target=lambda: result_holder.append(executor.execute(request, cancellation)))
    worker.start()
    assert started.wait(timeout=1)
    cancellation.set()
    time.sleep(0.05)
    assert worker.is_alive()
    release.set()
    worker.join(timeout=2)

    assert result_holder[0].state == "cancelled"
