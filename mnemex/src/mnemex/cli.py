"""Command-line interface for mnemex.

    mnemex init [--git] [DIR]        set up a memory/kb store
    mnemex add   --title T [--tags a,b] [--source S] [FILE]   add a note (FILE or stdin)
    mnemex search QUERY [--tag T] [-k N]                      BM25 search the kb
    mnemex view  /memories/PATH                               view a memory path
    mnemex reindex                                            rebuild the search index
    mnemex stats                                             show store statistics
    mnemex ask   "PROMPT"                                    run the live agent (needs API key)

The store directory defaults to ``./memory`` or ``$MNEMEX_HOME``.
"""

from __future__ import annotations

import argparse
import os
import sys

from .backends import GitSyncBackend, LocalFilesystemBackend
from .knowledge_base import KnowledgeBase
from .memory_tool import MemoryToolHandler


def _store_dir(args: argparse.Namespace) -> str:
    return args.dir or os.environ.get("MNEMEX_HOME", "./memory")


def _backend(args: argparse.Namespace):
    path = _store_dir(args)
    if getattr(args, "git", False) or os.environ.get("MNEMEX_GIT"):
        return GitSyncBackend(path)
    return LocalFilesystemBackend(path)


def _cmd_init(args: argparse.Namespace) -> int:
    backend = _backend(args)
    kb = KnowledgeBase(backend)
    kb.add_note(
        "About this memory store",
        "This is a mnemex memory + knowledge base for Claude.\n"
        "Notes live under /memories/kb as markdown with front-matter.\n"
        "Claude reads/writes via the memory tool and recalls via kb_search.",
        tags=["meta"],
        source="mnemex init",
    )
    print(f"Initialized mnemex store at {_store_dir(args)}")
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    body = sys.stdin.read() if args.file in (None, "-") else open(args.file).read()
    kb = KnowledgeBase(_backend(args))
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    path = kb.add_note(args.title, body, tags=tags, source=args.source or "")
    print(f"Added note: {path}")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    kb = KnowledgeBase(_backend(args))
    hits = kb.search(args.query, k=args.k, tag=args.tag)
    print(kb.format_hits(hits))
    return 0


def _cmd_view(args: argparse.Namespace) -> int:
    handler = MemoryToolHandler(_backend(args))
    result = handler.execute({"command": "view", "path": args.path})
    print(result.content)
    return 1 if result.is_error else 0


def _cmd_reindex(args: argparse.Namespace) -> int:
    kb = KnowledgeBase(_backend(args))
    print(f"Reindexed {kb.reindex()} note(s).")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    backend = _backend(args)
    kb = KnowledgeBase(backend)
    n = kb.reindex()
    handler = MemoryToolHandler(backend)
    listing = handler.execute({"command": "view", "path": "/memories"})
    print(f"Store: {_store_dir(args)}")
    print(f"Knowledge base notes: {n}")
    print("\n" + listing.content)
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import MnemexMCPServer

    server = MnemexMCPServer(_backend(args))
    if args.http:
        server.run_http(host=args.host, port=args.http)
    else:
        server.run_stdio()
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    try:
        from .agent import MemoryAgent
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    agent = MemoryAgent(_backend(args), model=args.model)
    print(agent.run(args.prompt))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mnemex", description=__doc__)
    p.add_argument("--dir", help="store directory (default ./memory or $MNEMEX_HOME)")
    p.add_argument(
        "--git",
        action="store_true",
        help="use a git-synced backend (commit after every write)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="set up a memory/kb store")
    pi.set_defaults(func=_cmd_init)

    pa = sub.add_parser("add", help="add a note (FILE or stdin)")
    pa.add_argument("--title", required=True)
    pa.add_argument("--tags", help="comma-separated tags")
    pa.add_argument("--source", help="provenance for the note")
    pa.add_argument("file", nargs="?", help="file to read (default: stdin)")
    pa.set_defaults(func=_cmd_add)

    ps = sub.add_parser("search", help="BM25 search the knowledge base")
    ps.add_argument("query")
    ps.add_argument("--tag", help="restrict to a tag")
    ps.add_argument("-k", type=int, default=5, help="max results")
    ps.set_defaults(func=_cmd_search)

    pv = sub.add_parser("view", help="view a memory path")
    pv.add_argument("path", help="e.g. /memories or /memories/kb/foo.md")
    pv.set_defaults(func=_cmd_view)

    pr = sub.add_parser("reindex", help="rebuild the search index")
    pr.set_defaults(func=_cmd_reindex)

    pt = sub.add_parser("stats", help="show store statistics")
    pt.set_defaults(func=_cmd_stats)

    pm = sub.add_parser(
        "mcp",
        help="run the MCP server (stdio by default; --http PORT for remote)",
    )
    pm.add_argument("--http", type=int, metavar="PORT",
                    help="serve Streamable HTTP on PORT instead of stdio")
    pm.add_argument("--host", default="127.0.0.1",
                    help="bind address for --http (default 127.0.0.1)")
    # Re-declared here so `mnemex-mcp --dir X --git` works: MCP client
    # configs pass flags flat, after the implicit subcommand. SUPPRESS
    # defaults keep them from clobbering values parsed by the root parser.
    pm.add_argument("--dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    pm.add_argument("--git", action="store_true", default=argparse.SUPPRESS,
                    help=argparse.SUPPRESS)
    pm.set_defaults(func=_cmd_mcp)

    pk = sub.add_parser("ask", help="run the live agent (needs ANTHROPIC_API_KEY)")
    pk.add_argument("prompt")
    pk.add_argument("--model", default="claude-opus-4-8")
    pk.set_defaults(func=_cmd_ask)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


def mcp_main(argv: list[str] | None = None) -> int:
    """Entry point for `mnemex-mcp`: shorthand for `mnemex mcp ...`."""
    return main(["mcp", *(argv if argv is not None else sys.argv[1:])])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
