"""``store.lock(key)`` — exclusive named locks held in the store (lacing#70).

Same key excludes, different keys do not. ``MemoryStore`` / ``MappingStore``
exclude threads; ``SqliteStore`` also other processes (a file lock beside the
db). The Postgres backend's case lives in ``test_store_postgres.py``.
"""

from __future__ import annotations

import copy
import pickle
import subprocess
import sys
import threading
import time

import pytest

from lacing.store import MappingStore, MemoryStore, SqliteStore

#: How long to wait to prove a thread is still blocked.
BLOCKED_SECS = 0.3
#: Generous upper bound for something that should happen at once.
PROMPT_SECS = 5.0


@pytest.fixture(params=["memory", "mapping", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        s = MemoryStore()
    elif request.param == "mapping":
        s = MappingStore({})
    else:
        s = SqliteStore(tmp_path / "l.annot", check_same_thread=False)
    yield s
    if request.param == "sqlite":
        s.close()


def _try_lock(store, key) -> tuple[threading.Thread, threading.Event, threading.Event]:
    """A thread that takes ``store.lock(key)``; returns (thread, acquired, release)."""
    acquired, release = threading.Event(), threading.Event()

    def run():
        with store.lock(key):
            acquired.set()
            release.wait(PROMPT_SECS)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, acquired, release


def test_same_key_excludes_until_released(store):
    with store.lock("k"):
        t, acquired, release = _try_lock(store, "k")
        assert not acquired.wait(BLOCKED_SECS)  # blocked while we hold it
    assert acquired.wait(PROMPT_SECS)  # and proceeds once we let go
    release.set()
    t.join(PROMPT_SECS)


def test_different_keys_do_not_contend(store):
    with store.lock("a"):
        t, acquired, release = _try_lock(store, "b")
        assert acquired.wait(PROMPT_SECS)
        release.set()
        t.join(PROMPT_SECS)


def test_lock_is_released_when_the_body_raises(store):
    with pytest.raises(RuntimeError):
        with store.lock("k"):
            raise RuntimeError("boom")
    t, acquired, release = _try_lock(store, "k")
    assert acquired.wait(PROMPT_SECS)
    release.set()
    t.join(PROMPT_SECS)


def test_lock_serialises_a_read_modify_write(store):
    counter = [0]

    def bump():
        for _ in range(50):
            with store.lock("counter"):
                n = counter[0]
                time.sleep(0)  # invite a thread switch inside the section
                counter[0] = n + 1

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert counter[0] == 200


def test_memory_store_with_locks_still_copies_and_pickles():
    s = MemoryStore()
    with s.lock("k"):
        pass
    for clone in (copy.deepcopy(s), pickle.loads(pickle.dumps(s))):
        with clone.lock("k"):  # a copy has its own, free, locks
            pass


def test_sqlite_lock_excludes_another_process(tmp_path):
    """A second process on the same ``.annot`` file waits for the holder."""
    path = tmp_path / "x.annot"
    child_code = (
        "import sys\n"
        "from lacing.store import SqliteStore\n"
        "s = SqliteStore(sys.argv[1])\n"
        "print('ready', flush=True)\n"
        "with s.lock('k'):\n"
        "    print('got', flush=True)\n"
    )
    with SqliteStore(path) as s:
        with s.lock("k"):
            child = subprocess.Popen(
                [sys.executable, "-c", child_code, str(path)],
                stdout=subprocess.PIPE,
                text=True,
            )
            assert child.stdout.readline().strip() == "ready"
            time.sleep(BLOCKED_SECS)
            assert child.poll() is None  # still waiting on us, not finished
        out, _ = child.communicate(timeout=30)  # we let go: it gets the lock
    assert out.split() == ["got"]
