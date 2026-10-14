"""Named exclusive locks for stores: the mechanisms behind ``store.lock(key)``.

``IntervalAnnotationStore.lock(key)`` is an exclusive context manager scoped to
one store (for ``PostgresStore``: one ``(owner, project)``). Each backend picks
the narrowest mechanism that excludes every holder that can reach the same
data: a process-local lock for ``MemoryStore``, a file lock beside the database
for ``SqliteStore`` (excludes other processes on the host too), a Postgres
advisory lock for ``PostgresStore`` (excludes other hosts).

Locks are *not* re-entrant: taking a lock you already hold blocks forever.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover  — Windows
    _fcntl = None
    import msvcrt as _msvcrt

#: Bytes of the blake2b digest used to name a key (file name / advisory id).
KEY_DIGEST_BYTES = 8


def key_digest(*parts: str) -> bytes:
    """Stable digest of ``parts`` (length-prefixed, so ``("a", "bc") != ("ab", "c")``)."""
    h = hashlib.blake2b(digest_size=KEY_DIGEST_BYTES)
    for part in parts:
        raw = part.encode("utf-8")
        h.update(len(raw).to_bytes(4, "big"))
        h.update(raw)
    return h.digest()


def advisory_lock_id(*parts: str) -> int:
    """A signed 64-bit integer for ``parts``: the argument of ``pg_advisory_lock``.

    >>> advisory_lock_id("o", "p", "k") == advisory_lock_id("o", "p", "k")
    True
    >>> advisory_lock_id("o", "p", "k") != advisory_lock_id("o", "p", "other")
    True
    >>> -2**63 <= advisory_lock_id("o", "p", "k") < 2**63
    True
    """
    return int.from_bytes(key_digest(*parts), "big", signed=True)


class NamedLocks:
    """Process-local named exclusive locks (a registry of ``threading.Lock``)."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def __getstate__(self) -> dict:
        return {}  # locks cannot be copied or pickled; a copy starts fresh

    def __setstate__(self, state: dict) -> None:
        self.__init__()

    @contextmanager
    def __call__(self, key: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            yield


@contextmanager
def file_lock(path: str | os.PathLike) -> Iterator[None]:
    """Exclusive lock on ``path`` (created if missing), held for the ``with`` block.

    A fresh file descriptor per call, so threads of one process exclude each
    other as well as other processes. The kernel drops the lock if the holder
    dies. The lock file is left in place (removing it would race a waiter).
    """
    fd = os.open(os.fspath(path), os.O_RDWR | os.O_CREAT, 0o666)
    try:
        if _fcntl is not None:
            _fcntl.flock(fd, _fcntl.LOCK_EX)
        else:  # pragma: no cover  — Windows: LK_LOCK retries for ~10 s, so loop
            while True:
                try:
                    _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
        try:
            yield
        finally:
            if _fcntl is not None:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
            else:  # pragma: no cover
                os.lseek(fd, 0, os.SEEK_SET)
                _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def sidecar_lock_path(db_path: str | os.PathLike, key: str) -> str:
    """Lock file for ``key`` beside the database at ``db_path``."""
    return f"{os.fspath(db_path)}.{key_digest(key).hex()}.lock"
