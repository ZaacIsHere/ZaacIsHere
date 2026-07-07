"""Storage backends for the memory tree.

Every backend presents the same tiny filesystem-like surface that the memory
tool handler needs. Paths handed to a backend are always *relative* POSIX
paths (never absolute, never containing ``..``) -- the handler is responsible
for validating and stripping the ``/memories`` prefix before it gets here, so
backends can stay dumb and portable.

Three backends ship in the box:

* :class:`LocalFilesystemBackend` -- the default; a directory on disk.
* :class:`InMemoryBackend`        -- ephemeral; ideal for tests and demos.
* :class:`GitSyncBackend`         -- a disk backend that commits after every
  mutation, so the whole memory/knowledge base is a durable, portable git
  history you can push to GitHub, a HuggingFace dataset repo, or anywhere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    """A single node in a directory listing."""

    path: str  # relative POSIX path, e.g. "kb/notes.md"
    is_dir: bool
    size: int  # bytes; 0 for directories


class StorageBackend(ABC):
    """Minimal filesystem surface used by the memory tool handler.

    Implementations must treat ``""`` (empty string) as the memory root.
    """

    # --- queries -------------------------------------------------------
    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def is_dir(self, path: str) -> bool: ...

    @abstractmethod
    def size(self, path: str) -> int: ...

    @abstractmethod
    def read_text(self, path: str) -> str: ...

    @abstractmethod
    def walk(self, path: str, max_depth: int = 2) -> list[Entry]:
        """Return entries under ``path`` up to ``max_depth`` levels deep.

        Hidden entries (leading ``.``) and ``node_modules`` are excluded.
        The root ``path`` itself is included as the first entry.
        """

    # --- mutations -----------------------------------------------------
    @abstractmethod
    def write_text(self, path: str, text: str) -> None: ...

    @abstractmethod
    def delete(self, path: str) -> None: ...

    @abstractmethod
    def rename(self, old_path: str, new_path: str) -> None: ...

    # --- hooks ---------------------------------------------------------
    def commit(self, message: str) -> None:  # noqa: D401 - optional hook
        """Persist a logical change. No-op unless a backend overrides it."""


def _human_size(num_bytes: int) -> str:
    """Format bytes the way ``du -h`` does, matching the memory tool spec."""
    size = float(num_bytes)
    for unit in ("", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            if unit == "":
                return f"{int(size)}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}T"  # pragma: no cover - unreachable


class LocalFilesystemBackend(StorageBackend):
    """Backs the memory tree with a real directory on disk."""

    def __init__(self, base_path: str):
        self.base = os.path.abspath(base_path)
        os.makedirs(self.base, exist_ok=True)

    def _abs(self, path: str) -> str:
        # ``path`` is already validated/relative; join and re-confirm it stays
        # inside base as a defence-in-depth second gate.
        full = os.path.abspath(os.path.join(self.base, path))
        if full != self.base and not full.startswith(self.base + os.sep):
            raise ValueError(f"path escapes storage root: {path!r}")
        return full

    def exists(self, path: str) -> bool:
        return os.path.exists(self._abs(path))

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(self._abs(path))

    def size(self, path: str) -> int:
        p = self._abs(path)
        return 0 if os.path.isdir(p) else os.path.getsize(p)

    def read_text(self, path: str) -> str:
        with open(self._abs(path), "r", encoding="utf-8") as fh:
            return fh.read()

    def write_text(self, path: str, text: str) -> None:
        full = self._abs(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)

    def delete(self, path: str) -> None:
        full = self._abs(path)
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)

    def rename(self, old_path: str, new_path: str) -> None:
        dst = self._abs(new_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(self._abs(old_path), dst)

    def walk(self, path: str, max_depth: int = 2) -> list[Entry]:
        root = self._abs(path)
        entries: list[Entry] = [Entry(path=path, is_dir=True, size=0)]
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
            # Prune hidden dirs / node_modules and stop descending past depth.
            dirnames[:] = [
                d for d in dirnames if not d.startswith(".") and d != "node_modules"
            ]
            if depth >= max_depth:
                dirnames[:] = []
            for name in sorted(dirnames):
                rel = os.path.relpath(os.path.join(dirpath, name), self.base)
                entries.append(Entry(path=rel.replace(os.sep, "/"), is_dir=True, size=0))
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, self.base)
                entries.append(
                    Entry(
                        path=rel.replace(os.sep, "/"),
                        is_dir=False,
                        size=os.path.getsize(full),
                    )
                )
        return entries


class InMemoryBackend(StorageBackend):
    """Ephemeral backend; a dict of ``path -> text``. Great for tests."""

    def __init__(self) -> None:
        self._files: dict[str, str] = {}

    def _dirs(self) -> set[str]:
        dirs: set[str] = {""}
        for path in self._files:
            parts = path.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))
        return dirs

    def exists(self, path: str) -> bool:
        return path in self._files or path in self._dirs()

    def is_dir(self, path: str) -> bool:
        return path in self._dirs()

    def size(self, path: str) -> int:
        return len(self._files.get(path, "").encode("utf-8"))

    def read_text(self, path: str) -> str:
        return self._files[path]

    def write_text(self, path: str, text: str) -> None:
        self._files[path] = text

    def delete(self, path: str) -> None:
        for key in [k for k in self._files if k == path or k.startswith(path + "/")]:
            del self._files[key]

    def rename(self, old_path: str, new_path: str) -> None:
        moved = {
            (new_path + k[len(old_path):]): v
            for k, v in self._files.items()
            if k == old_path or k.startswith(old_path + "/")
        }
        self.delete(old_path)
        self._files.update(moved)

    def walk(self, path: str, max_depth: int = 2) -> list[Entry]:
        prefix = "" if path == "" else path + "/"
        base_depth = 0 if path == "" else path.count("/") + 1
        entries: list[Entry] = [Entry(path=path, is_dir=True, size=0)]
        seen: set[str] = set()
        for full, text in sorted(self._files.items()):
            if not (full == path or full.startswith(prefix)):
                continue
            rel_depth = full.count("/") - (base_depth - 1) if path else full.count("/") + 1
            if rel_depth > max_depth:
                # still surface the intermediate directory
                cut = "/".join(full.split("/")[:base_depth + max_depth - 1])
                if cut and cut not in seen:
                    seen.add(cut)
                    entries.append(Entry(path=cut, is_dir=True, size=0))
                continue
            parts = full.split("/")
            for i in range(base_depth, len(parts) - 1):
                d = "/".join(parts[: i + 1])
                if d not in seen:
                    seen.add(d)
                    entries.append(Entry(path=d, is_dir=True, size=0))
            entries.append(
                Entry(path=full, is_dir=False, size=len(text.encode("utf-8")))
            )
        return entries


class GitSyncBackend(LocalFilesystemBackend):
    """Disk backend that commits after every mutation.

    Turns the memory/knowledge base into a durable, portable git history.
    ``auto_push`` optionally pushes to ``remote`` after each commit so a
    stateless / ephemeral worker (Zaac-style) can persist across restarts.
    """

    def __init__(
        self,
        base_path: str,
        *,
        auto_push: bool = False,
        remote: str = "origin",
        branch: str = "main",
        author: str = "mnemex <mnemex@localhost>",
    ):
        super().__init__(base_path)
        self.auto_push = auto_push
        self.remote = remote
        self.branch = branch
        self.author = author
        if not os.path.isdir(os.path.join(self.base, ".git")):
            self._git("init", "-q")
            self._git("checkout", "-q", "-B", self.branch)

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        name, _, email = self.author.partition(" <")
        env.setdefault("GIT_AUTHOR_NAME", name)
        env.setdefault("GIT_COMMITTER_NAME", name)
        env.setdefault("GIT_AUTHOR_EMAIL", email.rstrip(">") or "mnemex@localhost")
        env.setdefault("GIT_COMMITTER_EMAIL", email.rstrip(">") or "mnemex@localhost")
        return subprocess.run(
            ["git", "-C", self.base, *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def commit(self, message: str) -> None:
        self._git("add", "-A")
        result = self._git("commit", "-q", "-m", message)
        if result.returncode == 0 and self.auto_push:
            self._git("push", "-q", self.remote, self.branch)

    # Route mutations through commit() so history stays coherent.
    def write_text(self, path: str, text: str) -> None:
        super().write_text(path, text)
        self.commit(f"memory: write {path}")

    def delete(self, path: str) -> None:
        super().delete(path)
        self.commit(f"memory: delete {path}")

    def rename(self, old_path: str, new_path: str) -> None:
        super().rename(old_path, new_path)
        self.commit(f"memory: rename {old_path} -> {new_path}")
