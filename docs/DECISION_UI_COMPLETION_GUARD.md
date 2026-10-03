# Decision: constrain the legacy UI completion guard

2026-10-03 — baseline correction, before any Kernel authority change.

**Reproduction:** the existing regression asks about MS Football, changes topic
to a software project, then says it wants to add payments. Routing correctly
leaves MS Football. `_requested_action_capabilities` nevertheless matches the
infinitive `ajouter` and injects a mandatory `write_ui` repair. A real model
would make an unnecessary additional call and could try to type into the
foreground application. The fake model exhausts its responses.

**Sources:** [Microsoft agent concepts](https://learn.microsoft.com/en-us/agent-framework/concepts/agents/),
[LangGraph runtime/context](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/runtime.py),
its [streaming regression tests](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/tests/test_pregel.py),
and the issues/PR discussion linked in `DECISION_RUNTIME_OBSERVABILITY.md` were
consulted while assessing incremental runtime changes. They support keeping
context, tool execution and observation separate; they do not validate a French
keyword classifier. The decisive evidence here is the local reproduced trace.

**Alternatives:** remove the completion guard (loses existing write-goal
protection); introduce a new semantic planner immediately (premature migration);
narrow ambiguous edit verbs to requests with a generic UI destination
(selected). Clear write commands and the historical STT recovery still retain
their existing completion checks. No application-specific rules are added.

**Risk:** the guard remains a language heuristic. It is not a semantic mission
engine and cannot prove arbitrary intent or completion. This correction reduces
one unsafe false positive; later semantic mission work must replace inference
from isolated verbs with explicit grounded objectives.

**Validation:** existing domain-switch regression, two new regression methods
covering conversational edits and concrete UI edits, and all runtime/recognition
tests. The initial `json` NameError and frozen-settings mock were test harness
defects; their assertions and expected product behavior were preserved.
