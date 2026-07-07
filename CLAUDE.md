# Persistent memory protocol

This repository carries a live, git-versioned memory and knowledge store for
Claude at `./memory` (notes under `memory/kb/`, maintained by the `mnemex`
toolkit in `./mnemex`).

**At the start of any task here:**

1. Search the store for relevant prior knowledge before re-deriving anything:
   `pip install -e ./mnemex && mnemex --dir memory search "<topic>"`
2. Read `memory/kb/curation-protocol.md` if you plan to modify the store.
3. Notes tagged `principle` are distilled lessons — treat them as standing
   guidance. Notes tagged `outcome` are ground-truth feedback on past work.

**Before ending a session that produced durable knowledge:**

- Record lessons: `mnemex --dir memory add --title "..." --tags <topic>`
- Record results of past work when observed:
  `mnemex --dir memory outcome "<what happened>" --verdict success|failure|partial --ref <PR/commit>`
- Commit `memory/` changes with message `memory: <summary>` and push.

Keep the store coherent: update or merge existing notes rather than creating
near-duplicates. A weekly curation routine distills and prunes the store; the
log of every pass is `memory/kb/curation-log.md`.
