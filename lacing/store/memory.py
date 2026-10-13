"""In-memory annotation store backed by an interval tree.

Uses ``intervaltree`` (Apache-2.0). Annotations whose reference is not a
``MediaRef`` (i.e., they have no time interval) are kept in a separate
list — they can still be enumerated via ``all()`` / ``by_tier`` but
won't appear in interval queries.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from fractions import Fraction
from uuid import UUID

from intervaltree import Interval, IntervalTree

from lacing.allen import PREDICATE_BY_RELATION, AllenRelation
from lacing.model import Annotation
from lacing.tier import Tier
from lacing.time import TimeInterval


def _key(interval: TimeInterval) -> tuple[Fraction, Fraction]:
    """Convert a ``TimeInterval`` to fraction-pair keys for the interval tree."""
    return interval.start.to_fraction(), interval.end.to_fraction()


def _index_of(bucket: list[Annotation], ann: Annotation) -> int:
    """Position of ``ann`` in ``bucket`` by identity (equal annotations may repeat)."""
    return next(i for i, a in enumerate(bucket) if a is ann)


class MemoryStore:
    """``IntervalAnnotationStore`` implementation over ``intervaltree``.

    Conforms to the protocol in ``lacing.store.base``. We don't formally
    inherit from ``IntervalAnnotationStore`` because it's a ``Protocol``
    with method bodies — structural typing is enough.
    """

    def __init__(self) -> None:
        # Serialises writers and the snapshots readers take, so ``update`` is
        # atomic for a reader on another thread (lacing#66).
        self._lock = threading.RLock()
        self._tree: IntervalTree = IntervalTree()
        # interval-keyed bucket: (start_frac, end_frac) -> list of annotations
        self._buckets: dict[tuple[Fraction, Fraction], list[Annotation]] = {}
        # annotations with no time interval (e.g., NodeRef without interval support
        # in future, or AnnotationRef without sub-interval): kept addressable by id
        self._timeless: dict[UUID, Annotation] = {}
        self._tiers: dict[str, Tier] = {}

    # --- helpers --------------------------------------------------------------

    def _ensure_node(self, key: tuple[Fraction, Fraction]) -> list[Annotation]:
        if key not in self._buckets:
            self._buckets[key] = []
            # intervaltree forbids zero-length intervals; sidestep by storing
            # zero-length keys in the bucket dict only — they participate in
            # `intersects` via the explicit point handling below.
            if key[0] != key[1]:
                self._tree.add(Interval(key[0], key[1], key))
        return self._buckets[key]

    def _drop_node(self, key: tuple[Fraction, Fraction]) -> None:
        self._buckets.pop(key, None)
        if key[0] != key[1]:
            for iv in list(self._tree):
                if iv.data == key:
                    self._tree.remove(iv)

    # --- MutableMapping interface -------------------------------------------

    def __getitem__(self, key: TimeInterval) -> list[Annotation]:
        with self._lock:
            bucket = self._buckets.get(_key(key))
            if bucket is None:
                raise KeyError(key)
            return list(bucket)  # defensive copy

    def __setitem__(self, key: TimeInterval, value: list[Annotation]) -> None:
        k = _key(key)
        with self._lock:
            # Replace; ensure tree node exists exactly when bucket is non-empty.
            if not value:
                self._drop_node(k)
                return
            self._ensure_node(k)
            self._buckets[k] = list(value)

    def __delitem__(self, key: TimeInterval) -> None:
        k = _key(key)
        with self._lock:
            if k not in self._buckets:
                raise KeyError(key)
            self._drop_node(k)

    def __iter__(self) -> Iterator[TimeInterval]:
        for ann_list in self._buckets.values():
            if ann_list:
                iv = ann_list[0].interval
                if iv is not None:
                    yield iv

    def __len__(self) -> int:
        return sum(1 for ann_list in self._buckets.values() if ann_list)

    # --- annotation-level convenience ---------------------------------------

    def add(self, annotation: Annotation) -> None:
        self._insert(annotation)

    def _insert(self, annotation: Annotation) -> None:
        """``add`` without subclass checks (``update`` must not trip a duplicate-id guard)."""
        with self._lock:
            iv = annotation.interval
            if iv is None:
                self._timeless[annotation.id] = annotation
                return
            bucket = self._ensure_node(_key(iv))
            bucket.append(annotation)

    def remove(self, annotation_id: UUID) -> Annotation | None:
        with self._lock:
            # Search timeless first.
            if annotation_id in self._timeless:
                return self._timeless.pop(annotation_id)
            for k, bucket in list(self._buckets.items()):
                for i, a in enumerate(bucket):
                    if a.id == annotation_id:
                        bucket.pop(i)
                        if not bucket:
                            self._drop_node(k)
                        return a
            return None

    def update(self, annotation: Annotation) -> None:
        with self._lock:
            old = next((a for a in self.all() if a.id == annotation.id), None)
            if old is None:
                raise KeyError(annotation.id)
            old_iv, new_iv = old.interval, annotation.interval
            if old_iv is None and new_iv is None:
                self._timeless[annotation.id] = annotation  # one slot write
            elif (
                old_iv is not None
                and new_iv is not None
                and _key(old_iv) == _key(new_iv)
            ):
                bucket = self._buckets[_key(new_iv)]
                bucket[_index_of(bucket, old)] = annotation  # one slot write
            else:
                # The copy lands somewhere else: put the new one in *before*
                # taking the old out, so the id is never absent even to a
                # reader that does not take the lock.
                self._insert(annotation)
                self._take_out(old)

    def _take_out(self, old: Annotation) -> None:
        """Remove exactly ``old`` (by identity) from where ``add`` put it."""
        if old.interval is None:
            del self._timeless[old.id]
            return
        k = _key(old.interval)
        bucket = self._buckets[k]
        bucket.pop(_index_of(bucket, old))
        if not bucket:
            self._drop_node(k)

    def all(self) -> Iterator[Annotation]:
        with self._lock:
            snapshot = [a for bucket in self._buckets.values() for a in bucket]
            snapshot.extend(self._timeless.values())
        yield from snapshot

    # --- Allen-relation queries ---------------------------------------------

    def _bucket_snapshot(self) -> list[list[Annotation]]:
        """Copies of the non-empty buckets, taken under the lock (see ``update``)."""
        with self._lock:
            return [list(b) for b in self._buckets.values() if b]

    def _query(
        self, query: TimeInterval, relation: AllenRelation
    ) -> Iterator[Annotation]:
        pred = PREDICATE_BY_RELATION[relation]
        for bucket in self._bucket_snapshot():
            iv = bucket[0].interval
            if iv is not None and pred(iv, query):
                yield from bucket

    def intersects(self, query: TimeInterval) -> Iterator[Annotation]:
        from lacing.allen import intersects as _intersects

        for bucket in self._bucket_snapshot():
            iv = bucket[0].interval
            if iv is not None and _intersects(iv, query):
                yield from bucket

    def during(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._query(query, AllenRelation.DURING)

    def contains(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._query(query, AllenRelation.CONTAINS)

    def overlaps(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._query(query, AllenRelation.OVERLAPS)

    def meets(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._query(query, AllenRelation.MEETS)

    def starts(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._query(query, AllenRelation.STARTS)

    def finishes(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._query(query, AllenRelation.FINISHES)

    def equals(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._query(query, AllenRelation.EQUALS)

    def relate(
        self, query: TimeInterval, relations: Iterable[AllenRelation]
    ) -> Iterator[Annotation]:
        rels = set(relations)
        for bucket in self._bucket_snapshot():
            iv = bucket[0].interval
            if iv is None:
                continue
            for rel in rels:
                if PREDICATE_BY_RELATION[rel](iv, query):
                    yield from bucket
                    break

    # --- tier filters --------------------------------------------------------

    def by_tier(self, tier_name: str) -> Iterator[Annotation]:
        for ann in self.all():
            if ann.tier == tier_name:
                yield ann

    def at_tier(self, tier_name: str, query: TimeInterval) -> Iterator[Annotation]:
        for ann in self.intersects(query):
            if ann.tier == tier_name:
                yield ann

    # --- tier registry -------------------------------------------------------

    def tiers(self) -> Iterator[Tier]:
        return iter(self._tiers.values())

    def add_tier(self, tier: Tier) -> None:
        self._tiers[tier.name] = tier

    def get_tier(self, name: str) -> Tier | None:
        return self._tiers.get(name)

    # --- bulk ---------------------------------------------------------------

    def extend(self, annotations: Iterable[Annotation]) -> None:
        for a in annotations:
            self.add(a)

    # --- misc ---------------------------------------------------------------

    def __repr__(self) -> str:
        return f"MemoryStore(<{len(self)} keys, {sum(len(b) for b in self._buckets.values())} annotations>)"

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, TimeInterval):
            return False
        return _key(key) in self._buckets and bool(self._buckets[_key(key)])
