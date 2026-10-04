# Decision: Python runtime modernization gate

Date: 2026-10-04.

## Problem

The current Personal AI Agent was developed and historically validated on
Python 3.9. Python 3.9 is end-of-life, while the official MCP Python SDK v2 for
the 2026-07-28 protocol requires Python 3.10 or newer. Implementing a private
MCP wire client only to preserve Python 3.9 would create avoidable protocol,
authorization and maintenance risk.

## Sources consulted

- Python Developer Guide, version lifecycle: Python 3.9 is unsupported.
- Official Model Context Protocol Python SDK v2: current stable SDK, supports
  the 2026-07-28 specification and requires Python 3.10+.
- MCP v2 client transport documentation: Streamable HTTP, stdio and custom
  transports are handled by the SDK, including protocol negotiation.
- MCP 2026-07-28 release notes: authorization hardening and stateless core.

## Selected approach

Do not change the user's local interpreter yet. First run the *complete* Windows
historical regression on both Python 3.9 and Python 3.12 in CI.

Python 3.12 is introduced as a compatibility target, not yet as an immediate
local requirement. Once the full suite is green, provider-neutral MCP work can
target the maintained runtime while the existing Python 3.9 installation stays
usable during migration.

## Invariants

- No feature may silently depend on MCP v2 while running under Python 3.9.
- No raw private reimplementation of MCP authorization/protocol negotiation.
- Full Windows tests, not only architecture unit tests, decide compatibility.
- The local user environment is not modified by this CI change.

## Next step

If Python 3.12 is green, add the official MCP v2 client as an optional connector
transport on the maintained runtime path and keep connector capabilities behind
the Kernel permission/approval boundary.
