"""Tests for the BM25 knowledge base and the kb_search tool."""

from __future__ import annotations

from mnemex.backends import InMemoryBackend
from mnemex.knowledge_base import KnowledgeBase


def _seed(kb: KnowledgeBase) -> None:
    kb.add_note(
        "WebRTC WHIP ingress for OBS",
        "WHIP is a signaling protocol for ingesting WebRTC streams. OBS can "
        "publish to a WHIP endpoint for low-latency broadcast ingress.",
        tags=["webrtc", "broadcast"],
    )
    kb.add_note(
        "Reed-Solomon erasure coding",
        "Erasure coding splits data into shards with parity so files survive "
        "the loss of some shards. Used in federated storage like EchoMesh.",
        tags=["storage", "distributed"],
    )
    kb.add_note(
        "NDI bridging notes",
        "NDI carries video over IP on the local network. Bridge NDI to WebRTC "
        "for remote multiview dashboards.",
        tags=["broadcast", "ndi"],
    )


def test_add_and_search_ranks_relevant_first():
    kb = KnowledgeBase(InMemoryBackend())
    _seed(kb)
    hits = kb.search("webrtc whip obs ingress")
    assert hits
    assert "whip" in hits[0].path.lower() or "WHIP" in hits[0].title
    assert hits[0].score >= hits[-1].score  # sorted descending


def test_search_tag_filter():
    kb = KnowledgeBase(InMemoryBackend())
    _seed(kb)
    hits = kb.search("storage shards", tag="storage")
    assert hits
    assert all("storage" in h.tags for h in hits)


def test_search_no_results():
    kb = KnowledgeBase(InMemoryBackend())
    _seed(kb)
    assert kb.search("quantum chromodynamics unicorn") == []
    assert "No matching notes" in kb.format_hits([])


def test_note_roundtrip_preserves_frontmatter():
    backend = InMemoryBackend()
    kb = KnowledgeBase(backend)
    path = kb.add_note("Title Here", "Body text.", tags=["a", "b"], source="unit-test")
    rel = path[len("/memories/"):]
    note = kb.load_note(rel)
    assert note is not None
    assert note.title == "Title Here"
    assert note.tags == ["a", "b"]
    assert note.source == "unit-test"
    assert "Body text." in note.body


def test_reindex_counts_notes():
    kb = KnowledgeBase(InMemoryBackend())
    _seed(kb)
    assert kb.reindex() == 3


def test_execute_search_tool_returns_pointer_string():
    kb = KnowledgeBase(InMemoryBackend())
    _seed(kb)
    out = kb.execute_search_tool({"query": "NDI video over IP", "k": 2})
    assert "/memories/kb/" in out
    assert "view" in out  # instructs Claude to read the file


def test_update_note_preserves_created():
    backend = InMemoryBackend()
    kb = KnowledgeBase(backend)
    p1 = kb.add_note("Same Title", "v1", tags=["x"])
    rel = p1[len("/memories/"):]
    created1 = kb.load_note(rel).created
    kb.add_note("Same Title", "v2 updated body", tags=["x"])
    note = kb.load_note(rel)
    assert note.created == created1
    assert "v2 updated body" in note.body
