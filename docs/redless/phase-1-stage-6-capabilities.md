# Redless Phase 1, Stage 6: capabilities and verification

The machine transport accepts a capability query:

```json
{"type":"capabilities"}
```

It returns a `CapabilityReport` record with separate `supported` and `unavailable`
lists. The current real executor supports task execution, structured results, artifact
references, cooperative cancellation request/confirmation, status events, and the
existing agent native tools.

The following remain explicitly unavailable:

- workspace containment, because the local environment sets a working directory but is
  not a filesystem sandbox;
- resume/checkpoint support;
- Sidecaravan tool integration;
- external identity semantics;
- token streaming through the stable task contract.

The deterministic fixture reports the same contract-relevant limitations and is safe for
consumer tests without a model server. A subprocess test verifies that capability,
status, and result records are valid JSONL and that the legacy startup banner cannot
corrupt machine stdout.

## Verification performed

- Full repository suite: 661 passed, 38 skipped.
- Redless Stage 5/6 suite: 19 passed.
- Ruff checks passed for `src/redless` and `tests/redless`.
- JSONL fixture subprocess smoke test passed with capabilities, lifecycle, and result
  records only on stdout.
- `git diff --check` passed.

The skipped tests are existing environment/API gates: unavailable Podman and
Singularity runtimes, optional ProgramBench, and tests requiring live provider keys.
