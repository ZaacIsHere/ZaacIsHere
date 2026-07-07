"""A just-in-time knowledge base layered over the memory tree.

The design follows the current "just-in-time context retrieval" pattern: the
agent does *not* front-load the whole knowledge base into context. Instead it
calls :meth:`KnowledgeBase.search` (exposed to Claude as the ``kb_search``
tool) to get a ranked list of pointers + snippets, then ``view``s only the
files it actually needs via the memory tool.

Retrieval is a self-contained BM25 index -- no embeddings model, no vector DB,
no network, no third-party dependencies. That keeps it cheap enough to run on
a free-tier / stateless worker while still giving genuinely useful ranking.
Notes are plain markdown with a lightweight ``---`` front-matter block, so the
store stays human- and git-friendly.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .backends import StorageBackend

KB_DIR = "kb"  # relative to the memory root -> /memories/kb
_INDEX_PATH = ".kb_index.json"
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by for from has he in is it its of on that the to "
    "was were will with this these those i you we they but or not".split()
)

# kb_search tool definition for the Messages API.
KB_SEARCH_TOOL = {
    "name": "kb_search",
    "description": (
        "Search your persistent knowledge base for notes relevant to a query. "
        "Returns ranked file paths under /memories/kb with short snippets. "
        "Use this to recall what you already know BEFORE re-deriving it, then "
        "read the most relevant files with the memory tool's `view` command."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for."},
            "k": {
                "type": "integer",
                "description": "Max results to return (default 5).",
            },
            "tag": {
                "type": "string",
                "description": "Optional: restrict results to notes with this tag.",
            },
        },
        "required": ["query"],
    },
}


def _tokenize(text: str) -> list[str]:
    return [
        t for t in _WORD_RE.findall(text.lower())
        if t not in _STOPWORDS and len(t) > 1
    ]


@dataclass
class Note:
    path: str          # relative to memory root, e.g. "kb/foo.md"
    title: str
    tags: list[str]
    body: str
    created: float
    updated: float
    source: str = ""


@dataclass
class SearchHit:
    path: str          # absolute memory path, e.g. "/memories/kb/foo.md"
    title: str
    tags: list[str]
    score: float
    snippet: str


@dataclass
class _IndexState:
    # term -> {doc_path: term_freq}
    postings: dict[str, dict[str, int]] = field(default_factory=dict)
    doc_len: dict[str, int] = field(default_factory=dict)
    meta: dict[str, dict[str, Any]] = field(default_factory=dict)  # path -> note meta


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or f"note-{int(time.time())}"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse a minimal ``---`` front-matter block. Returns (meta, body)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta, text[end + 5 :]


def _render_note(note: Note) -> str:
    tags = ", ".join(note.tags)
    return (
        "---\n"
        f"title: {note.title}\n"
        f"tags: {tags}\n"
        f"source: {note.source}\n"
        f"created: {note.created:.0f}\n"
        f"updated: {note.updated:.0f}\n"
        "---\n"
        f"{note.body.rstrip()}\n"
    )


class KnowledgeBase:
    """BM25-ranked, git-friendly knowledge base over a storage backend."""

    K1 = 1.5
    B = 0.75

    def __init__(self, backend: StorageBackend):
        self.backend = backend
        self._index: _IndexState | None = None

    # -- writing --------------------------------------------------------
    def add_note(
        self,
        title: str,
        body: str,
        *,
        tags: list[str] | None = None,
        source: str = "",
        path: str | None = None,
    ) -> str:
        """Create or overwrite a note. Returns its absolute memory path."""
        now = time.time()
        rel = path or f"{KB_DIR}/{_slugify(title)}.md"
        if not rel.startswith(KB_DIR + "/"):
            rel = f"{KB_DIR}/{rel}"
        created = now
        if self.backend.exists(rel):
            existing_meta, _ = _parse_frontmatter(self.backend.read_text(rel))
            created = float(existing_meta.get("created", now))
        note = Note(
            path=rel,
            title=title,
            tags=tags or [],
            body=body,
            created=created,
            updated=now,
            source=source,
        )
        self.backend.write_text(rel, _render_note(note))
        self._index = None  # invalidate; rebuilt lazily on next search
        return f"/memories/{rel}"

    def load_note(self, rel_path: str) -> Note | None:
        if not self.backend.exists(rel_path):
            return None
        meta, body = _parse_frontmatter(self.backend.read_text(rel_path))
        tags = [t.strip() for t in meta.get("tags", "").split(",") if t.strip()]
        return Note(
            path=rel_path,
            title=meta.get("title", rel_path),
            tags=tags,
            body=body,
            created=float(meta.get("created", 0) or 0),
            updated=float(meta.get("updated", 0) or 0),
            source=meta.get("source", ""),
        )

    # -- indexing -------------------------------------------------------
    def _all_note_paths(self) -> list[str]:
        if not self.backend.exists(KB_DIR):
            return []
        return [
            e.path
            for e in self.backend.walk(KB_DIR, max_depth=2)
            if not e.is_dir and e.path.endswith(".md")
        ]

    def _build_index(self) -> _IndexState:
        state = _IndexState()
        for rel in self._all_note_paths():
            note = self.load_note(rel)
            if note is None:
                continue
            # Weight the title by repeating it -- cheap field boosting.
            tokens = _tokenize(note.title) * 3 + _tokenize(" ".join(note.tags)) * 2
            tokens += _tokenize(note.body)
            state.doc_len[rel] = len(tokens)
            counts: dict[str, int] = {}
            for tok in tokens:
                counts[tok] = counts.get(tok, 0) + 1
            for tok, tf in counts.items():
                state.postings.setdefault(tok, {})[rel] = tf
            state.meta[rel] = {
                "title": note.title,
                "tags": note.tags,
                "body": note.body,
            }
        self._persist_index(state)
        return state

    def _persist_index(self, state: _IndexState) -> None:
        try:
            self.backend.write_text(
                _INDEX_PATH,
                json.dumps(
                    {
                        "postings": state.postings,
                        "doc_len": state.doc_len,
                        "meta": {
                            p: {"title": m["title"], "tags": m["tags"]}
                            for p, m in state.meta.items()
                        },
                    }
                ),
            )
        except Exception:  # pragma: no cover - index cache is best-effort
            pass

    def _ensure_index(self) -> _IndexState:
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def reindex(self) -> int:
        """Force a full rebuild. Returns the number of indexed notes."""
        self._index = self._build_index()
        return len(self._index.doc_len)

    # -- reading --------------------------------------------------------
    def search(self, query: str, k: int = 5, tag: str | None = None) -> list[SearchHit]:
        state = self._ensure_index()
        n_docs = len(state.doc_len)
        if n_docs == 0:
            return []
        avg_len = sum(state.doc_len.values()) / n_docs
        q_terms = _tokenize(query)
        scores: dict[str, float] = {}
        for term in q_terms:
            postings = state.postings.get(term)
            if not postings:
                continue
            df = len(postings)
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for doc, tf in postings.items():
                denom = tf + self.K1 * (
                    1 - self.B + self.B * state.doc_len[doc] / avg_len
                )
                scores[doc] = scores.get(doc, 0.0) + idf * (tf * (self.K1 + 1)) / denom

        hits: list[SearchHit] = []
        for doc, score in sorted(scores.items(), key=lambda kv: -kv[1]):
            meta = state.meta.get(doc, {})
            if tag and tag not in meta.get("tags", []):
                continue
            note = self.load_note(doc)
            if note is None:
                continue
            hits.append(
                SearchHit(
                    path=f"/memories/{doc}",
                    title=note.title,
                    tags=note.tags,
                    score=round(score, 4),
                    snippet=self._snippet(note.body, q_terms),
                )
            )
            if len(hits) >= k:
                break
        return hits

    @staticmethod
    def _snippet(body: str, q_terms: list[str], width: int = 200) -> str:
        flat = " ".join(body.split())
        low = flat.lower()
        pos = -1
        for term in q_terms:
            pos = low.find(term)
            if pos != -1:
                break
        if pos == -1:
            return flat[:width] + ("..." if len(flat) > width else "")
        start = max(0, pos - width // 3)
        end = min(len(flat), start + width)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(flat) else ""
        return f"{prefix}{flat[start:end]}{suffix}"

    def format_hits(self, hits: list[SearchHit]) -> str:
        """Render hits as the ``kb_search`` tool_result string for Claude."""
        if not hits:
            return "No matching notes found in the knowledge base."
        lines = [f"Found {len(hits)} relevant note(s):"]
        for i, h in enumerate(hits, 1):
            tags = f" [tags: {', '.join(h.tags)}]" if h.tags else ""
            lines.append(
                f"{i}. {h.path} (score {h.score}){tags}\n"
                f"   {h.title}\n"
                f"   {h.snippet}"
            )
        lines.append(
            "\nUse the memory tool's `view` command to read the full text of any "
            "path above."
        )
        return "\n".join(lines)

    def execute_search_tool(self, tool_input: dict[str, Any]) -> str:
        hits = self.search(
            tool_input["query"],
            k=int(tool_input.get("k", 5)),
            tag=tool_input.get("tag"),
        )
        return self.format_hits(hits)
