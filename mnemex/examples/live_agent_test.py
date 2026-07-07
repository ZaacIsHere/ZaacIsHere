"""Live end-to-end test of the mnemex MemoryAgent against the real API.

Prerequisites:
  pip install -e './mnemex[agent]'
  export ANTHROPIC_API_KEY=sk-ant-...

Run from the repository root:
  python mnemex/examples/live_agent_test.py

Success = the agent prints a coherent reply AND creates
memory/kb/livetest.md. That confirms the real API accepts the memory
tool + kb_search + context-editing payload, which mocks cannot prove.
"""

from __future__ import annotations

import os
import sys

NOTE_PATH = "memory/kb/livetest.md"


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Export it, then re-run.", file=sys.stderr)
        return 1
    if not os.path.isdir("memory"):
        print(
            "No ./memory store here. Run from the repo root (the folder that "
            "contains 'memory/' and 'mnemex/').",
            file=sys.stderr,
        )
        return 1
    try:
        from mnemex import LocalFilesystemBackend, MemoryAgent
    except ImportError as exc:
        print(f"mnemex not installed: {exc}", file=sys.stderr)
        print("Run: pip install -e './mnemex[agent]'", file=sys.stderr)
        return 1

    agent = MemoryAgent(LocalFilesystemBackend("./memory"))
    prompt = (
        "View your memory directory, then search the knowledge base for "
        "'mnemex lessons'. Finally, write a one-line note to "
        "/memories/kb/livetest.md confirming you ran live against the API."
    )
    print("Running the live agent (this makes real API calls)...\n")
    reply = agent.run(prompt)

    print("=== Agent reply ===")
    print(reply)
    print("\n=== " + NOTE_PATH + " ===")
    if os.path.exists(NOTE_PATH):
        with open(NOTE_PATH) as fh:
            print(fh.read())
        print("SUCCESS: full stack verified against the live API.")
        return 0
    print("The agent replied but did not create the note file.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
