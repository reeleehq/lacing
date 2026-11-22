"""Named exclusive locks for stores: the mechanisms behind ``store.lock(key)``.

``IntervalAnnotationStore.lock(key)`` is an exclusive context manager scoped to
one store (for ``PostgresStore``: one ``(owner, project)``). Each backend picks
the narrowest mechanism that excludes every holder that can reach the same
data: a process-local lock for ``MemoryStore``, a file lock beside the database
for ``SqliteStore`` (excludes other processes on the host too), a Postgres
advisory lock for ``PostgresStore`` (excludes other hosts).

Locks are *not* re-entrant: taking a lock you already hold blocks forever.

:class:`KeyedTurn` is the same exclusion as a *turn* a caller takes and gives
back: a per-key turn across threads and processes, with a blocking acquire for
worker threads, a non-blocking one, and an ``async`` acquire an event loop polls
without holding a thread (lacing#194).
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Iterator
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


# --------------------------------------------------------------------------- #
# KeyedTurn: a per-key turn across threads and processes (lacing#194)
# --------------------------------------------------------------------------- #

#: Seconds between tries of another process's hold on a turn.
DFLT_TURN_POLL_S: float = 0.05


def turn_file_name(key: str) -> str:
    """The lock file a :class:`KeyedTurn` of ``key`` holds: its digest, so a key may
    hold any character (an email, a path) and never names a file itself."""
    return f"{key_digest(key).hex()}.lock"


class KeyedTurn:
    """One key's turn, ordered across this process's threads and every process
    that shares ``directory``.

    A thread lock orders this process's callers; an exclusive ``flock`` on
    ``directory/<name_of(key)>`` orders them against other processes. The kernel
    releases an ``flock`` when its holder dies, so a crashed process never leaves a
    turn held. Without ``fcntl`` (not POSIX) the turn is the thread lock alone.

    **It fails closed**: when the lock file cannot be made (an unwritable
    directory), taking the turn raises ``OSError`` rather than running unordered.

    Three ways to take it: :meth:`acquire` (blocking, with a ``timeout``),
    :meth:`try_acquire` (never blocks) and :meth:`acquire_async` (polls
    :meth:`try_acquire` from an event loop, so a cancelled waiter holds nothing).
    Not re-entrant; :meth:`release` gives it back. As a context manager it is the
    blocking acquire.

    >>> import tempfile
    >>> turn = KeyedTurn(tempfile.mkdtemp(), "alice@example.com")
    >>> turn.try_acquire(), turn.try_acquire()
    (True, False)
    >>> turn.release(); turn.try_acquire()
    True
    >>> turn.release()
    """

    def __init__(
        self,
        directory: str | os.PathLike,
        key: str,
        *,
        name_of: Callable[[str], str] = turn_file_name,
        poll_s: float = DFLT_TURN_POLL_S,
    ) -> None:
        self.directory = os.fspath(directory)
        self.key = key
        self.poll_s = poll_s
        self._file_name = name_of(key)
        self._thread_lock = threading.Lock()
        self._fd: int | None = None

    @property
    def path(self) -> str:
        """The lock file this turn holds."""
        return os.path.join(self.directory, self._file_name)

    def _open(self) -> int:
        os.makedirs(self.directory, exist_ok=True)
        # Read-only is enough for flock, and works on a lock file another user made.
        return os.open(self.path, os.O_RDONLY | os.O_CREAT, 0o644)

    def _take_file(self, *, deadline: float | None) -> bool:
        """With the thread lock held: the file lock by ``deadline`` (``None``: try once)."""
        import time

        if _fcntl is None:  # pragma: no cover  — not POSIX: this process's order only
            return True
        fd = self._open()
        try:
            while True:
                try:
                    _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                    self._fd = fd
                    return True
                except BlockingIOError:
                    if deadline is None or (
                        deadline >= 0 and time.monotonic() >= deadline
                    ):
                        os.close(fd)
                        return False
                    time.sleep(self.poll_s)
        except BaseException:
            os.close(fd)
            raise

    def try_acquire(self) -> bool:
        """Take the turn now, or ``False`` when it is held; never blocks."""
        if not self._thread_lock.acquire(blocking=False):
            return False
        try:
            taken = self._take_file(deadline=None)
        except BaseException:
            self._thread_lock.release()
            raise
        if not taken:
            self._thread_lock.release()
        return taken

    def acquire(self, timeout: float = -1) -> bool:
        """Take the turn within ``timeout`` seconds (negative: as long as it takes);
        ``False`` when it is still held."""
        import time

        deadline = -1.0 if timeout < 0 else time.monotonic() + timeout
        if not self._thread_lock.acquire(timeout=timeout):
            return False
        try:
            taken = self._take_file(deadline=deadline)
        except BaseException:
            self._thread_lock.release()
            raise
        if not taken:
            self._thread_lock.release()
        return taken

    async def acquire_async(
        self, *, poll_s: float | None = None, deadline_s: float | None = None
    ) -> bool:
        """Take the turn from an event loop: :meth:`try_acquire` every ``poll_s``
        (default the turn's), for at most ``deadline_s`` seconds (``None``: until
        taken). Nothing is held across an ``await``, so a cancelled waiter holds
        nothing."""
        import asyncio
        import time

        poll = self.poll_s if poll_s is None else poll_s
        deadline = None if deadline_s is None else time.monotonic() + deadline_s
        while not self.try_acquire():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(poll)
        return True

    def release(self) -> None:
        """Give the turn back, to this process's next caller and to other processes."""
        fd, self._fd = self._fd, None
        try:
            if fd is not None and _fcntl is not None:
                try:
                    _fcntl.flock(fd, _fcntl.LOCK_UN)
                finally:
                    os.close(fd)
        finally:
            self._thread_lock.release()

    def __enter__(self) -> "KeyedTurn":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


_KEYED_TURNS: dict[tuple[str, str, Callable[[str], str]], KeyedTurn] = {}
_KEYED_TURNS_GUARD = threading.Lock()


def keyed_turn(
    directory: str | os.PathLike,
    key: str,
    *,
    name_of: Callable[[str], str] = turn_file_name,
) -> KeyedTurn:
    """The one :class:`KeyedTurn` per ``(directory, key)`` in this process: every
    caller that takes a key's turn must share one, or their thread locks would not
    order them. Kept for the process's life, so the map is bounded by the number
    of distinct keys."""
    ident = (os.path.abspath(os.fspath(directory)), key, name_of)
    with _KEYED_TURNS_GUARD:
        turn = _KEYED_TURNS.get(ident)
        if turn is None:
            turn = _KEYED_TURNS[ident] = KeyedTurn(directory, key, name_of=name_of)
        return turn
