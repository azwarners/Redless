# REDLESS Roadmap

REDLESS is an independently usable autonomous execution engine for software-engineering and other bounded computer tasks, optimized for slow local language models.

Its core promise is:

> Give REDLESS a task and enough information to locate or create its workspace; REDLESS prepares the workspace, executes autonomously within policy, records what happened, and returns a structured result.

REDLESS is intentionally smaller than the systems that may call it. It owns **one execution loop, one run, one workspace lifecycle, and one result contract**. Higher-level systems may schedule, compose, or present REDLESS runs, but REDLESS remains useful without them.

This roadmap supersedes the older phase plan that treated workspace preparation and machine-facing contracts as later concerns.

---

## Current architectural direction

### REDLESS owns

- autonomous task execution
- the model/tool loop
- workspace materialization and cleanup according to explicit policy
- workspace containment for supported execution environments
- trajectories and run-local artifacts
- structured task status and results
- cancellation handling
- honest capability reporting
- a stable public machine-callable contract
- minimal native execution tools required for standalone operation

### REDLESS does not own

- multi-agent orchestration
- long-lived user or character identity
- shared scheduling across applications
- a general durable job queue
- chat UI
- model lifecycle management
- application-specific business logic
- global tool catalogs
- cross-application memory

Those responsibilities belong to callers or neighboring components.

Current stack boundaries:

- **Apmatia** may supply optional identity context and agent behavior. REDLESS does not define Apmatia identity semantics.
- **Ladcemas** may manage host configuration, shared scheduling, and higher-level background-job coordination.
- **Sidecaravan** provides reusable external capabilities and tool adapters. REDLESS keeps ownership of its execution loop.
- **Ysparr** may provide model/provider transport. Direct model endpoints remain supported.
- **AggregaOS** may install and configure REDLESS, but REDLESS must remain independently usable.

---

# Active implementation plan

The canonical implementation work is tracked in GitHub Issues.

## Phase 1 — Stable machine-callable execution contract

