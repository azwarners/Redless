# Redless Phase 1, Stage 5: real execution

Stage 5 connects the public task contract to the existing Redless model, environment,
and agent factories through `redless.executor.RedlessExecutor`.

## Configuration boundary

The executor loads `slow_local.yaml` by default, or the profile named by
`TaskRequest.model.profile`. A request may override the configured model name and the
OpenAI-compatible endpoint URL. Provider credentials are still obtained from the
configured environment; they are not accepted in the request.

Provider credentials remain available to the model factory at runtime. Secret fields are
redacted at serialization boundaries, so credentials do not enter serialized
trajectories, structured results, or public machine output.

Execution policy currently supports environment selection, per-command timeout, and
wall-time limits. `allowed_tools` and network policies other than `inherit` fail
explicitly because the existing environment adapters do not enforce them uniformly.

## Workspace lifecycle

Redless owns `create`, `clone`, and `ephemeral` workspaces. Existing workspaces must be
preserved and cannot be deleted by a task request. Clone requests use `git clone`, then
check out an optional branch, tag, or commit ref in detached mode. Cleanup is applied
only to workspaces created by Redless:

- `preserve` returns a workspace artifact reference;
- `on_success` removes the workspace only after a successful task;
- `always` removes it after either success or failure.

Cleanup is completed before the terminal result is returned. A cleanup failure becomes a
structured `workspace_cleanup_error` result.

## Cancellation and results

The model and environment adapters check the shared cancellation event before and after
their cooperative operation. A slow model request is allowed to finish; cancellation is
not reported as confirmed until the agent thread has stopped. A caller disconnect or EOF
does not retry the task.

Successful submitted runs return the agent submission, a workspace reference when the
workspace is preserved, and a trajectory reference when requested. Result destinations
are explicit filesystem paths from the request.
