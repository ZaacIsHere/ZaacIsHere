"""Path-traversal protection is security-critical: test it hard."""

from __future__ import annotations

import os

import pytest

from mnemex.backends import LocalFilesystemBackend
from mnemex.memory_tool import MemoryPathError, MemoryToolHandler, _safe_relpath


@pytest.mark.parametrize(
    "bad",
    [
        "/memories/../secrets.env",
        "/memories/../../etc/passwd",
        "/etc/passwd",
        "/memories/a/../../b",
        "/memories/..",
        "memories/foo",           # missing leading slash / not rooted
        "/Memories/foo",          # wrong root (case-sensitive)
        "/memories/%2e%2e/x",     # url-encoded traversal
        "/memories/..%2f..%2fx",
        "..\\..\\windows",
        "",
    ],
)
def test_rejects_traversal(bad):
    with pytest.raises(MemoryPathError):
        _safe_relpath(bad)


@pytest.mark.parametrize(
    "good,expected",
    [
        ("/memories", ""),
        ("/memories/notes.txt", "notes.txt"),
        ("/memories/kb/foo.md", "kb/foo.md"),
        ("/memories/a/b/c.txt", "a/b/c.txt"),
    ],
)
def test_accepts_valid(good, expected):
    assert _safe_relpath(good) == expected


def test_handler_blocks_escape_and_file_stays_put(tmp_path):
    """A traversal create must not write outside the store root."""
    root = tmp_path / "mem"
    handler = MemoryToolHandler(LocalFilesystemBackend(str(root)))
    secret = tmp_path / "secret.txt"
    res = handler.execute(
        {
            "command": "create",
            "path": "/memories/../secret.txt",
            "file_text": "PWNED",
        }
    )
    assert res.is_error
    assert not secret.exists()
    # Nothing named secret.txt should exist anywhere under the store root.
    leaked = [
        os.path.join(d, f)
        for d, _, files in os.walk(str(root))
        for f in files
        if f == "secret.txt"
    ]
    assert leaked == []
