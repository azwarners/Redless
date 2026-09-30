# Phase 1, Stage 1: current boundary inventory

This inventory records the current Redless implementation before adding the
machine-callable task contract. It is based on the `main` checkout at commit
`a393b93` and is intended to identify stable seams and behavior that must remain
unchanged.

## Current execution path

The primary local run is:

```text
redless / minisweagent.run.mini.main
  -> load and recursively merge YAML/key-value configuration
  -> get_model(...)
  -> get_environment(...)
  -> get_agent(model, environment, ...)
  -> Agent.run(task)
  -> DefaultAgent.run()
  -> repeated model query / action execution steps
  -> trajectory save after each step
  -> exit result and optional trajectory file
```

The `redless` console script is currently an alias for
`minisweagent.run.mini:app`. The inherited `mini` and `mini-swe-agent` aliases remain
available. `redless-workspace` is a separate setup utility for `init` and `clone`.

## Existing public-ish component seams

### CLI and configuration

`src/minisweagent/run/mini.py` owns the human-facing CLI. It accepts a model, agent,
environment, task, limits, config specs, and trajectory output path. It prints startup,
progress/result, and trajectory-save messages through Rich and prompts interactively when
no task is supplied.

`src/minisweagent/config/__init__.py` resolves YAML files and dotted key-value overrides,
then `recursive_merge` combines them. Configuration selects implementation classes by
short names or import paths.

### Agent loop

`DefaultAgent` owns the sequential execution loop. It maintains the complete in-memory
message trajectory, calls `model.query(...)`, executes returned actions through the
environment, formats observations back through the model, and saves state after each
step when an output path is configured.

The agent already tracks model calls, tool calls, cost, model time, tool time, warnings,
and a deterministic live-context ledger. Its serialized trajectory contains internal
messages, model/environment configuration, version metadata, exit status, submission,
and statistics.

### Models

`get_model` selects a model implementation from configuration. Current relevant choices
include LiteLLM, direct llama.cpp, OpenRouter, other provider adapters, and deterministic
test models.

The internal `Model` protocol exposes query, message formatting, observation formatting,
template variables, and serialization. A future machine contract should adapt to this
boundary without exposing these internal protocol types as the public API.

### Environments and tools

`get_environment` selects among local, Docker, Singularity, Bubblewrap, Contree, and
SWE-ReX-backed environments. The internal `Environment` protocol exposes command
execution, text-tool execution, template variables, and serialization.

The local environment executes commands on the host process with a configurable working
directory and timeout. Containerized environments provide their own workspace and
cleanup behavior. Text operations use the repository's bounded text-tool implementation
where supported.

Environment selection is therefore an existing execution seam, but it is not yet a
uniform security or workspace contract across all implementations.

### Workspace setup

`redless-workspace init` creates a new Git repository and writes local model settings.
`redless-workspace clone` clones a repository and writes the same settings. These are
interactive/setup commands rather than a declarative run-time workspace service.

The current workspace utility does not yet provide a single request-level abstraction
for existing, clone, create, or ephemeral workspaces, nor an explicit cleanup policy.
That is required for the Phase 1 machine contract.

### Results, artifacts, and logs

The current agent returns an internal exit dictionary containing fields such as
`exit_status` and `submission`. The optional persisted artifact is the full trajectory
JSON file, whose path is configured by the agent.

There is no stable public `TaskResult` or `Artifact` schema yet. Trajectory data is an
internal audit record and should not be exposed as the machine contract itself.

The current human CLI writes informational output to stdout. Optional agent progress is
written to stderr, but this is not a complete machine-mode separation. A JSONL adapter
must own stdout and reserve stderr for human-oriented logs.

## Current limits and interruption behavior

The agent supports step, cost, and wall-clock limits. Individual tool actions can also
carry timeout overrides. Local command timeout handling kills the command process group;
model request timeout behavior is provider-specific.

Interactive mode handles keyboard interruption through internal `InterruptAgentFlow`
messages. There is no external run ID, cancellation request channel, cancellation
confirmation state, or caller-disconnect policy. A future machine interface must not
pretend that an interrupted caller or timeout proves the underlying model execution has
stopped.

## Behavior to preserve

Stage 1 identifies these compatibility requirements for later stages:

- existing `redless` human CLI behavior and direct-provider use;
- slow-model progress and timeout behavior;
- sequential agent-loop semantics;
- complete trajectory persistence and existing trajectory consumers;
- configured environment choices and their existing defaults;
- existing workspace setup commands;
- explicit internal exit statuses and submissions;
- no automatic retry/resubmission after uncertain model execution;
- no new dependency on Apmatia, Ladcemas, Ysparr, or Sidecaravan.

## Stage 1 conclusion

The safest integration point is a parallel public machine-mode adapter around the
existing configuration, agent, model, environment, and serialization seams. The first
machine-mode implementation should not rewrite `DefaultAgent`, replace trajectory
storage, or make the existing human CLI emit JSONL.

Stage 2 can now define transport-neutral public contract objects and map them explicitly
to these internal boundaries.

## Verification performed

- Confirmed the Codebase Memory index is ready for `main` at `a393b93`.
- Queried the indexed architecture, entry points, environment/model symbols, and agent
  call paths.
- Read the current CLI, configuration, protocol, agent, workspace, model, and
  environment implementations.
- No runtime code was changed and no external integration was invoked.
