"""Tests for the `mnemex outcome` feedback-capture command."""

from __future__ import annotations

from mnemex.backends import LocalFilesystemBackend
from mnemex.cli import main
from mnemex.knowledge_base import KnowledgeBase


def test_outcome_records_searchable_note(tmp_path, capsys):
    store = str(tmp_path / "mem")
    rc = main(
        [
            "--dir", store,
            "outcome",
            "MCP server registered in Claude Code and survives restarts",
            "--verdict", "success",
            "--ref", "PR#1",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Recorded success outcome:" in out

    kb = KnowledgeBase(LocalFilesystemBackend(store))
    hits = kb.search("mcp server restarts", tag="outcome")
    assert hits
    note = kb.load_note(hits[0].path[len("/memories/"):])
    assert "success" in note.tags
    assert "Ref: PR#1" in note.body


def test_outcome_failure_verdict(tmp_path):
    store = str(tmp_path / "mem")
    main(["--dir", store, "outcome", "tunnel dropped mid-show", "--verdict", "failure"])
    kb = KnowledgeBase(LocalFilesystemBackend(store))
    hits = kb.search("tunnel dropped", tag="failure")
    assert hits
