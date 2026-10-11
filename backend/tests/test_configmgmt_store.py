"""The local configuration repository (dulwich, bare)."""

import stat
import subprocess
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from netops.configmgmt.store import ConfigStore, ConfigStoreError

NOW = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)


def test_commit_and_read_back(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "configs")
    a, b = uuid.uuid4(), uuid.uuid4()
    first = store.commit(a, "hostname a\n", "a: scheduled backup", NOW)
    second = store.commit(b, "hostname b\n", "b: scheduled backup", NOW)
    third = store.commit(a, "hostname a\nip domain lookup\n", "a: change_event backup", NOW)
    assert len({first, second, third}) == 3
    assert store.read(first, a) == "hostname a\n"
    assert store.read(third, a) == "hostname a\nip domain lookup\n"
    assert store.read(third, b) == "hostname b\n"  # other devices' files are carried along
    with pytest.raises(ConfigStoreError):
        store.read(first, b)


def test_repository_is_private(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "configs")
    store.commit(uuid.uuid4(), "hostname x\n", "x", NOW)
    mode = stat.S_IMODE((tmp_path / "configs").stat().st_mode)
    assert mode == 0o700


def test_concurrent_writers_lose_nothing(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "configs")
    devices = [uuid.uuid4() for _ in range(8)]
    commits: dict[uuid.UUID, str] = {}

    def write(device: uuid.UUID) -> None:
        commits[device] = ConfigStore(tmp_path / "configs").commit(
            device, f"hostname {device}\n", "backup", NOW
        )

    threads = [threading.Thread(target=write, args=(d,)) for d in devices]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    last = max(commits.values(), key=lambda c: len(_log(tmp_path / "configs", c)))
    for device in devices:
        assert store.read(last, device) == f"hostname {device}\n"


def _log(path: Path, commit: str) -> list[str]:
    from dulwich.objects import ObjectID
    from dulwich.repo import Repo

    repo = Repo(str(path))
    try:
        walker = repo.get_walker(include=[ObjectID(commit.encode())])
        return [entry.commit.id.decode() for entry in walker]
    finally:
        repo.close()


def test_plain_git_can_read_it(tmp_path: Path) -> None:
    device = uuid.uuid4()
    ConfigStore(tmp_path / "configs").commit(device, "hostname x\n", "x: manual backup", NOW)
    shown = subprocess.run(  # noqa: S603
        ["git", "-C", str(tmp_path / "configs"), "show", f"main:{device}.cfg"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    assert shown.stdout == "hostname x\n"
