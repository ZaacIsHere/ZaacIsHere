"""Offline demo of mnemex -- no API key required.

Shows the memory tool handler and the just-in-time knowledge base working
together over an in-memory backend, exactly as they would inside the agent
loop. Run: ``python examples/demo.py``
"""

from __future__ import annotations

from mnemex import InMemoryBackend, KnowledgeBase, MemoryToolHandler


def main() -> None:
    backend = InMemoryBackend()
    handler = MemoryToolHandler(backend)
    kb = KnowledgeBase(backend)

    print("== Seeding the knowledge base ==")
    for title, body, tags in [
        (
            "Zero-drift stage timing",
            "ProStage Timer keeps show callers in sync using Socket.io plus a "
            "monotonic clock offset handshake so every downstage monitor agrees "
            "on the current cue to the millisecond.",
            ["broadcast", "timing"],
        ),
        (
            "rclone union for federated storage",
            "Cloud Mesh Kit fuses Nextcloud, Dropbox and SMB tiers into one "
            "logical volume with rclone union, spreading writes across free "
            "tiers.",
            ["storage", "edge"],
        ),
    ]:
        print("  +", kb.add_note(title, body, tags=tags))

    print("\n== Claude checks its memory directory (view /memories) ==")
    print(handler.execute({"command": "view", "path": "/memories"}).content)

    print("\n== Claude recalls knowledge (kb_search) ==")
    print(kb.execute_search_tool({"query": "how do we keep show timers in sync?"}))

    print("\n== Claude writes a progress note (memory create) ==")
    print(
        handler.execute(
            {
                "command": "create",
                "path": "/memories/progress.md",
                "file_text": "# Progress\n- [x] Seeded KB\n- [ ] Wire into live agent\n",
            }
        ).content
    )

    print("\n== A later session reads it back ==")
    print(handler.execute({"command": "view", "path": "/memories/progress.md"}).content)


if __name__ == "__main__":
    main()
