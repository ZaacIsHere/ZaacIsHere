# mnemex

**A memory + knowledge base system for Claude.** Give an agent durable,
cross-session memory and just-in-time recall of everything it has learned —
built on the three current primitives that actually compound, with the core in
**pure Python (zero dependencies)**.

```
┌──────────────────────────────────────────────────────────────┐
│  Claude (Messages API)                                         │
│    tools: [ memory_20250818 ,  kb_search ]                     │
│    context_management: clear_tool_uses_20250919   ← ~84% fewer │
│                                                      tokens    │
└───────────────┬───────────────────────────┬──────────────────┘
                │ read / write               │ recall
        ┌───────▼────────┐          ┌────────▼─────────┐
        │ MemoryToolHandler        │ KnowledgeBase     │
        │ spec-exact, path-safe    │ BM25, JIT recall  │
        └───────┬────────┘          └────────┬─────────┘
                └──────────────┬─────────────┘
                       ┌───────▼────────┐
                       │ StorageBackend │  local · in-memory · git-sync
                       └────────────────┘
```

## Why this design

The three pieces each solve a different half of "memory," and they stack:

| Primitive | What it buys you | Spec |
|-----------|------------------|------|
| **Memory tool** | Claude persists notes/progress to files that survive context resets and summarization. | `memory_20250818` |
| **Knowledge base** (`kb_search`) | *Just-in-time* recall: Claude searches accumulated notes and reads back only what's relevant, instead of front-loading everything into context. | BM25, local |
| **Context editing** | Old tool results are cleared server-side as context grows — benchmarked at ~84% token savings on long tasks — while memory keeps what must survive. | `clear_tool_uses_20250919` |

The memory-tool handler is **spec-exact** (every command, return string, and
error message matches the platform docs) and **hardened against path
traversal**, which is the one genuinely security-critical part of a
client-side memory tool. Retrieval is a self-contained BM25 index — no
embeddings model, no vector DB, no network — so the whole thing runs on a
free-tier or stateless worker and persists as plain, git-friendly markdown.

## Install

```bash
pip install -e mnemex            # core, pure stdlib
pip install -e 'mnemex[agent]'   # + anthropic SDK for the live agent
```

## Quickstart (no API key)

```bash
mnemex init                                   # create ./memory
echo "WHIP lets OBS publish WebRTC to an ingress endpoint." \
  | mnemex add --title "WHIP ingress" --tags webrtc,broadcast
mnemex search "obs low latency streaming"     # BM25 recall
mnemex view /memories/kb/whip-ingress.md
mnemex --git init                             # git-backed, commits every write
```

Or drive the primitives directly — see [`examples/demo.py`](examples/demo.py):

```python
from mnemex import InMemoryBackend, KnowledgeBase, MemoryToolHandler

backend = InMemoryBackend()
handler = MemoryToolHandler(backend)          # the memory tool, client-side
kb = KnowledgeBase(backend)

kb.add_note("NDI bridging", "Bridge NDI to WebRTC for remote multiview.",
            tags=["broadcast"])

# exactly what Claude sees when it calls the tools:
print(handler.execute({"command": "view", "path": "/memories"}).content)
print(kb.execute_search_tool({"query": "remote multiview over ip"}))
```

## Live agent

`MemoryAgent` wires the memory tool, `kb_search`, and context editing into one
Messages API loop:

```python
from mnemex import LocalFilesystemBackend, MemoryAgent

agent = MemoryAgent(LocalFilesystemBackend("./memory"))   # needs ANTHROPIC_API_KEY
print(agent.run("Summarize what you know about our broadcast stack, "
                "then note anything new you learn to memory."))
```

It sends the memory tool and `kb_search` as `tools`, enables
`clear_tool_uses_20250919` under the `context-management-2025-06-27` beta
(keeping the 3 most recent tool exchanges, never clearing `kb_search`
pointers), and runs the tool-use loop to completion.

## MCP server — mnemex as Claude's memory, everywhere

`mnemex mcp` exposes the same store over the Model Context Protocol
(spec 2025-11-25, zero dependencies — the transports are hand-rolled
newline-delimited JSON-RPC and a stateless Streamable HTTP endpoint). Tools:
`kb_search`, `kb_add_note`, `memory_list`, `memory_read`, `memory_write`,
`memory_edit`, `memory_delete`, `memory_rename` — all routed through the same
audited, path-hardened handler as the agent loop.

**Claude Code:**

```bash
claude mcp add mnemex -- mnemex-mcp --dir ~/.mnemex --git
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mnemex": {
      "command": "mnemex-mcp",
      "args": ["--dir", "/Users/you/.mnemex", "--git"]
    }
  }
}
```

**claude.ai (web/mobile) custom connector** — needs a reachable HTTPS URL, so
run the HTTP transport behind your tunnel/host of choice:

```bash
MNEMEX_TOKEN=your-secret mnemex-mcp --dir ~/.mnemex --http 8848
# POST JSON-RPC to http://host:8848/mcp with Authorization: Bearer your-secret
```

Point every surface at the same `--git` store and Claude has one persistent,
inspectable, versioned memory across app, desktop, code, and mobile.

### The curation loop (meta-learning)

Memory systems rot write-only. Close the loop with a scheduled session (a
Claude app routine, a cron'd `claude -p`, or a GitHub Action) that runs a
prompt like:

> Review /memories/kb with kb_search and memory_list. Merge duplicate notes,
> promote recurring lessons into a single canonical note tagged `principle`,
> prune anything stale or superseded, and update /memories/progress.md with
> what changed.

Because the store is git-backed, every curation pass is a commit — you can
audit exactly how the knowledge base evolved, and revert a bad distillation.

## Storage backends

All three implement one small `StorageBackend` surface, so the audited handler
logic runs unchanged over any of them:

- **`LocalFilesystemBackend`** — a directory on disk (default).
- **`InMemoryBackend`** — ephemeral; for tests and demos.
- **`GitSyncBackend`** — commits after every mutation; optional `auto_push` so a
  stateless worker can persist its whole memory/KB to a remote (GitHub, a
  HuggingFace dataset repo, anywhere) and rehydrate on the next run.

Bring your own (S3, Redis, a database) by implementing the same six methods.

## Security

Client-side memory means *your* code executes every file op Claude requests, so
path safety is on you. `mnemex` rejects — with tests
([`tests/test_path_safety.py`](tests/test_path_safety.py)) — every path that
isn't rooted at `/memories`, any `..` segment, URL-encoded traversal
(`%2e%2e`), and backslash tricks, and the disk backend re-confirms the resolved
path stays inside the store root as defence in depth.

## Tests

```bash
pip install -e 'mnemex[dev]' && pytest    # 66 tests, <1s, no network
```

## Layout

```
src/mnemex/
  memory_tool.py     spec-exact memory_20250818 handler + path safety
  knowledge_base.py  BM25 knowledge base + kb_search tool
  backends.py        local / in-memory / git-sync storage
  mcp_server.py      MCP server (stdio + Streamable HTTP), zero deps
  agent.py           memory + kb + context-editing loop (needs anthropic SDK)
  cli.py             mnemex init | add | search | view | reindex | stats | mcp | ask
```

## License

MIT
