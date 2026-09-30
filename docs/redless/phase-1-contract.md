# Redless Phase 1 public contract

Stage 2 introduces the transport-neutral public contract types. The reference transport
will be JSONL over stdin/stdout in Stage 3, but these objects do not depend on that
transport.

The import boundary is the top-level `redless` package. Consumers should not import
private `minisweagent` implementation classes.

## Contract version

All public objects carry `contract_version: "1"`. A future incompatible shape requires
a new contract version rather than silently changing the meaning of an existing field.

## Task request

`TaskRequest` contains:

- `run_id` and optional caller `correlation_id`;
- task text;
- declarative workspace specification;
- optional non-secret model reference;
- optional opaque identity context;
- optional execution policy;
- optional result and trajectory destinations;
- required capabilities requested by the caller.

Workspace modes are `existing`, `clone`, `create`, and `ephemeral`. Cleanup policy is
explicit: `preserve`, `on_success`, or `always`.

Clone workspaces may specify `ref` as a branch, tag, or commit ID. Redless checks out
the selected ref detached after cloning. `ref` is invalid for existing, created, and
ephemeral workspaces.
Model references accept a configured profile, model name, or endpoint URL. Credentials
are not fields in the contract, and endpoint URLs containing user information are
rejected.

## Status and result

The lifecycle states are:

`accepted`, `running`, `cancellation_requested`, `succeeded`, `failed`, and `cancelled`.

Only `succeeded`, `failed`, and `cancelled` are terminal. A `cancellation_requested`
status is not confirmation that execution has stopped.

`TaskResult` contains terminal timing, an optional final answer, filesystem artifact
references, an optional trajectory reference, and an optional structured error.
Artifacts are references, not embedded blobs.

## Cancellation

`CancellationRequest` identifies a `run_id` and may include a reason. The request itself
does not imply that the task has stopped. The execution adapter must emit `cancelled`
only after it confirms that execution has ceased.

## Capabilities

`CapabilityReport` lists supported and unavailable capability names. Later stages must
populate this report from actual implementation support. Resume/checkpoint, token
streaming, Sidecaravan tools, and external identity semantics must not be advertised by
default merely because related internal or planned features exist.

## Stage 2 boundary

This stage defines and validates data shapes only. It does not add JSONL transport,
workspace creation, model execution, cancellation control, or capability discovery.
