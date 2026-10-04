# Decision: durable live Kernel scheduling without blind replay

Date: 2026-10-04. Scope: authoritative live tool execution.

## Problem

The live Kernel governance layer already authorizes every native tool against an
agent manifest and capability. It still executes the underlying tool directly,
so the live path has no durable QUEUED/RUNNING/terminal ledger and the existing
MissionScheduler remains passive. A process crash during a side effect therefore
cannot be distinguished from a tool call that never started.

## Sources consulted

Official / primary documentation:

- SQLite transactional guarantees and crash recovery:
  https://www.sqlite.org/transactional.html
- SQLite WAL mode and recovery:
  https://www.sqlite.org/wal.html
- OpenAI Agents runtime loop and resumable state:
  https://developers.openai.com/api/docs/guides/agents/running-agents
- OpenAI guardrails and human review:
  https://developers.openai.com/api/docs/guides/agents/guardrails-approvals

Mature GitHub implementations inspected:

- agiresearch/AIOS `aios/scheduler/fifo_scheduler.py`: separate queued
  syscalls from execution managers and let the scheduler own admission.
- agiresearch/AIOS
  `tests/modules/memory/test_write_barrier_integration.py`: test the dispatcher
  boundary independently of the full kernel.
- openclaw/openclaw subagent registry lifecycle code: an interrupted write does
  not prove non-execution; terminal ownership is reconciled before publication.
- microsoft/UFO AgentOS documentation: deterministic state machines and bounded
  recovery are kept separate from LLM reasoning.

## Selected approach

Keep the current synchronous model/tool loop, but put an authoritative durable
scheduler directly under the live Kernel policy gate.

For each authorized call:

```
AUTHORIZED
  -> persist QUEUED
  -> scheduler admission
  -> persist RUNNING
  -> execute existing native tool
  -> persist SUCCEEDED / FAILED
```

The scheduler does not create a second automation engine. The existing
NativeToolRegistry remains the executor.

## Crash invariant

A request found RUNNING after restart is an uncertain external outcome:

```
RUNNING AT CRASH
  != FAILED
  != SAFE TO RETRY
```

It is exposed as a recovery candidate and is never replayed automatically.
Fresh observation/reconciliation must decide whether retry, skip or repair is
safe.

A request found QUEUED did not enter execution. It is labelled safe-to-retry,
but this first live scheduler still does not silently execute old intent in a
new session. Future long-mission coordination may resume it under the persisted
mission owner.

## Risks

- The current provider loop is synchronous, so this change supplies durable
  admission and recovery identity, not yet true background parallelism.
- The request ledger stores bounded tool arguments. Existing secret redaction
  policy remains required before sensitive connector payloads are allowed here.
- Cross-process worker ownership is not implemented yet.

## Validation

New unit tests cover persisted transitions, terminal failures, capacity release,
RUNNING crash recovery, QUEUED non-replay, and duplicate request protection.
The GitHub Actions matrix compiles the new module and runs these tests on Linux
and Windows before the full Windows historical suite.
