---
title: Cloud env has no secret store; env vars are plaintext-shared
tags: principle, security, infra
source: code.claude.com/docs, session 2026-07-07
created: 1783436407
updated: 1783436407
---
Claude Code on the web (verified 2026-07-07): the environment-variables
field is plaintext and visible to anyone using the environment - NOT a
secret store; there is no dedicated secrets manager. Env changes apply
only to NEW sessions, never the current one.

Consequence: never place a long-lived API key in a cloud env that runs
autonomous routines or processes untrusted content (PR webhooks, web),
because those sessions can read it and injection could exfiltrate it.
Preferred: keep the cloud env key-free; run live API integration tests
locally with a key from a real secret store. If a cloud key is truly
needed, use a dedicated, spend-capped, revocable key and remove it after.

Loop subtlety: MemoryAgent.run passes one convo list by reference and
mutates it in place; to inspect per-call state, snapshot at call time.
