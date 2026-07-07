---
title: Lessons from building mnemex
tags: principle, engineering
source: session 2026-07-07
created: 1783415040
updated: 1783415040
---
1. Verify API specs against live docs before coding; training memory gets tool
   type strings, return strings, and beta headers wrong (memory_20250818,
   clear_tool_uses_20250919, context-management-2025-06-27, MCP 2025-11-25).
2. Aggressive security tests catch real bugs: posixpath.normpath silently
   CLAMPS /../x to /x instead of rejecting it - never rely on normpath for
   sandbox enforcement; reject '..' segments outright.
3. argparse subparser defaults clobber root-parser values; use
   default=argparse.SUPPRESS when re-declaring flags on a subparser.
4. Zaac's preferences: zero-dependency cores, stateless/free-tier friendly,
   git-versioned state, auditable systems, measure twice cut once.
