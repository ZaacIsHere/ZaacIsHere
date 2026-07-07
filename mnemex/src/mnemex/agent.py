"""A minimal agent loop wiring memory + knowledge base + context editing.

This is the "maximal reward" layer: it composes the three current primitives
that compound into cheap, durable, long-running memory:

1. **Memory tool** (``memory_20250818``) -- Claude reads/writes persistent
   files; survives summarization.
2. **kb_search tool** -- just-in-time retrieval over accumulated notes.
3. **Context editing** (``clear_tool_uses_20250919`` + the
   ``context-management-2025-06-27`` beta) -- old tool results are cleared
   server-side as context grows, benchmarked at ~84% token savings on long
   tasks, while memory preserves anything that must outlive the clear.

Only this module needs the ``anthropic`` SDK; the handler and knowledge base
are pure stdlib. Import errors are raised lazily so the rest of the package
works without the SDK installed.
"""

from __future__ import annotations

from typing import Any

from .backends import StorageBackend, LocalFilesystemBackend
from .knowledge_base import KB_SEARCH_TOOL, KnowledgeBase
from .memory_tool import TOOL_SPEC, MemoryToolHandler

_DEFAULT_MODEL = "claude-opus-4-8"
_CONTEXT_BETA = "context-management-2025-06-27"

# Sensible default: start clearing old tool results once input passes ~30k
# tokens, always keeping the 3 most recent tool exchanges. kb_search results
# are excluded from clearing so recall pointers stay live.
_DEFAULT_CONTEXT_EDITS = [
    {
        "type": "clear_tool_uses_20250919",
        "trigger": {"type": "input_tokens", "value": 30000},
        "keep": {"type": "tool_uses", "value": 3},
        "clear_at_least": {"type": "input_tokens", "value": 5000},
        "exclude_tools": ["kb_search"],
    }
]


class MemoryAgent:
    """Runs a tool-use loop with memory, kb_search, and context editing."""

    def __init__(
        self,
        backend: StorageBackend | None = None,
        *,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = 4096,
        client: Any = None,
        context_edits: list[dict[str, Any]] | None = None,
        enable_kb: bool = True,
    ):
        self.backend = backend or LocalFilesystemBackend("./memory")
        self.handler = MemoryToolHandler(self.backend)
        self.kb = KnowledgeBase(self.backend)
        self.model = model
        self.max_tokens = max_tokens
        self.enable_kb = enable_kb
        self.context_edits = (
            context_edits if context_edits is not None else _DEFAULT_CONTEXT_EDITS
        )
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import anthropic  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover
                raise ImportError(
                    "The live agent needs the anthropic SDK: pip install "
                    "'mnemex[agent]' (or: pip install anthropic)."
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    @property
    def tools(self) -> list[dict[str, Any]]:
        tools = [dict(TOOL_SPEC)]
        if self.enable_kb:
            tools.append(KB_SEARCH_TOOL)
        return tools

    def _dispatch_tool(self, block: Any) -> dict[str, Any]:
        name = block.name
        tool_input = dict(block.input)
        if name == "memory":
            return self.handler.execute(tool_input).as_tool_result(block.id)
        if name == "kb_search":
            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": self.kb.execute_search_tool(tool_input),
            }
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": f"Error: unknown tool {name}",
            "is_error": True,
        }

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_iterations: int = 24,
        messages: list[dict[str, Any]] | None = None,
    ) -> str:
        """Run the loop until Claude stops calling tools. Returns final text."""
        convo: list[dict[str, Any]] = list(messages or [])
        convo.append({"role": "user", "content": prompt})

        for _ in range(max_iterations):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": convo,
                "tools": self.tools,
                "betas": [_CONTEXT_BETA],
                "context_management": {"edits": self.context_edits},
            }
            if system:
                kwargs["system"] = system
            message = self.client.beta.messages.create(**kwargs)

            convo.append({"role": "assistant", "content": message.content})
            if message.stop_reason != "tool_use":
                return "".join(
                    b.text for b in message.content if getattr(b, "type", "") == "text"
                )
            results = [
                self._dispatch_tool(b)
                for b in message.content
                if getattr(b, "type", "") == "tool_use"
            ]
            convo.append({"role": "user", "content": results})

        return "[stopped: reached max_iterations without a final answer]"
