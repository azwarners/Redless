from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from redless import (
    Artifact,
    CancellationRequest,
    ModelReference,
    TaskRequest,
    TaskResult,
    TaskStatus,
    WorkspaceSpec,
)


def test_task_request_serializes_versioned_public_shape_without_secrets():
    request = TaskRequest(
        run_id="run-1",
        correlation_id="caller-1",
        task="inspect the repository",
        workspace=WorkspaceSpec(mode="existing", path="/work/project"),
        model=ModelReference(profile="local-mistral", model_name="Mistral-Med-3.5-128B-dense"),
    )

    payload = request.model_dump(mode="json")

    assert payload["contract_version"] == "1"
    assert payload["workspace"]["mode"] == "existing"
    assert "api_key" not in payload


def test_workspace_requirements_are_validated():
    with pytest.raises(ValidationError, match="existing workspaces require path"):
        WorkspaceSpec(mode="existing")

    with pytest.raises(ValidationError, match="clone workspaces require repository_url"):
        WorkspaceSpec(mode="clone")


def test_model_reference_rejects_credentials_in_endpoint_url():
    with pytest.raises(ValidationError, match="must not contain credentials"):
        ModelReference(endpoint_url="https://user:secret@example.test/v1")


def test_status_and_result_keep_cancellation_request_distinct_from_confirmation():
    started = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    status = TaskStatus(run_id="run-1", state="cancellation_requested", updated_at=started, cancellation_requested=True)
    result = TaskResult(
        run_id="run-1",
        state="cancelled",
        started_at=started,
        finished_at=started,
        artifacts=[Artifact(kind="workspace", path="/work/project")],
        cancellation_requested=True,
    )

    assert status.state == "cancellation_requested"
    assert result.state == "cancelled"
    assert status.model_dump(mode="json")["cancellation_requested"] is True


def test_public_models_reject_unknown_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CancellationRequest(run_id="run-1", api_key="secret")
