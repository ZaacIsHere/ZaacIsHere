"""Tests for the MCP server: dispatcher logic plus a real stdio round-trip."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from mnemex.backends import InMemoryBackend
from mnemex.knowledge_base import KnowledgeBase
from mnemex.mcp_server import SUPPORTED_PROTOCOL_VERSIONS, MnemexMCPServer


@pytest.fixture
def server():
    backend = InMemoryBackend()
    kb = KnowledgeBase(backend)
    kb.add_note(
        "WHIP ingress",
        "WHIP lets OBS publish WebRTC streams to an ingress endpoint.",
        tags=["webrtc"],
    )
    return MnemexMCPServer(backend)


def _call(server: MnemexMCPServer, method: str, params=None, msg_id=1):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle_message(msg)


def _tool(server: MnemexMCPServer, name: str, arguments: dict):
    resp = _call(server, "tools/call", {"name": name, "arguments": arguments})
    result = resp["result"]
    return result["content"][0]["text"], result.get("isError", False)


def test_initialize_negotiates_known_version(server):
    resp = _call(server, "initialize", {"protocolVersion": "2025-06-18"})
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert resp["result"]["serverInfo"]["name"] == "mnemex"
    assert "tools" in resp["result"]["capabilities"]


def test_initialize_unknown_version_falls_back_to_latest(server):
    resp = _call(server, "initialize", {"protocolVersion": "1999-01-01"})
    assert resp["result"]["protocolVersion"] == SUPPORTED_PROTOCOL_VERSIONS[0]


def test_notification_gets_no_response(server):
    assert (
        server.handle_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        is None
    )


def test_unknown_method_errors(server):
    resp = _call(server, "resources/list")
    assert resp["error"]["code"] == -32601


def test_ping(server):
    assert _call(server, "ping")["result"] == {}


def test_tools_list_shapes(server):
    tools = _call(server, "tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {
        "kb_search",
        "kb_add_note",
        "memory_list",
        "memory_read",
        "memory_write",
        "memory_edit",
        "memory_delete",
        "memory_rename",
    } <= names
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert t["description"]


def test_kb_search_and_add_roundtrip(server):
    text, err = _tool(server, "kb_search", {"query": "obs webrtc publish"})
    assert not err
    assert "/memories/kb/whip-ingress.md" in text

    text, err = _tool(
        server,
        "kb_add_note",
        {"title": "NDI notes", "body": "NDI carries video over IP.", "tags": ["ndi"]},
    )
    assert not err
    assert "Note saved: /memories/kb/ndi-notes.md" in text

    text, _ = _tool(server, "kb_search", {"query": "video over ip", "tag": "ndi"})
    assert "ndi-notes" in text


def test_memory_write_read_edit_delete(server):
    text, err = _tool(
        server, "memory_write", {"path": "/memories/progress.md", "content": "step 1\n"}
    )
    assert not err

    text, err = _tool(server, "memory_read", {"path": "/memories/progress.md"})
    assert not err and "step 1" in text

    text, err = _tool(
        server,
        "memory_edit",
        {"path": "/memories/progress.md", "old_str": "step 1", "new_str": "step 2"},
    )
    assert not err

    text, err = _tool(
        server,
        "memory_rename",
        {"old_path": "/memories/progress.md", "new_path": "/memories/done.md"},
    )
    assert not err

    text, err = _tool(server, "memory_delete", {"path": "/memories/done.md"})
    assert not err
    _, err = _tool(server, "memory_read", {"path": "/memories/done.md"})
    assert err


def test_traversal_surfaces_as_tool_error_not_crash(server):
    text, err = _tool(
        server, "memory_write", {"path": "/memories/../pwn.txt", "content": "x"}
    )
    assert err
    assert "traversal" in text.lower() or "Error" in text


def test_unknown_tool(server):
    text, err = _tool(server, "frobnicate", {})
    assert err and "Unknown tool" in text


def test_stdio_round_trip(tmp_path):
    """Drive the real process over stdin/stdout: initialize -> list -> call."""
    lines = "\n".join(
        json.dumps(m)
        for m in [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "memory_write",
                    "arguments": {"path": "/memories/x.md", "content": "hello\n"},
                },
            },
        ]
    )
    proc = subprocess.run(
        [sys.executable, "-m", "mnemex.cli", "--dir", str(tmp_path / "store"), "mcp"],
        input=lines + "\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    responses = [json.loads(l) for l in proc.stdout.strip().split("\n") if l]
    by_id = {r["id"]: r for r in responses}
    assert by_id[1]["result"]["protocolVersion"] == "2025-11-25"
    assert any(t["name"] == "kb_search" for t in by_id[2]["result"]["tools"])
    assert "successfully" in by_id[3]["result"]["content"][0]["text"]
    # And the write really hit disk.
    assert (tmp_path / "store" / "x.md").read_text() == "hello\n"
