"""Verify the MemoryAgent tool-use loop with a mock client (no API key).

This exercises everything except the actual HTTP round-trip: payload shape
(tools, betas, context_management), tool dispatch into the memory handler and
knowledge base, feeding tool_results back, and the termination conditions.
"""

from __future__ import annotations

from mnemex.agent import MemoryAgent
from mnemex.backends import InMemoryBackend
from mnemex.knowledge_base import KnowledgeBase


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Msg:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, script):
        self._script = script
        self.calls: list[dict] = []

    def create(self, **kwargs):
        # Snapshot messages: the agent passes and mutates one list by
        # reference, so the raw kwargs would show only the final state.
        snap = dict(kwargs)
        snap["messages"] = list(kwargs["messages"])
        self.calls.append(snap)
        return self._script[len(self.calls) - 1]


class _FakeClient:
    """Stands in for anthropic.Anthropic(); returns scripted messages."""

    def __init__(self, script):
        self.beta = type("B", (), {"messages": _FakeMessages(script)})()


def _seeded_backend() -> InMemoryBackend:
    backend = InMemoryBackend()
    kb = KnowledgeBase(backend)
    kb.add_note("WHIP ingress", "OBS publishes WebRTC via a WHIP endpoint.", tags=["webrtc"])
    return backend


def test_loop_dispatches_tools_then_returns_final_text():
    backend = _seeded_backend()
    turn1 = _Msg(
        [
            _Block(type="tool_use", id="t1", name="memory",
                   input={"command": "view", "path": "/memories"}),
            _Block(type="tool_use", id="t2", name="kb_search",
                   input={"query": "webrtc whip"}),
        ],
        stop_reason="tool_use",
    )
    turn2 = _Msg([_Block(type="text", text="All set.")], stop_reason="end_turn")
    client = _FakeClient([turn1, turn2])

    agent = MemoryAgent(backend, client=client)
    result = agent.run("Check memory and recall webrtc notes, then confirm.")

    assert result == "All set."
    calls = client.beta.messages.calls
    assert len(calls) == 2  # tool turn + final turn

    # --- payload shape on the first request ---
    first = calls[0]
    assert any(t.get("type") == "memory_20250818" for t in first["tools"])
    assert any(t.get("name") == "kb_search" for t in first["tools"])
    assert first["betas"] == ["context-management-2025-06-27"]
    assert first["context_management"]["edits"][0]["type"] == "clear_tool_uses_20250919"

    # --- tool results were dispatched and fed back on the second request ---
    fed_back = calls[1]["messages"][-1]["content"]
    by_id = {r["tool_use_id"]: r["content"] for r in fed_back}
    assert "/memories" in by_id["t1"]                       # memory view ran
    assert "/memories/kb/whip-ingress.md" in by_id["t2"]    # kb_search ran


def test_loop_respects_max_iterations():
    backend = _seeded_backend()
    # Always asks for a tool: never terminates on its own.
    forever = _Msg(
        [_Block(type="tool_use", id="x", name="memory",
                input={"command": "view", "path": "/memories"})],
        stop_reason="tool_use",
    )
    client = _FakeClient([forever] * 10)
    agent = MemoryAgent(backend, client=client)
    out = agent.run("loop", max_iterations=3)
    assert "max_iterations" in out
    assert len(client.beta.messages.calls) == 3


def test_unknown_tool_surfaces_error_but_keeps_going():
    backend = _seeded_backend()
    turn1 = _Msg(
        [_Block(type="tool_use", id="t1", name="bogus", input={})],
        stop_reason="tool_use",
    )
    turn2 = _Msg([_Block(type="text", text="recovered")], stop_reason="end_turn")
    client = _FakeClient([turn1, turn2])
    agent = MemoryAgent(backend, client=client)
    assert agent.run("call a bad tool") == "recovered"
    fed_back = client.beta.messages.calls[1]["messages"][-1]["content"]
    assert fed_back[0]["is_error"] is True
    assert "unknown tool" in fed_back[0]["content"].lower()
