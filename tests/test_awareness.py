"""Tests for the Yjs Awareness relay.

The relay is content-agnostic — it never parses the y-protocol payload —
so these tests use synthetic byte strings whose first byte is the
documented message-type.

Strategy (lacing#99)
--------------------
- **One event loop.** The client is entered as a context manager, so every
  socket of a test runs on one portal. Without it each socket gets its own
  event-loop thread, and the relay would push bytes across loops.
- **Settled joins.** ``websocket_connect`` returns once the server has
  *accepted*, which is before it registers the socket in its room. The relay
  sends each existing peer a query byte only after registering the newcomer,
  so :func:`_join` waits for that byte on every peer: after it, a message sent
  to the room reaches the newcomer, and no query is left queued.
- **Deadlines.** Every receive goes through :func:`_receive`, which fails the
  test after :data:`RECEIVE_TIMEOUT_S` rather than blocking forever.

With joins settled and queries drained, each test asserts the exact next
message a socket receives; "this socket got nothing" is shown by the next
message being a later sentinel (which relies on the one event loop handling
the earlier message first, as the relay's paths are equally long).
"""

from __future__ import annotations

from contextlib import ExitStack

import pytest

pytest.importorskip("fastapi")

import anyio  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lacing.server import create_app  # noqa: E402
from lacing.server.awareness import (  # noqa: E402
    MSG_AWARENESS,
    MSG_AWARENESS_QUERY,
    MSG_SYNC,
)

RECEIVE_TIMEOUT_S = 5.0
QUERY = bytes([MSG_AWARENESS_QUERY])


@pytest.fixture
def client():
    with TestClient(create_app()) as client:  # one portal for every socket
        yield client


@pytest.fixture
def sockets(client):
    """The test's sockets, closed before ``client``'s portal shuts down: the
    dependency fixes teardown order whatever the test's argument order."""
    with ExitStack() as stack:
        yield stack


def _receive(ws, *, timeout: float = RECEIVE_TIMEOUT_S) -> bytes:
    """``ws.receive_bytes()``, failing the test after ``timeout`` seconds.

    Starlette's test session has no receive timeout, so this reads its
    session stream (``_send_rx``, private) under ``anyio.fail_after``.
    """

    async def receive():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    try:
        message = ws.portal.call(receive)
    except TimeoutError:
        pytest.fail(f"no message within {timeout}s")
    ws._raise_on_close(message)
    return message["bytes"]


def _join(sockets: ExitStack, client: TestClient, room: str, *peers):
    """Connect to ``room`` and wait until the relay has registered the socket:
    each of ``peers`` (already in ``room``) receives its join query."""
    ws = sockets.enter_context(client.websocket_connect(f"/ws/awareness/{room}"))
    for peer in peers:
        assert _receive(peer) == QUERY
    return ws


def _aw(payload: bytes = b"\x00\x00") -> bytes:
    """Synthetic awareness message: type byte + opaque payload."""
    return bytes([MSG_AWARENESS]) + payload


def test_two_clients_in_same_room_receive_each_others_awareness(client, sockets):
    """A → B propagation through the relay."""
    a = _join(sockets, client, "proj-1")
    b = _join(sockets, client, "proj-1", a)
    a.send_bytes(_aw(b"hello-from-a"))
    assert _receive(b) == _aw(b"hello-from-a")


def test_clients_in_different_rooms_are_isolated(client, sockets):
    """A in proj-1 must not be heard by B in proj-2: B's next message after A
    sends is C's (sent later, from proj-2)."""
    a = _join(sockets, client, "proj-1")
    b = _join(sockets, client, "proj-2")
    c = _join(sockets, client, "proj-2", b)
    a.send_bytes(_aw(b"from-proj-1"))
    c.send_bytes(_aw(b"from-proj-2"))
    assert _receive(b) == _aw(b"from-proj-2")


def test_sender_does_not_receive_its_own_message(client, sockets):
    """A's own broadcast must not echo back: A's next message is B's."""
    a = _join(sockets, client, "proj-1")
    b = _join(sockets, client, "proj-1", a)
    a.send_bytes(_aw(b"a-says"))
    b.send_bytes(_aw(b"b-says"))
    assert _receive(a) == _aw(b"b-says")


def test_sync_messages_are_dropped(client, sockets):
    """Doc-CRDT (MSG_SYNC) is out of scope for Phase 4-A — the relay drops it:
    B's next message is the awareness message sent after it."""
    a = _join(sockets, client, "proj-1")
    b = _join(sockets, client, "proj-1", a)
    a.send_bytes(bytes([MSG_SYNC]) + b"sync-payload")
    a.send_bytes(_aw(b"awareness-after-sync"))
    assert _receive(b) == _aw(b"awareness-after-sync")


def test_query_byte_is_relayed(client, sockets):
    """Reply payloads tagged MSG_AWARENESS_QUERY must propagate."""
    a = _join(sockets, client, "proj-1")
    b = _join(sockets, client, "proj-1", a)
    a.send_bytes(QUERY + b"reply-state")
    assert _receive(b) == QUERY + b"reply-state"


def test_three_clients_full_fanout(client, sockets):
    """A's awareness should reach both B and C in the same room."""
    a = _join(sockets, client, "proj-1")
    b = _join(sockets, client, "proj-1", a)
    c = _join(sockets, client, "proj-1", a, b)
    a.send_bytes(_aw(b"to-b-and-c"))
    assert _receive(b) == _aw(b"to-b-and-c")
    assert _receive(c) == _aw(b"to-b-and-c")


def test_a_missing_message_fails_instead_of_hanging(client, sockets):
    """The deadline itself: nothing is sent, so the receive must fail fast."""
    a = _join(sockets, client, "proj-1")
    with pytest.raises(pytest.fail.Exception, match="no message within"):
        _receive(a, timeout=0.2)
