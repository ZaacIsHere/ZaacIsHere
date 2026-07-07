"""MCP server exposing mnemex as live memory for any MCP client.

Implements the Model Context Protocol (spec revision 2025-11-25) with zero
third-party dependencies:

* **stdio transport** -- newline-delimited JSON-RPC over stdin/stdout, for
  Claude Code (``claude mcp add mnemex -- mnemex mcp``) and Claude Desktop.
* **Streamable HTTP transport** (``mnemex mcp --http PORT``) -- a single
  ``/mcp`` endpoint answering POSTed JSON-RPC with JSON, for remote use
  (e.g. a claude.ai custom connector). Optional bearer auth via
  ``$MNEMEX_TOKEN``.

The server is a thin adapter: every tool call routes into the same audited
:class:`~mnemex.memory_tool.MemoryToolHandler` and
:class:`~mnemex.knowledge_base.KnowledgeBase` used by the agent loop, so the
path-traversal protection and note format are identical everywhere.

Tool names are discrete and self-describing (``memory_read``, ``kb_search``,
...) rather than a single command-multiplexed tool, because generic MCP
clients pick tools by name and schema.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

from .backends import StorageBackend
from .knowledge_base import KnowledgeBase
from .memory_tool import MemoryToolHandler

#: Spec revisions this server can speak, newest first.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

SERVER_INFO = {"name": "mnemex", "version": "0.1.0"}

_PATH_DESC = (
    "Memory path rooted at /memories, e.g. /memories/kb/notes.md. "
    "Paths outside /memories are rejected."
)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "kb_search",
        "description": (
            "Search the persistent knowledge base (BM25-ranked). Returns "
            "matching note paths under /memories/kb with snippets. Use this "
            "to recall prior knowledge before re-deriving it, then read the "
            "full note with memory_read."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for."},
                "k": {"type": "integer", "description": "Max results (default 5)."},
                "tag": {"type": "string", "description": "Restrict to notes with this tag."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_add_note",
        "description": (
            "Add (or update, by identical title) a note in the persistent "
            "knowledge base. Notes are markdown with title/tags/source "
            "front-matter and become searchable via kb_search immediately."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string", "description": "Markdown note body."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional topic tags.",
                },
                "source": {"type": "string", "description": "Provenance of the note."},
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "memory_list",
        "description": "List files and directories in the memory store (2 levels deep).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to list (default /memories).",
                },
            },
        },
    },
    {
        "name": "memory_read",
        "description": "Read a memory file (line-numbered). Optionally a line range.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _PATH_DESC},
                "start_line": {"type": "integer", "description": "1-indexed first line."},
                "end_line": {"type": "integer", "description": "Last line, -1 for EOF."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "memory_write",
        "description": "Create or overwrite a memory file with the given content.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _PATH_DESC},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "memory_edit",
        "description": (
            "Replace one unique occurrence of old_str in a memory file with "
            "new_str (omit new_str to delete the text)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _PATH_DESC},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
            },
            "required": ["path", "old_str"],
        },
    },
    {
        "name": "memory_delete",
        "description": "Delete a memory file or directory (recursively).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _PATH_DESC},
            },
            "required": ["path"],
        },
    },
    {
        "name": "memory_rename",
        "description": "Rename or move a memory file or directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_path": {"type": "string", "description": _PATH_DESC},
                "new_path": {"type": "string", "description": _PATH_DESC},
            },
            "required": ["old_path", "new_path"],
        },
    },
]


class MnemexMCPServer:
    """Transport-agnostic MCP message dispatcher over a storage backend."""

    def __init__(self, backend: StorageBackend):
        self.handler = MemoryToolHandler(backend)
        self.kb = KnowledgeBase(backend)

    # -- JSON-RPC dispatch ------------------------------------------------
    def handle_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one JSON-RPC message. Returns the response, or None for
        notifications (which get no reply)."""
        method = msg.get("method", "")
        msg_id = msg.get("id")
        is_notification = "id" not in msg

        try:
            if method == "initialize":
                result = self._initialize(msg.get("params") or {})
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOL_DEFINITIONS}
            elif method == "tools/call":
                result = self._tools_call(msg.get("params") or {})
            elif method.startswith("notifications/"):
                return None
            else:
                if is_notification:
                    return None
                return _rpc_error(msg_id, -32601, f"Method not found: {method}")
        except Exception as exc:  # noqa: BLE001 - surface as JSON-RPC error
            if is_notification:
                return None
            return _rpc_error(msg_id, -32603, f"Internal error: {exc}")

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion", "")
        version = (
            requested
            if requested in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "mnemex is your persistent memory and knowledge base. At the "
                "start of a task, call kb_search (or memory_list) to recall "
                "relevant prior knowledge. As you learn durable facts or make "
                "decisions worth keeping, save them with kb_add_note. Use "
                "memory_read/memory_write for progress files that must "
                "survive context resets."
            ),
        }

    # -- tools ------------------------------------------------------------
    def _tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        dispatch: dict[str, Callable[[dict[str, Any]], tuple[str, bool]]] = {
            "kb_search": self._tool_kb_search,
            "kb_add_note": self._tool_kb_add_note,
            "memory_list": self._tool_memory_list,
            "memory_read": self._tool_memory_read,
            "memory_write": self._tool_memory_write,
            "memory_edit": self._tool_memory_edit,
            "memory_delete": self._tool_memory_delete,
            "memory_rename": self._tool_memory_rename,
        }
        fn = dispatch.get(name)
        if fn is None:
            text, is_error = f"Unknown tool: {name}", True
        else:
            text, is_error = fn(args)
        result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
        if is_error:
            result["isError"] = True
        return result

    def _tool_kb_search(self, args: dict[str, Any]) -> tuple[str, bool]:
        return self.kb.execute_search_tool(args), False

    def _tool_kb_add_note(self, args: dict[str, Any]) -> tuple[str, bool]:
        path = self.kb.add_note(
            args["title"],
            args["body"],
            tags=list(args.get("tags") or []),
            source=args.get("source", ""),
        )
        return f"Note saved: {path}", False

    def _mem(self, command: dict[str, Any]) -> tuple[str, bool]:
        res = self.handler.execute(command)
        return res.content, res.is_error

    def _tool_memory_list(self, args: dict[str, Any]) -> tuple[str, bool]:
        return self._mem(
            {"command": "view", "path": args.get("path") or "/memories"}
        )

    def _tool_memory_read(self, args: dict[str, Any]) -> tuple[str, bool]:
        command: dict[str, Any] = {"command": "view", "path": args["path"]}
        if "start_line" in args:
            command["view_range"] = [args["start_line"], args.get("end_line", -1)]
        return self._mem(command)

    def _tool_memory_write(self, args: dict[str, Any]) -> tuple[str, bool]:
        return self._mem(
            {"command": "create", "path": args["path"], "file_text": args["content"]}
        )

    def _tool_memory_edit(self, args: dict[str, Any]) -> tuple[str, bool]:
        return self._mem(
            {
                "command": "str_replace",
                "path": args["path"],
                "old_str": args["old_str"],
                "new_str": args.get("new_str", ""),
            }
        )

    def _tool_memory_delete(self, args: dict[str, Any]) -> tuple[str, bool]:
        return self._mem({"command": "delete", "path": args["path"]})

    def _tool_memory_rename(self, args: dict[str, Any]) -> tuple[str, bool]:
        return self._mem(
            {
                "command": "rename",
                "old_path": args["old_path"],
                "new_path": args["new_path"],
            }
        )

    # -- transports ---------------------------------------------------------
    def run_stdio(self) -> None:
        """Serve newline-delimited JSON-RPC on stdin/stdout until EOF."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                _emit(_rpc_error(None, -32700, "Parse error"))
                continue
            response = self.handle_message(msg)
            if response is not None:
                _emit(response)

    def run_http(self, host: str = "127.0.0.1", port: int = 8848) -> None:
        """Serve Streamable HTTP: POSTed JSON-RPC answered with JSON.

        Minimal but spec-compliant for a server that doesn't stream: POST
        /mcp returns application/json (single response) or 202 for
        notifications; GET returns 405 (no server-initiated stream).
        Set $MNEMEX_TOKEN to require `Authorization: Bearer <token>`.
        """
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        server = self
        token = os.environ.get("MNEMEX_TOKEN")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                print(f"[mnemex-mcp] {fmt % args}", file=sys.stderr)

            def _reject(self, code: int, text: str) -> None:
                body = text.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                self._reject(405, "Method Not Allowed (no server-initiated stream)")

            def do_DELETE(self) -> None:  # noqa: N802
                self._reject(405, "Method Not Allowed (stateless server)")

            def do_POST(self) -> None:  # noqa: N802
                if self.path.rstrip("/") not in ("", "/mcp"):
                    return self._reject(404, "Not Found (use /mcp)")
                if token:
                    auth = self.headers.get("Authorization", "")
                    if auth != f"Bearer {token}":
                        return self._reject(401, "Unauthorized")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    msg = json.loads(self.rfile.read(length))
                except (ValueError, json.JSONDecodeError):
                    return self._reject(400, "Bad Request: invalid JSON")
                response = server.handle_message(msg)
                if response is None:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd = ThreadingHTTPServer((host, port), Handler)
        print(
            f"[mnemex-mcp] Streamable HTTP on http://{host}:{port}/mcp"
            + (" (bearer auth on)" if token else ""),
            file=sys.stderr,
        )
        httpd.serve_forever()


def _rpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
