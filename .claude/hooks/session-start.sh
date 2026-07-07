#!/bin/bash
set -euo pipefail

# Only needed in Claude Code on the web containers.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# mnemex CLI + test runner; idempotent, and the container cache keeps
# subsequent sessions fast.
pip install --quiet -e ./mnemex pytest

# Surface the memory store into session context so every session starts
# with recall (stdout of a sync SessionStart hook is added to context).
echo "=== mnemex memory store (search with: mnemex --dir memory search '<topic>') ==="
mnemex --dir memory stats || true
