# Redless Phase 1 machine mode

Stage 3 adds the reference machine transport: JSON Lines (JSONL) over stdin/stdout.
The public contract objects remain transport-neutral and are defined in
`docs/redless/phase-1-contract.md`.

## Input records

Each non-empty stdin line is one JSON object with a `type` and `payload`:

```json
{"type":"task","payload":{"contract_version":"1","run_id":"run-1","task":"...","workspace":{"contract_version":"1","mode":"create","cleanup_policy":"preserve"}}}
{"type":"cancel","payload":{"contract_version":"1","run_id":"run-1","reason":"operator requested stop"}}
{"type":"capabilities"}
```

The task payload is a `TaskRequest`. The cancellation payload is a
`CancellationRequest`. Unknown record types and invalid payloads produce structured
errors and do not raise unstructured text on stdout.

## Output records

Each stdout line is one JSON object with a `type` and `payload`:

```json
{"type":"status","payload":{"contract_version":"1","run_id":"run-1","state":"accepted",...}}
{"type":"status","payload":{"contract_version":"1","run_id":"run-1","state":"running",...}}
{"type":"result","payload":{"contract_version":"1","run_id":"run-1","state":"succeeded",...}}
```

Errors use `{"type":"error","payload":{...StructuredError...}}`. Human-oriented
diagnostics belong on stderr. The transport serializes records compactly and flushes
after every line so callers can observe lifecycle changes promptly.

Capability requests return a `CapabilityReport` record. The report is generated from
the selected executor and names both supported and unavailable features. Resume/
checkpoint, workspace containment, Sidecaravan tools, identity semantics, and token
streaming remain unavailable until their enforcement or implementation exists.

## Execution boundary

The transport provides a `TaskExecutor` interface. Its default executor now runs the
existing Redless agent through the Stage 5 adapter. `--fixture` selects the deterministic
contract fixture instead.

The transport supports one active run per process. A cancellation request sets a
cooperative cancellation event and emits `cancellation_requested`; the executor must
return a `cancelled` result only after it confirms execution has ceased.

EOF does not cancel an active run or request resubmission. The server waits for the
active executor thread to finish before returning.

## Invocation

After installation, the entry point is:

```bash
redless-machine < requests.jsonl > events.jsonl 2> redless.log
```

The current human-facing `redless` command is unchanged.
