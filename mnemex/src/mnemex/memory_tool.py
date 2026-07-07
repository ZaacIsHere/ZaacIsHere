"""Spec-exact client-side handler for Anthropic's memory tool.

Implements the ``memory_20250818`` tool: the six commands (``view``,
``create``, ``str_replace``, ``insert``, ``delete``, ``rename``), the exact
success / error return strings from the platform docs, and -- most
importantly -- rigorous path-traversal protection. Every path is validated to
live under the ``/memories`` root before it ever reaches a backend.

The handler is deliberately backend-agnostic (see :mod:`mnemex.backends`) so
the same, audited logic runs over disk, memory, or a git-synced store. It has
zero third-party dependencies.

Wire it into any tool-use loop::

    handler = MemoryToolHandler(LocalFilesystemBackend("./memory"))
    result = handler.execute(tool_use_block["input"])   # -> ToolResult
    # send result.content back as a tool_result block (result.is_error too)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .backends import StorageBackend, _human_size

MEMORY_ROOT = "/memories"
TOOL_TYPE = "memory_20250818"
#: The ``tools`` entry to send in the Messages API request.
TOOL_SPEC = {"type": TOOL_TYPE, "name": "memory"}

_MAX_LINES = 999_999
_VIEW_CHAR_LIMIT = 16_000  # Claude's tool description truncates longer views.


class MemoryPathError(ValueError):
    """Raised when a requested path escapes the ``/memories`` sandbox."""


@dataclass
class ToolResult:
    """Result of a memory command, ready to become a ``tool_result`` block."""

    content: str
    is_error: bool = False

    def as_tool_result(self, tool_use_id: str) -> dict[str, Any]:
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": self.content,
        }
        if self.is_error:
            block["is_error"] = True
        return block


def _safe_relpath(path: str) -> str:
    """Validate ``path`` is inside ``/memories`` and return a relative path.

    Rejects traversal (`../`), URL-encoded traversal, backslashes, and any
    path not rooted at ``/memories``. Returns ``""`` for the root itself.
    """
    if not isinstance(path, str) or not path:
        raise MemoryPathError("A path is required.")
    # Normalise obvious encodings / separators before inspection.
    lowered = path.replace("\\", "/")
    if "%2e" in lowered.lower() or "%2f" in lowered.lower():
        raise MemoryPathError(f"Illegal path: {path}")
    if not (lowered == MEMORY_ROOT or lowered.startswith(MEMORY_ROOT + "/")):
        raise MemoryPathError(
            f"Path must be within {MEMORY_ROOT}. Got: {path}"
        )
    rel = lowered[len(MEMORY_ROOT):].lstrip("/")
    # Reject any ".." segment outright. Do NOT rely on normpath here: it
    # silently *clamps* "/../x" to "/x", which would let a traversal collapse
    # into the sandbox instead of being refused.
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise MemoryPathError(f"Path traversal detected: {path}")
    return "/".join(parts)


def _number_lines(text: str, start: int = 1) -> str:
    lines = text.split("\n")
    # A trailing newline yields a spurious empty final element; drop it so the
    # numbering matches the file's real line count.
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return "\n".join(
        f"{i:6d}\t{line}" for i, line in enumerate(lines[: ], start=start)
    )


class MemoryToolHandler:
    """Executes memory tool commands against a :class:`StorageBackend`."""

    def __init__(self, backend: StorageBackend):
        self.backend = backend

    # -- public API -----------------------------------------------------
    def execute(self, command_input: dict[str, Any]) -> ToolResult:
        """Dispatch one memory command. Never raises for expected errors."""
        command = command_input.get("command")
        try:
            handler = getattr(self, f"_cmd_{command}", None)
            if handler is None:
                return ToolResult(f"Error: unknown command {command}", is_error=True)
            return handler(command_input)
        except MemoryPathError as exc:
            return ToolResult(f"Error: {exc}", is_error=True)
        except FileNotFoundError:
            path = command_input.get("path", "")
            return ToolResult(
                f"The path {path} does not exist. Please provide a valid path.",
                is_error=True,
            )

    # -- commands -------------------------------------------------------
    def _cmd_view(self, inp: dict[str, Any]) -> ToolResult:
        path = inp["path"]
        rel = _safe_relpath(path)
        if not self.backend.exists(rel):
            return ToolResult(
                f"The path {path} does not exist. Please provide a valid path.",
                is_error=True,
            )
        if self.backend.is_dir(rel):
            return ToolResult(self._render_dir(path, rel))

        if path.lower().endswith((".jpg", ".jpeg", ".png")):
            return ToolResult(
                f"[image file {path}, {_human_size(self.backend.size(rel))}]"
            )

        text = self.backend.read_text(rel)
        if text.count("\n") + 1 > _MAX_LINES:
            return ToolResult(
                f"File {path} exceeds maximum line limit of {_MAX_LINES:,} lines.",
                is_error=True,
            )

        view_range = inp.get("view_range")
        if view_range:
            start, end = view_range
            lines = text.split("\n")
            if lines and lines[-1] == "":
                lines = lines[:-1]
            end = len(lines) if end == -1 else end
            selected = "\n".join(lines[start - 1 : end])
            body = _number_lines(selected + "\n", start=start)
        else:
            truncated = text[:_VIEW_CHAR_LIMIT]
            body = _number_lines(truncated)
            if len(text) > _VIEW_CHAR_LIMIT:
                body += "\n... [truncated; use view_range to see more]"
        return ToolResult(f"Here's the content of {path} with line numbers:\n{body}")

    def _render_dir(self, display_path: str, rel: str) -> str:
        header = (
            f"Here're the files and directories up to 2 levels deep in "
            f"{display_path}, excluding hidden items and node_modules:"
        )
        rows = []
        for entry in self.backend.walk(rel, max_depth=2):
            disp = MEMORY_ROOT if entry.path == "" else f"{MEMORY_ROOT}/{entry.path}"
            size = "0" if entry.is_dir else _human_size(entry.size)
            rows.append(f"{size}\t{disp}")
        return header + "\n" + "\n".join(rows)

    def _cmd_create(self, inp: dict[str, Any]) -> ToolResult:
        path = inp["path"]
        rel = _safe_relpath(path)
        if rel == "":
            return ToolResult("Error: cannot create the memory root", is_error=True)
        # The tool description says create "creates or overwrites"; we overwrite
        # so Claude is never wedged by a pre-existing file.
        self.backend.write_text(rel, inp.get("file_text", ""))
        return ToolResult(f"File created successfully at: {path}")

    def _cmd_str_replace(self, inp: dict[str, Any]) -> ToolResult:
        path = inp["path"]
        rel = _safe_relpath(path)
        if not self.backend.exists(rel) or self.backend.is_dir(rel):
            return ToolResult(
                f"Error: The path {path} does not exist. Please provide a valid path.",
                is_error=True,
            )
        old_str = inp["old_str"]
        new_str = inp.get("new_str", "")
        text = self.backend.read_text(rel)
        count = text.count(old_str)
        if count == 0:
            return ToolResult(
                f"No replacement was performed, old_str `{old_str}` "
                f"did not appear verbatim in {path}.",
                is_error=True,
            )
        if count > 1:
            line_nos = [
                str(i + 1)
                for i, line in enumerate(text.split("\n"))
                if old_str in line
            ]
            return ToolResult(
                f"No replacement was performed. Multiple occurrences of old_str "
                f"`{old_str}` in lines: {', '.join(line_nos)}. "
                f"Please ensure it is unique",
                is_error=True,
            )
        updated = text.replace(old_str, new_str, 1)
        self.backend.write_text(rel, updated)
        # Return a small snippet around the edit, with line numbers.
        idx = updated.find(new_str)
        start_line = updated.count("\n", 0, idx)
        snippet_lines = updated.split("\n")
        lo = max(0, start_line - 2)
        hi = min(len(snippet_lines), start_line + new_str.count("\n") + 3)
        snippet = _number_lines("\n".join(snippet_lines[lo:hi]) + "\n", start=lo + 1)
        return ToolResult(f"The memory file has been edited.\n{snippet}")

    def _cmd_insert(self, inp: dict[str, Any]) -> ToolResult:
        path = inp["path"]
        rel = _safe_relpath(path)
        if not self.backend.exists(rel) or self.backend.is_dir(rel):
            return ToolResult(f"Error: The path {path} does not exist", is_error=True)
        insert_line = inp["insert_line"]
        text = self.backend.read_text(rel)
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        if insert_line < 0 or insert_line > len(lines):
            return ToolResult(
                f"Error: Invalid `insert_line` parameter: {insert_line}. "
                f"It should be within the range of lines of the file: "
                f"[0, {len(lines)}]",
                is_error=True,
            )
        insert_text = inp.get("insert_text", "").rstrip("\n")
        lines.insert(insert_line, insert_text)
        self.backend.write_text(rel, "\n".join(lines) + "\n")
        return ToolResult(f"The file {path} has been edited.")

    def _cmd_delete(self, inp: dict[str, Any]) -> ToolResult:
        path = inp["path"]
        rel = _safe_relpath(path)
        if rel == "":
            return ToolResult(
                "Error: cannot delete the /memories directory itself", is_error=True
            )
        if not self.backend.exists(rel):
            return ToolResult(f"Error: The path {path} does not exist", is_error=True)
        self.backend.delete(rel)
        return ToolResult(f"Successfully deleted {path}")

    def _cmd_rename(self, inp: dict[str, Any]) -> ToolResult:
        old_path = inp["old_path"]
        new_path = inp["new_path"]
        old_rel = _safe_relpath(old_path)
        new_rel = _safe_relpath(new_path)
        if old_rel == "":
            return ToolResult(
                "Error: cannot rename the /memories directory itself", is_error=True
            )
        if not self.backend.exists(old_rel):
            return ToolResult(
                f"Error: The path {old_path} does not exist", is_error=True
            )
        if self.backend.exists(new_rel):
            return ToolResult(
                f"Error: The destination {new_path} already exists", is_error=True
            )
        self.backend.rename(old_rel, new_rel)
        return ToolResult(f"Successfully renamed {old_path} to {new_path}")


_WORD_RE = re.compile(r"\w+")  # re-exported for the KB tokenizer
