# Redless Phase 1 deterministic fixture

Stage 4 provides a model-free consumer fixture through:

```bash
redless-machine --fixture
```

The fixture uses the Stage 3 JSONL transport and supports deterministic contract tests.
It does not call a model, clone repositories, access a provider endpoint, or require
Apmatia, Ladcemas, Ysparr, or Sidecaravan.

## Fixture tasks

- Any task other than the special values below succeeds and writes
  `redless-fixture-output.txt` to the requested workspace.
- `fixture:failure` returns a structured `fixture_failure` error.
- `fixture:block` waits for cancellation and returns `cancelled` only after the
  cancellation event is observed.

The fixture supports `task_execution`, `structured_results`, `artifact_references`,
`cancellation_request_support`, and `cancellation_confirmation_support`. A requested
capability outside that set returns a structured `unsupported_capability` failure.

The fixture accepts existing workspaces and creates new workspaces for `create` and
`ephemeral` requests. Repository cloning is intentionally unsupported in this
model-free fixture and fails explicitly rather than accessing the network.

## Consumer example

```json
{"type":"task","payload":{"contract_version":"1","run_id":"fixture-1","correlation_id":"consumer-1","task":"fixture:success","workspace":{"contract_version":"1","mode":"existing","path":"/tmp/redless-fixture"}}}
```

The resulting `TaskResult` contains an artifact filesystem reference. The fixture tests
also cover structured failure, unsupported capabilities, cancellation confirmation, and
the fact that input EOF does not cause automatic retry or resubmission.