Tracking issue: [#2 — Define and implement machine-callable task, result, and cancellation contracts](https://github.com/azwarners/Redless/issues/2)

This is the current foundation.

### Reference transport

The first machine interface is a CLI subprocess contract using **JSON Lines (JSONL) over stdin/stdout**.

- structured machine messages go over stdin/stdout
- human-oriented logs go to stderr
- the public task/result contract is transport-neutral
- future HTTP or other adapters must preserve the same semantics rather than inventing a second API

### Public contract

Phase 1 defines versioned forms of:

- `TaskRequest`
- `TaskStatus`
- `TaskResult`
- `Artifact`
- `CancellationRequest`
- capability reporting

The public contract must expose stable concepts rather than private mini-SWE-agent-derived Python internals.

### Lifecycle

Initial run states:

- `accepted`
- `running`
- `cancellation_requested`
- `succeeded`
- `failed`
- `cancelled`

Terminal states:

- `succeeded`
- `failed`
- `cancelled`

Cancellation is a request until REDLESS has confirmed execution has stopped.

Caller disconnect or timeout does not imply cancellation and must never trigger blind automatic resubmission.

### Workspace lifecycle

The caller supplies a **declarative workspace specification**. REDLESS owns workspace materialization and cleanup.

Supported concepts should include:

- existing workspace
- fresh clone
- new empty workspace
- ephemeral workspace
- optional repository/ref selection
- explicit cleanup policy such as preserve, cleanup on success, or always cleanup

A human must not be required to SSH into the execution host and run setup commands before an agent-originated task can begin.

Existing prepared workspaces remain supported, but they are not required.

REDLESS must not silently destroy a workspace or its artifacts.

### Model configuration

A task references a configured model profile or endpoint without embedding secrets into the task contract.

Direct OpenAI-compatible endpoints such as llama.cpp remain supported. Ysparr-backed endpoints are optional and use the same REDLESS model boundary.

Credentials must not leak into requests, results, trajectories, or logs.

### Identity context

Optional identity context is opaque to REDLESS.

REDLESS may carry caller-provided identity context through the supported boundary, but it does not define personality, memory, preferences, or identity permissions.

### Deterministic contract fixture

Consumer tests must be possible without a real model server.

The deterministic fixture should prove:

- valid task submission
- status transitions
- deterministic workspace mutation
- successful structured result
- artifact discovery
- run correlation
- requested versus confirmed cancellation
- structured failures
- clean separation of stdout machine output and stderr logs
- explicit rejection of unsupported capabilities
- no retry/resubmission assumption when a caller disappears

### Capability reporting

REDLESS must advertise only what is implemented.

Capabilities should distinguish at least:

- task execution
- structured results
- artifact references
- cancellation request support
- cancellation confirmation support
- structured status/events
- checkpoint/resume
- native tools
- workspace-containment guarantees

Do not claim checkpoint/resume until it actually exists.

Do not collapse all meanings of "streaming" into one flag. Status/event streaming and model-token streaming are different capabilities.

---

## Phase 2 — Sidecaravan capability integration

Tracking issue: [#3 — Integrate Sidecaravan capabilities without weakening execution limits](https://github.com/azwarners/Redless/issues/3)

After the machine contract is stable, REDLESS can consume selected Sidecaravan capabilities.

### Principles

- REDLESS keeps ownership of its execution loop.
- Sidecaravan supplies reusable capabilities; it does not become the REDLESS loop.
- Tool/capability selection remains scoped.
- Do not inject every installed tool into every prompt.
- Native REDLESS tools remain available where required for standalone operation.
- Native tools must not bypass a restricted capability policy.
- Unsupported restricted profiles must fail explicitly rather than pretending to be enforced.
- Tool invocation and results remain attributable in trajectories.

Phase 2 must preserve both direct model endpoint operation and Ysparr-backed configuration without duplicating loop ownership.

---

# Execution and safety direction

These are architectural requirements that support the active phases. They are not separate speculative products.

## Workspace containment

The assigned workspace is an execution boundary, not merely an initial working directory.

For supported execution environments, the default policy should prevent arbitrary mutation outside the workspace.

Static shell inspection may be used as a guardrail, but it must not be represented as a complete security boundary. Stronger OS/container-level isolation should be used where practical.

Workspace-policy violations should be explicit, observable, and distinguishable from ordinary command failures.

## Background-safe execution

REDLESS must tolerate slow inference and callers that stop waiting.

A browser closing, a phone sleeping, a chat connection ending, or a caller-side timeout does not mean the REDLESS run should be cancelled.

Higher-level systems may persist and query run state, but REDLESS's contract must make uncertain execution safe to reason about:

> caller disconnect != cancellation  
> caller timeout != REDLESS timeout  
> uncertain execution != safe retry

## Structured results and artifacts

Human logs must not be the API.

Callers should be able to determine final state, error information, produced artifacts, and trajectory references without scraping terminal output.

Artifacts are initially filesystem references rather than embedded binary payloads.

## Slow-model behavior

REDLESS remains optimized for models where inference may take minutes or longer.

The execution design should continue to favor:

- cheap deterministic local tool work
- conservative retry behavior
- full trajectory preservation
- clear model-call progress
- no arbitrary deadline on a healthy slow model response by default
- bounded command/tool execution where appropriate

---

# Later work driven by real consumers

The following may become useful, but should be added only when downstream use demonstrates a concrete requirement.

## Checkpoint and resume

Checkpoint/resume is currently unsupported and must be advertised as such.

If implemented later, it needs explicit semantics for:

- what state is durable
- what can be resumed safely
- model/tool calls that were in flight at interruption
- workspace consistency
- idempotency and duplicate execution risk

It must not be added merely as a label around restarting a task.

## Durable run lookup and reattachment

Phone/chat-driven workflows may eventually need a durable way to query or reattach to long-running work.

The durable scheduler/job registry may live outside REDLESS, likely in Ladcemas or another caller. REDLESS should expose enough stable run identity and result semantics for that system to work without making REDLESS itself a general job platform.

## Steering

External steering between model calls may be useful for long-running tasks, but it should not reintroduce an interactive chat CLI.

Any steering mechanism must be:

- asynchronous
- recorded in the trajectory
- compatible with workspace containment
- explicit in the machine contract
- optional

## Additional transports

HTTP, local sockets, or other adapters may be added around the stable execution contract when a real consumer needs them.

Transport adapters must not redefine lifecycle, cancellation, workspace, or result semantics.

---

# Near-term non-goals

REDLESS should not become:

- a chat application
- a multi-agent framework
- a workflow designer
- a model downloader or registry
- a model server manager
- a GUI
- a plugin marketplace
- a general database-backed application platform
- the owner of Apmatia identity/memory
- the owner of Sidecaravan's capability catalog
- the owner of Ysparr's provider transport
- the owner of shared system-wide scheduling

REDLESS may integrate with these systems while remaining independently useful.

---

# Guiding principles

When deciding whether functionality belongs in REDLESS, ask:

> Does this help REDLESS accept one bounded task, prepare the workspace it needs, execute that task safely and autonomously, and return a trustworthy result?

If yes, it probably belongs in REDLESS.

If it coordinates many agents, many applications, long-lived user state, shared schedules, or system-wide workflows, it probably belongs outside REDLESS.

The long-term target is deliberately simple:

> **Task + workspace specification + execution policy + model configuration → autonomous REDLESS run → structured status, artifacts, and result**
