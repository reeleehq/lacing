"""``store.update(annotation)`` — replace by id in one transaction (lacing#66).

``remove(id)`` then ``add(...)`` is two commits: a reader between them sees no
annotation with that id, which is how a "read or create" caller made a second
singleton row. ``update`` must leave no such gap on any backend. The Postgres
backend's case lives in ``test_store_postgres.py`` (it needs a server).
"""

from __future__ import annotations

import sys
import threading
from uuid import uuid4

import pytest

from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MappingStore, MemoryStore, SqliteStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval

#: Replacements the writer thread makes in the concurrency test.
N_REPLACEMENTS = 300


def _ti(s: int, e: int) -> TimeInterval:
    return TimeInterval(RationalTime(s), RationalTime(e))


def _ann(interval: TimeInterval, *, id=None, tier="words", text="x") -> Annotation:
    return Annotation(
        id=id or uuid4(),
        tier=tier,
        reference=MediaRef(asset_id="blake3:test", interval=interval),
        body={"text": text},
        body_schema_uri="annot://schema/word/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime(0),
        ),
    )


@pytest.fixture(params=["memory", "mapping", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        s = MemoryStore()
    elif request.param == "mapping":
        s = MappingStore({})
    else:
        s = SqliteStore(tmp_path / "u.annot", check_same_thread=False)
    s.add_tier(Tier("words"))
    yield s
    if request.param == "sqlite":
        s.close()


def _texts(store) -> dict:
    return {a.id: a.body["text"] for a in store.all()}


def test_update_replaces_in_place(store):
    a = _ann(_ti(0, 2), text="old")
    other = _ann(_ti(0, 2), text="keep")
    store.add(a)
    store.add(other)
    store.update(_ann(_ti(0, 2), id=a.id, text="new"))
    assert _texts(store) == {a.id: "new", other.id: "keep"}


def test_update_can_move_the_annotation(store):
    a = _ann(_ti(0, 2), text="old")
    store.add(a)
    store.update(_ann(_ti(10, 12), id=a.id, text="moved"))
    assert _texts(store) == {a.id: "moved"}
    assert [x.id for x in store.intersects(_ti(10, 12))] == [a.id]
    assert list(store.intersects(_ti(0, 2))) == []
    assert _ti(0, 2) not in store


def test_update_unknown_id_raises_and_changes_nothing(store):
    a = _ann(_ti(0, 2), text="old")
    store.add(a)
    with pytest.raises(KeyError):
        store.update(_ann(_ti(0, 2), text="ghost"))
    assert _texts(store) == {a.id: "old"}


@pytest.mark.parametrize("move", [False, True], ids=["same-interval", "moving"])
def test_a_reader_never_finds_the_id_missing(store, move):
    """The acceptance test: a reader thread and a replacing thread.

    The reader asks for the id by whole-store scan *and* by an interval query
    that covers both places the annotation lives, so a gap in either the row or
    the interval index shows up.
    """
    target = _ann(_ti(0, 2), text="0")
    store.add(target)
    everywhere = _ti(0, 100)
    missing: list[str] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            if target.id not in {a.id for a in store.all()}:
                missing.append("all()")
            if target.id not in {a.id for a in store.intersects(everywhere)}:
                missing.append("intersects()")

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # make a thread switch inside the gap likely
    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(1, N_REPLACEMENTS + 1):
            iv = _ti(10, 12) if move and i % 2 else _ti(0, 2)
            store.update(_ann(iv, id=target.id, text=str(i)))
    finally:
        stop.set()
        t.join()
        sys.setswitchinterval(old_interval)
    assert missing == []
    assert _texts(store) == {target.id: str(N_REPLACEMENTS)}


def test_mapping_store_update_persists(tmp_path):
    backing: dict = {}
    s = MappingStore(backing)
    a = _ann(_ti(0, 2), text="old")
    s.add(a)
    s.update(_ann(_ti(4, 6), id=a.id, text="new"))
    reopened = MappingStore(backing)
    assert _texts(reopened) == {a.id: "new"}
    assert len(backing) == 1
