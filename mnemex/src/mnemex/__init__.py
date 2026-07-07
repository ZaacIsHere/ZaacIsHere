"""mnemex -- a memory + knowledge base system for Claude.

Built on three current, compounding primitives:

* Anthropic's memory tool (``memory_20250818``) -- spec-exact, path-safe,
  backend-agnostic client-side handler.
* A just-in-time BM25 knowledge base exposed as the ``kb_search`` tool.
* Server-side context editing (``clear_tool_uses_20250919``) for long runs.

Core (handler + knowledge base + backends) is pure stdlib. Only the live
:class:`MemoryAgent` needs the ``anthropic`` SDK.
"""

from __future__ import annotations

from .backends import (
    Entry,
    GitSyncBackend,
    InMemoryBackend,
    LocalFilesystemBackend,
    StorageBackend,
)
from .knowledge_base import KB_SEARCH_TOOL, KnowledgeBase, Note, SearchHit
from .memory_tool import (
    MEMORY_ROOT,
    TOOL_SPEC,
    TOOL_TYPE,
    MemoryPathError,
    MemoryToolHandler,
    ToolResult,
)

__all__ = [
    "Entry",
    "GitSyncBackend",
    "InMemoryBackend",
    "KB_SEARCH_TOOL",
    "KnowledgeBase",
    "LocalFilesystemBackend",
    "MEMORY_ROOT",
    "MemoryPathError",
    "MemoryToolHandler",
    "Note",
    "SearchHit",
    "StorageBackend",
    "TOOL_SPEC",
    "TOOL_TYPE",
    "ToolResult",
]

try:  # optional: only importable when the anthropic SDK is present
    from .agent import MemoryAgent  # noqa: F401

    __all__.append("MemoryAgent")
except ImportError:  # pragma: no cover
    pass

__version__ = "0.1.0"
