"""``IntervalAnnotationStore`` — the headline Pythonic API.

A ``MutableMapping[TimeInterval, list[Annotation]]`` facade with methods
named after Allen's relations. See ANN-DOC §C ("a natural design target")
and BACK-DOC §4.1.

The facade hides the index. Phase 0 ships ``MemoryStore`` over
``intervaltree``. Phase 1 adds SQLite + R*Tree (``.annot``) and PostgreSQL
+ ``tstzrange`` GiST. The mapping interface is the same in all three.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from lacing.allen import AllenRelation
from lacing.model import Annotation
from lacing.tier import Tier
from lacing.time import TimeInterval


@runtime_checkable
class IntervalAnnotationStore(Protocol):
    """Protocol for any interval-keyed annotation store.

    Conceptually a ``MutableMapping[TimeInterval, list[Annotation]]``: keys
    are ``TimeInterval``; values are lists because multiple annotations can
    share an interval (different tiers, multiple annotators, soft labels).

    We use ``Protocol`` rather than inheriting from ``MutableMapping`` so
    backends (in-memory, SQLite, Postgres) can structurally conform without
    forcing a single class hierarchy. The mapping methods below match the
    ``MutableMapping`` ABC; concrete backends like :class:`MemoryStore`
    implement the full interface.
    """

    # --- Mapping interface (from MutableMapping) -----------------------------
    # Indexing by TimeInterval returns the annotations at that exact key.
    # For "everything that overlaps t" use .intersects(t).

    def __getitem__(self, key: TimeInterval) -> list[Annotation]: ...
    def __setitem__(self, key: TimeInterval, value: list[Annotation]) -> None: ...
    def __delitem__(self, key: TimeInterval) -> None: ...
    def __iter__(self) -> Iterator[TimeInterval]: ...
    def __len__(self) -> int: ...

    # --- Annotation-level convenience ---------------------------------------

    def add(self, annotation: Annotation) -> None:
        """Append ``annotation`` to the list at its reference interval."""
        ...

    def remove(self, annotation_id) -> Annotation | None:
        """Remove and return the annotation with this id, or None if absent."""
        ...

    def update(self, annotation: Annotation) -> None:
        """Replace the stored annotation that has ``annotation.id``, atomically.

        One commit: a concurrent reader sees the old annotation or the new one,
        never neither (``remove(id)`` then ``add(...)`` leaves a gap in
        between). The replacement may move to a different interval or tier.
        Raises ``KeyError`` when no annotation has that id — use :meth:`add`
        for a new one.
        """
        ...

    def all(self) -> Iterator[Annotation]:
        """Iterate every annotation in the store, order unspecified."""
        ...

    def lock(self, key: str) -> AbstractContextManager[None]:
        """Exclusive lock named ``key``, held for the ``with`` block.

        Scoped to this store's data (for ``PostgresStore``, its owner and
        project): holders of the same key exclude each other, different keys do
        not. The reach of the exclusion is the backend's: ``MemoryStore``
        excludes threads of this process, ``SqliteStore`` also other processes
        on the host, ``PostgresStore`` every client of the database, on any
        host. A holder that dies releases the lock. Not re-entrant.
        """
        ...

    # --- Allen-relation queries ---------------------------------------------
    # Each returns annotations whose reference interval has the named relation
    # to ``query``. ``intersects`` is the union of nine non-disjoint relations.

    def intersects(self, query: TimeInterval) -> Iterator[Annotation]:
        """Annotations whose interval shares any time with ``query``."""
        ...

    def during(self, query: TimeInterval) -> Iterator[Annotation]:
        """Annotations whose interval is strictly inside ``query`` (Allen ``d``)."""
        ...

    def contains(self, query: TimeInterval) -> Iterator[Annotation]:
        """Annotations whose interval strictly contains ``query`` (Allen ``di``)."""
        ...

    def overlaps(self, query: TimeInterval) -> Iterator[Annotation]:
        """Strict Allen ``o``: ``a.start < q.start < a.end < q.end``."""
        ...

    def meets(self, query: TimeInterval) -> Iterator[Annotation]:
        """Allen ``m``: ``a.end == q.start``."""
        ...

    def starts(self, query: TimeInterval) -> Iterator[Annotation]:
        """Allen ``s``: same start, earlier end."""
        ...

    def finishes(self, query: TimeInterval) -> Iterator[Annotation]:
        """Allen ``f``: later start, same end."""
        ...

    def equals(self, query: TimeInterval) -> Iterator[Annotation]:
        """Allen ``=``: identical interval."""
        ...

    def relate(
        self, query: TimeInterval, relations: Iterable[AllenRelation]
    ) -> Iterator[Annotation]:
        """Annotations whose interval has any of the named ``relations`` to ``query``.

        Generic dispatch — useful when relations are computed at runtime.
        """
        ...

    # --- Tier filters --------------------------------------------------------

    def by_tier(self, tier_name: str) -> Iterator[Annotation]:
        """All annotations on ``tier_name``, regardless of interval."""
        ...

    def at_tier(self, tier_name: str, query: TimeInterval) -> Iterator[Annotation]:
        """Annotations on ``tier_name`` that intersect ``query``."""
        ...

    # --- Tier registry -------------------------------------------------------

    def tiers(self) -> Iterator[Tier]:
        """Registered tiers. Annotations may reference tiers not yet registered;
        callers decide whether that's an error."""
        ...

    def add_tier(self, tier: Tier) -> None: ...
    def get_tier(self, name: str) -> Tier | None: ...

    # --- Bulk -----------------------------------------------------------------

    def extend(self, annotations: Iterable[Annotation]) -> None:
        """Add many; equivalent to repeated ``.add`` but adapters can optimize."""
        ...
