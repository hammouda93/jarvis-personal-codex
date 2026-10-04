# Decision: provider-neutral connector capability boundary

Date: 2026-10-04.

## Problem

Jarvis has two partial connector concepts: an OpenAI Responses MCP configuration
loader and a passive provider-neutral ConnectorGateway. The final Personal AI
Agent cannot make Gmail/Calendar/Drive/GitHub depend on one model provider, nor
can it expose every remote mutation as an unclassified generic call.

## Official sources consulted

- Gmail API authorization scopes: request the narrowest scope needed.
- Gmail draft/send guides: drafts and sent messages are distinct resources and
  sending produces a new SENT message.
- Google Calendar events API and OAuth scopes: event creation is an authenticated
  calendar mutation.
- Google Drive permissions API: sharing is a permission mutation and has
  concurrency/ownership side effects.
- MCP 2026-07-28: authorization hardening, stateless core and standardized tools.
- Official MCP Python SDK v2: clients validate negotiated protocol results and
  provide standard Streamable HTTP/stdio transports.

## Mature implementations studied

- The official MCP Python SDK tests separate tool listing/calling, transport,
  authorization and protocol validation.
- AIOS keeps syscall admission/dispatch separate from execution managers.
- OpenClaw's lifecycle and policy code treats external writes as owned,
  reconcilable operations rather than arbitrary model text.

## Selected approach

Expose four provider-neutral model tools:

- list_connectors
- connector_read
- connector_write
- connector_external

Risk is not supplied by the model. It is read from the trusted connector
registry. The three execution tools accept only their matching risk class.
connector_external always requires explicit user approval.

Domain ownership is resolved by connector identity:

- Gmail / WhatsApp / Instagram -> Communication
- Google Calendar -> Personal Admin
- Google Drive -> Data
- GitHub -> Developer

The ConnectorGateway remains the backend boundary. No account is considered
connected merely because metadata exists; a real registered adapter must be
available.

## Verification invariant

Backend success alone is not proof of an external mutation. A connector action
is marked verified only when the adapter also returns structured result data
such as a message/event/file/commit identifier. Otherwise the action remains
successful but unverified.

## Python / MCP transport

The official MCP Python SDK v2 requires Python 3.10+. The repository is testing
Python 3.12 compatibility before adding the real MCP v2 transport. No private
JSON-RPC/MCP implementation is introduced to preserve Python 3.9.

## Tests

Fake adapters exercise the real gateway/risk contracts without user accounts:
domain routing, connected-backend status, read/write risk separation, approval
for external effects, and proof requirements. Live account/API validation is a
separate human test once credentials/adapters are configured.
