# Redless Phase 1 implementation plan

Phase 1 defines and implements the machine-callable task, result, and cancellation
contracts described in Redless issue #2.

Stage 1 status: complete. See [the current boundary inventory](phase-1-stage-1-inventory.md).
Stage 2 status: complete. See [the public contract](phase-1-contract.md).
Stage 3 status: complete. See [the JSONL machine mode](phase-1-machine-mode.md).
Stage 4 status: complete. See [the deterministic fixture](phase-1-fixture.md).
Stage 5 status: complete. See [real execution](phase-1-stage-5-real-execution.md).
Stage 6 status: complete. See [capabilities and verification](phase-1-stage-6-capabilities.md).

The work is intentionally staged. Each stage should leave the existing human-facing
CLI and direct-provider behavior intact, and each stage should have focused tests before
the next stage begins.

## Stage 1: Inventory current boundaries

Map the existing CLI, agent loop, workspace creation, model configuration, trajectories,
artifacts, timeout behavior, and environment implementations. Identify stable seams for
the public machine interface without exposing private `minisweagent` imports.

Deliverable: a short boundary map and an explicit list of behavior that must remain
unchanged.

## Stage 2: Define the public contract

Add versioned public representations for:

- `TaskRequest`
- `TaskStatus`
- `TaskResult`
- `Artifact`
- `CancellationRequest`
- capability reports
- structured errors

Document JSON shapes, lifecycle states, terminal states, workspace specifications,
artifact references, cancellation semantics, and secret-handling rules.

## Stage 3: Add JSONL machine mode

Add a machine-facing CLI transport using JSON Lines:

- structured requests arrive on stdin;
- status, event, and result records go to stdout;
- human-oriented logs go only to stderr;
- malformed and unsupported requests produce structured errors;
- the transport remains separate from the durable contract semantics.

The existing human-facing CLI remains supported.

## Stage 4: Build the deterministic contract fixture

Implement a fixture that requires no live model server and proves that a consumer can:

- submit a bounded task;
- observe deterministic lifecycle status;
- observe a workspace change;
- receive an artifact reference;
- correlate records using `run_id` and `correlation_id`;
- receive deterministic structured failure;
- request cancellation for a blocking task;
- distinguish `cancellation_requested` from confirmed `cancelled`;
- verify logs do not corrupt stdout JSONL;
- receive explicit unsupported-capability errors;
- verify caller disappearance does not trigger resubmission.

## Stage 5: Connect real Redless execution

Adapt the public contract to the existing Redless agent, model, and environment path.
Redless owns workspace lifecycle, including existing, clone, create, and ephemeral
workspace modes plus explicit cleanup policy. Direct model-provider operation remains
functional, and credentials stay outside requests, results, trajectories, and logs.

Cancellation is cooperative and must not be reported as confirmed until execution has
actually ceased. Slow model requests must not be blindly retried after caller timeout or
disconnect.

## Stage 6: Advertise capabilities and verify end to end

Report only implemented capabilities, including task execution, structured results,
artifact references, cancellation request/confirmation, status events, native tools,
workspace containment, and resume/checkpoint support where applicable. Resume remains
unsupported until implemented.

Run the deterministic fixture and real execution tests, verify the existing CLI, inspect
the final diff, and record the verification actually performed.

## Completion boundary

Phase 1 is complete when a consumer script can submit a bounded task through JSONL,
observe accurate status, receive artifacts and a structured result, cancel supported
work with the correct confirmation semantics, and use the deterministic fixture without
a real model. Later HTTP adapters, Sidecaravan integration, identity semantics, and
checkpoint/resume are outside this phase.
