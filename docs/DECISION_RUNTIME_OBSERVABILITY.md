# Decision: passive live runtime observability

Date: 2026-10-03. Phase: stable baseline / passive observation.

## Problem and current implementation

The Qt presence UI receives voice states and free-form logs. The existing
`MissionEventBus` serves the passive Kernel; the opt-in `TracingToolRegistry`
and `StructuredTracingRuntime` write live tool calls to SQLite. These traces
are not currently delivered to the UI. A finished conversational turn is also
recorded as a completed mission, without semantic completion criteria.

## Sources consulted

- [Qt signals and slots](https://doc.qt.io/qtforpython-6.10/tutorials/basictutorial/signals_and_slots.html)
  and [thread affinity](https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-threads-qobject.html):
  use a QObject slot and a queued signal to update widgets on the GUI thread.
- [Qt QGraphicsView](https://doc.qt.io/qtforpython-6.8/PySide6/QtWidgets/QGraphicsView.html):
  a possible later graph renderer compatible with the existing Widgets stack.
- [Microsoft UFO log architecture](https://github.com/microsoft/UFO/blob/main/documents/docs/ufo2/evaluation/logs/overview.md)
  and [evaluation](https://github.com/microsoft/UFO/blob/main/documents/docs/ufo2/evaluation/evaluation_agent.md):
  execution trajectories and evaluation evidence are separate artifacts.
- [LangGraph streaming documentation](https://docs.langchain.com/oss/python/langgraph/streaming),
  [runtime implementation](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/runtime.py)
  and [stream writer regression](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/tests/test_pregel.py):
  expose real execution updates through an explicitly supplied observer.
- [LangGraph issue 6447](https://github.com/langchain-ai/langgraph/issues/6447):
  nested/async event propagation can lose updates. This is a reported failure,
  not proof that its proposed resolution works in this project.
- [LangGraph PR 6378](https://github.com/langchain-ai/langgraph/pull/6378):
  a proposed streaming/persistence change illustrates the need to distinguish
  transient UI notifications from durable state. The discussion disputes the
  proposed diagnosis; it is not adopted as a validated fix.

These principles are adapted without adding UFO or LangGraph dependencies.

## Alternatives and selected approach

1. Parse existing text logs: ambiguous, leaks implementation details, cannot
   correlate parallel calls or distinguish explicit evidence.
2. Replace the UI with QML or a web frontend now: introduces migration and
   packaging work before the visual reference and event contracts are ready.
3. Extend the existing tracing proxies and EventBus, with an opt-in Qt activity
   panel: smallest compatible path. **Selected.**

Keep the runtime authoritative. Supply the existing bus explicitly to the
tracing proxies. In-memory observation must work without enabling SQLite
tracing. Existing structured tracing remains opt-in and compatible.

## Contract and invariants

- A turn has its own start/phase/finish events. Finishing a turn says nothing
  about semantic mission completion. The panel labels it as a turn.
- Tool request/result events carry stable IDs, parent correlation and elapsed
  time. Exceptions are observable and still propagate unchanged.
- Success is displayed as completed/unverified. Only a successful result with
  an explicit boolean `verified=true` **and structured observed evidence** can
  publish a proof for that exact result. A generic inspection or response text
  cannot upgrade another action.
- Provider/model labels describe the configured route. They do not claim to
  identify the provider actually used by an internal failover.
- Observers receive bounded, redacted payloads. Observer/journal failures must
  not stop tool execution or change the live result.
- The UI keeps bounded state, ignores late events from old turns, and receives
  cross-thread notifications through a queued Qt slot. No animation, polling
  timer, model call or tool execution is added by the panel.
- The original EventJournal mission completion semantics remain a known
  migration item; they must not be used as proof in the new panel.

## Risks, boundaries and validation

The existing bus dispatches handlers synchronously. Consumers must immediately
enqueue UI work; arbitrary slow third-party observers are not made asynchronous.
This first panel covers the model-native loop; legacy direct actions are a
separate coverage item. It is neither a semantic planner nor a live graph.
The full visual identity remains dependent on the user's reference.

Validation covers event order, result identity, exception propagation, bounded
state, request/result/proof correlation, missing evidence, failure followed by
recovery, late events, secret redaction, journal/observer failure isolation,
default-disabled routing compatibility and offscreen Qt thread delivery.
Windows application launch, real microphone/STT/TTS, provider APIs and
cross-application missions still require separate live acceptance tests.

## Use and reproducibility

Enable the developer panel for one local session from the project directory:

```powershell
$env:JARVIS_RUNTIME_OBSERVABILITY_ENABLED = "1"
& .\.venv\Scripts\python.exe run_jarvis.py
```

The default remains `0`; `.env` was not edited. No provider is changed by this
flag. SQLite is only used when structured tracing is separately enabled.
The panel observes the model-native loop; direct actions and provider-side
search/MCP calls are not yet individual tool rows. Empty/partial coverage must
not be interpreted as inactivity of the entire agent. A proof is a structured
observation reported by the local tool, not an independent mission evaluator.

Run the complete deterministic suite with isolated data and offscreen Qt:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_personal_agent_validation.ps1
```

Use `-Targeted` for the observation pack. The existing regression registry now
selects `TEST-RUNTIME-OBSERVABILITY` for related changed paths. No new event
system is introduced; the existing bus, event kinds and tracing proxies are
extended. Bound-method unsubscription is fixed to support worker teardown.

Local synthetic benchmark (3,000 calls, no journal, no network, tracemalloc
enabled): raw median 0.001 ms, observed median 0.237 ms, observed p95 0.266 ms,
0.688 s process CPU time over the observed batch, 100 retained calls, roughly
942 KiB peak Python allocations. These measure event production and state
projection, not GUI painting, GPU usage, process RSS or STT/TTS impact. They
are a diagnostic sample, not a latency guarantee.

The existing window was rendered offscreen with explicitly labelled test
fixtures and visually inspected. Segoe UI was loaded for this rendering because
the offscreen plugin's default font produced missing glyphs. No production font
asset was copied or committed. Actual Windows desktop rendering remains a live
acceptance item.
