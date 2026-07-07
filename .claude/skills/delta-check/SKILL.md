---
name: delta-check
description: Before writing code against the Anthropic API, MCP spec, or Claude Code features, recall known post-cutoff changes and verify load-bearing details against live docs. Use when a task involves memory tool, context editing, MCP transports/spec revisions, model IDs, or any API whose spec may have changed since training.
---

# Delta check: don't code from training memory

Promoted from memory/kb principle (2026-07-07): training memory gets tool
type strings, return strings, beta headers, and spec revisions wrong.
Session evidence: memory_20250818 return strings, clear_tool_uses_20250919
config, context-management-2025-06-27 beta, MCP 2025-11-25 stdio framing —
all needed live verification; two real bugs were caught this way.

## Procedure

1. Search the store first: `mnemex --dir memory search "delta <topic>"` —
   the monthly delta sweep records post-cutoff changes as notes tagged
   `delta` with source URLs.
2. For any load-bearing string (tool type, beta header, protocol version,
   return format), verify against the live doc before writing code:
   platform.claude.com/docs, modelcontextprotocol.io, code.claude.com/docs.
3. Write the exact strings into tests, not just implementation, so drift
   is caught mechanically later.
4. If you find a change not yet in the store, record it:
   `mnemex --dir memory add --title "Delta <YYYY-MM>: <topic>" --tags delta --source <URL>`
