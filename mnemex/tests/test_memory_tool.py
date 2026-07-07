"""Tests for the spec-exact memory tool handler."""

from __future__ import annotations

import pytest

from mnemex.backends import InMemoryBackend, LocalFilesystemBackend
from mnemex.memory_tool import MemoryToolHandler


@pytest.fixture(params=["memory", "disk"])
def handler(request, tmp_path):
    backend = (
        InMemoryBackend()
        if request.param == "memory"
        else LocalFilesystemBackend(str(tmp_path / "mem"))
    )
    return MemoryToolHandler(backend)


def test_view_empty_root(handler):
    res = handler.execute({"command": "view", "path": "/memories"})
    assert not res.is_error
    assert res.content.startswith("Here're the files and directories")
    assert "/memories" in res.content


def test_create_and_view_file(handler):
    res = handler.execute(
        {"command": "create", "path": "/memories/notes.txt", "file_text": "hello\nworld\n"}
    )
    assert res.content == "File created successfully at: /memories/notes.txt"

    res = handler.execute({"command": "view", "path": "/memories/notes.txt"})
    assert "Here's the content of /memories/notes.txt with line numbers:" in res.content
    assert "     1\thello" in res.content
    assert "     2\tworld" in res.content


def test_view_missing_file(handler):
    res = handler.execute({"command": "view", "path": "/memories/nope.txt"})
    assert res.is_error
    assert res.content == (
        "The path /memories/nope.txt does not exist. Please provide a valid path."
    )


def test_view_range(handler):
    handler.execute(
        {"command": "create", "path": "/memories/a.txt", "file_text": "l1\nl2\nl3\nl4\n"}
    )
    res = handler.execute(
        {"command": "view", "path": "/memories/a.txt", "view_range": [2, 3]}
    )
    assert "     2\tl2" in res.content
    assert "     3\tl3" in res.content
    assert "l1" not in res.content.split("line numbers:")[1]
    assert "l4" not in res.content


def test_str_replace_success(handler):
    handler.execute(
        {"command": "create", "path": "/memories/p.txt", "file_text": "color: blue\n"}
    )
    res = handler.execute(
        {
            "command": "str_replace",
            "path": "/memories/p.txt",
            "old_str": "color: blue",
            "new_str": "color: green",
        }
    )
    assert res.content.startswith("The memory file has been edited.")
    view = handler.execute({"command": "view", "path": "/memories/p.txt"})
    assert "color: green" in view.content


def test_str_replace_not_found(handler):
    handler.execute(
        {"command": "create", "path": "/memories/p.txt", "file_text": "abc\n"}
    )
    res = handler.execute(
        {"command": "str_replace", "path": "/memories/p.txt", "old_str": "xyz", "new_str": "q"}
    )
    assert res.is_error
    assert "did not appear verbatim" in res.content


def test_str_replace_multiple(handler):
    handler.execute(
        {"command": "create", "path": "/memories/p.txt", "file_text": "dup\ndup\n"}
    )
    res = handler.execute(
        {"command": "str_replace", "path": "/memories/p.txt", "old_str": "dup", "new_str": "x"}
    )
    assert res.is_error
    assert "Multiple occurrences" in res.content
    assert "lines: 1, 2" in res.content


def test_insert(handler):
    handler.execute(
        {"command": "create", "path": "/memories/t.txt", "file_text": "a\nb\n"}
    )
    res = handler.execute(
        {"command": "insert", "path": "/memories/t.txt", "insert_line": 1, "insert_text": "X\n"}
    )
    assert res.content == "The file /memories/t.txt has been edited."
    view = handler.execute({"command": "view", "path": "/memories/t.txt"})
    assert "     1\ta" in view.content
    assert "     2\tX" in view.content
    assert "     3\tb" in view.content


def test_insert_invalid_line(handler):
    handler.execute(
        {"command": "create", "path": "/memories/t.txt", "file_text": "a\n"}
    )
    res = handler.execute(
        {"command": "insert", "path": "/memories/t.txt", "insert_line": 9, "insert_text": "z"}
    )
    assert res.is_error
    assert "Invalid `insert_line`" in res.content


def test_delete(handler):
    handler.execute(
        {"command": "create", "path": "/memories/gone.txt", "file_text": "x"}
    )
    res = handler.execute({"command": "delete", "path": "/memories/gone.txt"})
    assert res.content == "Successfully deleted /memories/gone.txt"
    assert handler.execute({"command": "view", "path": "/memories/gone.txt"}).is_error


def test_delete_missing(handler):
    res = handler.execute({"command": "delete", "path": "/memories/nope.txt"})
    assert res.is_error
    assert res.content == "Error: The path /memories/nope.txt does not exist"


def test_cannot_delete_root(handler):
    res = handler.execute({"command": "delete", "path": "/memories"})
    assert res.is_error


def test_rename(handler):
    handler.execute(
        {"command": "create", "path": "/memories/draft.txt", "file_text": "x"}
    )
    res = handler.execute(
        {"command": "rename", "old_path": "/memories/draft.txt", "new_path": "/memories/final.txt"}
    )
    assert res.content == "Successfully renamed /memories/draft.txt to /memories/final.txt"
    assert not handler.execute({"command": "view", "path": "/memories/final.txt"}).is_error


def test_rename_dest_exists(handler):
    handler.execute({"command": "create", "path": "/memories/a.txt", "file_text": "1"})
    handler.execute({"command": "create", "path": "/memories/b.txt", "file_text": "2"})
    res = handler.execute(
        {"command": "rename", "old_path": "/memories/a.txt", "new_path": "/memories/b.txt"}
    )
    assert res.is_error
    assert "already exists" in res.content


def test_unknown_command(handler):
    res = handler.execute({"command": "frobnicate", "path": "/memories"})
    assert res.is_error
    assert "unknown command" in res.content


def test_nested_directory_listing(handler):
    handler.execute(
        {"command": "create", "path": "/memories/kb/sub/deep.md", "file_text": "hi"}
    )
    res = handler.execute({"command": "view", "path": "/memories"})
    assert "/memories/kb" in res.content
