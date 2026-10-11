"""The configuration repository: a local, bare Git repository (dulwich).

One file per device (``<device id>.cfg``) holds its normalized running-config; every new
version is one commit on ``main``. The repository lives in its own Docker volume on the
platform server, is never pushed anywhere and has nothing to do with the project's GitHub
repository (ADR-0007). It holds complete configurations, secrets included, so its
directory is readable by the platform's user only.

Writes build Git objects directly (no working tree, no index). Writers on the host take
turns through a lock file and move ``main`` with a compare-and-swap, retried, so concurrent
workers cannot lose each other's commits.
"""

import fcntl
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from dulwich.objects import Blob, Commit, Tree
from dulwich.refs import HEADREF, Ref
from dulwich.repo import Repo

BRANCH = Ref(b"refs/heads/main")
AUTHOR = b"NetOps configuration backup <netops@localhost>"
_FILE_MODE = 0o100644
_ATTEMPTS = 20


class ConfigStoreError(Exception):
    pass


def _path(device_id: uuid.UUID) -> bytes:
    return f"{device_id}.cfg".encode()


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _repo(self, *, write: bool) -> Repo:
        if write:
            if not (self.path / "HEAD").exists():
                self._init()
            # Complete configurations: nobody but the platform's user may read them.
            os.chmod(self.path, 0o700)
        elif not (self.path / "HEAD").exists():
            raise ConfigStoreError(f"no configuration repository at {self.path}")
        return Repo(str(self.path))

    def _init(self) -> None:
        """Create the repository once, even with several workers starting at once."""
        self.path.mkdir(parents=True, exist_ok=True)
        with open(self.path / ".init.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not (self.path / "HEAD").exists():
                Repo.init_bare(str(self.path)).refs.set_symbolic_ref(HEADREF, BRANCH)

    def commit(self, device_id: uuid.UUID, text: str, message: str, when: datetime) -> str:
        """Store ``text`` as the device's file in a new commit; returns the commit id."""
        repo = self._repo(write=True)
        # Workers on one host take turns; the compare-and-swap below is the safety net.
        with open(self.path / ".commit.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return self._commit(repo, device_id, text, message, when)
            finally:
                repo.close()

    def _commit(
        self, repo: Repo, device_id: uuid.UUID, text: str, message: str, when: datetime
    ) -> str:
        blob = Blob.from_string(text.encode())
        repo.object_store.add_object(blob)
        for _ in range(_ATTEMPTS):
            parent = repo.refs[BRANCH] if BRANCH in repo.refs.allkeys() else None
            tree = Tree()
            if parent is not None:
                for entry in repo[repo[parent].tree].items():  # type: ignore[attr-defined]
                    tree.add(entry.path, entry.mode, entry.sha)
            tree.add(_path(device_id), _FILE_MODE, blob.id)
            repo.object_store.add_object(tree)
            commit = Commit()
            commit.tree = tree.id
            commit.parents = [parent] if parent is not None else []
            commit.author = commit.committer = AUTHOR
            commit.author_time = commit.commit_time = int(when.timestamp())
            utc_offset = when.utcoffset()
            offset = int(utc_offset.total_seconds()) if utc_offset is not None else 0
            commit.author_timezone = commit.commit_timezone = offset
            commit.encoding = b"UTF-8"
            commit.message = message.encode()
            repo.object_store.add_object(commit)
            try:
                if repo.refs.set_if_equals(BRANCH, parent, commit.id):
                    return commit.id.decode()
            except FileExistsError:
                pass  # main.lock is held by another writer
            time.sleep(0.05)  # main moved or is moving: rebuild on top of it
        raise ConfigStoreError("could not update the configuration repository")

    def read(self, commit_id: str, device_id: uuid.UUID) -> str:
        """The device's configuration as of a commit (the api reads a read-only mount)."""
        repo = self._repo(write=False)
        try:
            commit = repo[commit_id.encode()]
            tree = repo[commit.tree]  # type: ignore[attr-defined]
            _, sha = tree[_path(device_id)]  # type: ignore[index]
            data: bytes = repo[sha].data  # type: ignore[attr-defined]
            return data.decode()
        except KeyError as exc:
            raise ConfigStoreError(f"{device_id} is not in commit {commit_id}") from exc
        finally:
            repo.close()
