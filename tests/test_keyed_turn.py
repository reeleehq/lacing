"""``lacing.store.locking.KeyedTurn``: a per-key turn across threads and processes
(lacing#194)."""

import asyncio
import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from lacing.store.locking import KeyedTurn, keyed_turn, turn_file_name

fcntl = pytest.importorskip("fcntl")


def test_threads_take_turns_one_at_a_time(tmp_path):
    turn = keyed_turn(tmp_path, "alice")
    inside, most = [0], [0]
    guard = threading.Lock()

    def work():
        with turn:
            with guard:
                inside[0] += 1
                most[0] = max(most[0], inside[0])
            time.sleep(0.01)
            with guard:
                inside[0] -= 1

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert most[0] == 1


def test_another_process_holding_the_key_is_waited_for(tmp_path):
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import sys, time
            from lacing.store.locking import KeyedTurn
            t = KeyedTurn({str(tmp_path)!r}, "alice")
            assert t.acquire()
            print("held", flush=True)
            time.sleep(1.0)
            t.release()
        """)],
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        turn = KeyedTurn(tmp_path, "alice")
        assert not turn.try_acquire()  # held by the other process
        assert not turn.acquire(timeout=0.1)
        assert KeyedTurn(tmp_path, "bob").try_acquire()  # another key is free
        t0 = time.monotonic()
        assert turn.acquire(timeout=10)  # given back when the holder releases
        assert time.monotonic() - t0 > 0.2
        turn.release()
    finally:
        holder.wait(10)


def test_a_dead_holder_releases_its_turn(tmp_path):
    subprocess.run(
        [sys.executable, "-c", textwrap.dedent(f"""
            import os
            from lacing.store.locking import KeyedTurn
            KeyedTurn({str(tmp_path)!r}, "alice").acquire()
            os._exit(0)  # dies holding it
        """)],
        check=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    turn = KeyedTurn(tmp_path, "alice")
    assert turn.try_acquire()
    turn.release()


def test_the_async_acquire_waits_without_a_thread_and_a_cancelled_waiter_holds_nothing(tmp_path):
    turn = keyed_turn(tmp_path, "carol")

    async def scenario():
        assert turn.try_acquire()
        waiter = asyncio.ensure_future(turn.acquire_async(poll_s=0.01))
        await asyncio.sleep(0.05)
        assert not waiter.done()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        turn.release()
        assert await turn.acquire_async(poll_s=0.01, deadline_s=1.0)  # nothing was left held
        assert not await KeyedTurn(tmp_path, "carol").acquire_async(poll_s=0.01, deadline_s=0.05)
        turn.release()

    asyncio.run(scenario())


def test_one_turn_per_directory_and_key_per_process(tmp_path):
    assert keyed_turn(tmp_path, "dan") is keyed_turn(str(tmp_path), "dan")
    assert keyed_turn(tmp_path, "dan") is not keyed_turn(tmp_path, "eve")
    assert keyed_turn(tmp_path, "dan").path == os.path.join(str(tmp_path), turn_file_name("dan"))


def test_an_existing_lock_file_name_can_be_kept(tmp_path):
    named = KeyedTurn(tmp_path, "alice", name_of=lambda key: f"{key}.lock")
    assert named.path.endswith("alice.lock")
    assert named.try_acquire()
    assert not KeyedTurn(tmp_path, "x", name_of=lambda _key: "alice.lock").try_acquire()
    named.release()


def test_it_fails_closed_when_the_lock_file_cannot_be_made(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("a file where the directory should be")
    turn = KeyedTurn(blocker / "turns", "alice")
    with pytest.raises(OSError):
        turn.acquire()
    with pytest.raises(OSError):
        turn.try_acquire()
    assert not turn._thread_lock.locked()  # nothing left half-held


import math

import pytest


@pytest.mark.parametrize("timeout", [-2, -0.5, math.inf, None])
def test_any_negative_infinite_or_none_timeout_waits_as_long_as_it_takes(
    tmp_path, timeout
):
    """Not only ``-1`` (lacing#210)."""
    from lacing.store.locking import KeyedTurn

    turn = KeyedTurn(tmp_path, "k")
    assert turn.acquire(timeout=timeout)
    turn.release()


def test_a_turn_keeps_its_directory_after_a_chdir(tmp_path, monkeypatch):
    """A relative directory is resolved once, where the turn is made (lacing#210)."""
    from lacing.store.locking import keyed_turn

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    monkeypatch.chdir(tmp_path / "a")
    turn = keyed_turn("turns", "k")
    monkeypatch.chdir(tmp_path / "b")
    assert turn.path.startswith(str((tmp_path / "a").resolve()))
