"""Content digests over an annotation's *value* — the freshness primitive.

lacing has **three** digests and they answer **three different questions**.
Collapsing any two of them is a silent correctness bug, so the boundary is
spelled out here and cross-referenced from the other two:

- :func:`lacing.hash_bytes` / :func:`lacing.hash_file` — SHA-256 over an
  **artifact's bytes**. Answers *"are these two files the same file?"*. This
  is the ``Artifact.asset_id`` contract (:mod:`lacing.artifact`).
- :func:`lacing.server.etag.annotation_etag` — BLAKE2b-128 over the **whole
  annotation**, ``id`` and ``provenance`` included. Answers *"has this record
  been touched since I read it?"*. This is the ``If-Match`` / HTTP 412
  optimistic-concurrency primitive, and it is *deliberately* unstable across
  regenerations.
- :func:`annotation_value_digest` (this module) — SHA-256 over an annotation's
  **value**, ``id`` and ``provenance`` excluded. Answers *"did the answer
  actually change?"*. This is the freshness / early-cutoff primitive.

A regeneration that produces byte-identical content mints a fresh ``uuid4``
``id`` and a fresh ``provenance.generated_at_time``, so ``annotation_etag``
changes while ``annotation_value_digest`` does not. That difference is the
entire point: it lets a downstream freshness check key on *upstream output
values* rather than on *upstream keys*, and stop propagating invalidation
when nothing actually changed.

Why this lives in core and not under ``lacing/server/``
--------------------------------------------------------
``annotation_etag`` sits at ``lacing/server/etag.py``. Its own imports are
cheap, but importing any submodule of ``lacing.server`` executes
``lacing/server/__init__.py``, which imports the FastAPI app. The value
digest is consumed by the *execution* tier (``nw``, ``falaw``), which must
not drag a web framework in. This module therefore has **no runtime imports
beyond the standard library** — the :class:`~lacing.model.Annotation` import
is type-checking only.

The inclusion boundary — and why each call was made
----------------------------------------------------
Getting this boundary wrong is a silent wrong-cache-**hit**, not a miss, so
each field is justified rather than assumed.

**Included** (:data:`VALUE_FIELDS`):

- ``body`` — it *is* the annotation's value. Trivially included.
- ``body_schema_uri`` — the same ``dict`` means different things under
  different schemas, and a schema-version bump is a semantic change even when
  the payload bytes are unchanged. Excluding it would let a ``.../v1`` body
  satisfy a ``.../v2`` consumer's cache lookup.
- ``tier`` — the tier is part of what the annotation asserts (which layer of
  the analysis this claim belongs to), and lacing's tier stereotypes impose
  structural constraints. Two identical bodies on different tiers are
  different claims.
- ``reference`` — what the annotation is *about*: the asset and the interval.
  Re-timing an annotation changes its value. This is the one genuinely
  contested call (see below); it is included here and excluded from
  :func:`annotation_body_digest`, so the consumer chooses rather than guesses.
- ``confidence`` — a soft label whose confidence moved is a changed assertion.
  Downstream thresholding consumes it directly.

**Excluded**:

- ``id`` — a fresh ``uuid4`` on every regeneration. Including it makes the
  digest change unconditionally, which is exactly the ``annotation_etag``
  behaviour this function exists to avoid.
- ``provenance`` — ``generated_at_time`` changes on every run, and
  ``was_generated_by`` / ``was_derived_from`` describe *how* the value was
  reached, not *what* it is. Two byte-identical answers produced by different
  activities are the same answer. (If a consumer needs to invalidate on a
  changed producer, that belongs in its **cache key** — which is keyed on
  inputs — not in the **value digest**, which addresses the output.)

Rule of thumb, stated once: *key the cache on inputs; address the value by
content; record both in the trace.* A system with only the first cannot cut
off early.

``reference``: two functions, not a boolean
--------------------------------------------
Whether ``reference`` belongs in a value digest is genuinely
consumer-dependent. A :class:`~lacing.model.MediaRef` carries an
``interval``, so re-timing busts every downstream digest — **correct** when
downstream consumes the timing (an animatic, a cut list), **wasteful** when
it consumes only the body (a caption translation). Rather than a boolean flag
or a wrong guess that needs migrating later, this module ships both:

- :func:`annotation_value_digest` — the full value, ``reference`` included.
  **The default.** Use it unless you can state why the rest is irrelevant.
- :func:`annotation_body_digest` — ``{body, body_schema_uri}`` only.

**Be precise about what the narrow one drops, because "re-timing" undersells
it.** ``annotation_body_digest`` drops the *entire* ``reference`` — the asset
identity as well as the interval — plus ``tier`` and ``confidence``. Two
annotations carrying the same body over **different assets** digest alike
under it. Reach for it only when the consumer depends on nothing but what the
annotation *says*.

They are domain-separated (see :data:`VALUE_DIGEST_SCHEME`), so the two can
never collide even on an annotation whose payloads coincide.

Stability guarantees, and their limits
---------------------------------------
The digest is stable **across processes**, **across dict insertion order**
(``sort_keys=True`` canonicalises recursively) and **across a store
round-trip** (memory → ``.annot`` → memory).

The safety claim, stated precisely
-----------------------------------
**For a body that honours the ``body`` contract — i.e. contains only JSON
types, which is what validating against JSON Schema means — this digest never
returns a wrong cache *hit*.** Two annotations with different values never
digest alike. It can return a spurious *miss*; that only costs a recompute.

That claim is bounded by the contract, and it is worth knowing exactly where
the boundary is, because an unbounded version of it would be false:

1. **Non-``str`` mapping keys raise** :class:`NonStringBodyKeyError`.
   ``model_dump(mode="json")`` coerces keys to strings, so a body like
   ``{1: "a", "1": "b"}`` collapses to ``{"1": "b"}`` — an entire entry is
   annihilated, and two bodies differing only in the annihilated entry would
   digest **alike**. That is a wrong hit, so it is refused rather than
   documented. Such a body is already broken data: it does not survive a
   round-trip through any lacing store either (JSON object keys are strings).
2. **Python container types that JSON cannot distinguish digest alike** —
   ``(1, 2)`` and ``[1, 2]`` both serialise to ``[1, 2]``. This is *not* a
   wrong hit within the contract: as JSON they are the same value, and a
   contract-honouring body cannot contain a tuple. A ``set`` additionally
   serialises in an order not stable across processes (a spurious miss), and
   a type pydantic cannot serialise at all raises
   ``PydanticSerializationError`` rather than digesting a ``repr`` that embeds
   a memory address.
3. **Equal-but-differently-serialised rationals digest differently.**
   :class:`~lacing.time.RationalTime` serialises as ``{"v": …, "r": …}``, so
   ``RationalTime(1, 24)`` and ``RationalTime(2, 48)`` compare **equal** but
   digest differently — a rate change moves the digest even when the instant
   is unchanged. This is a spurious *miss*. (``annotation_etag`` has the same
   property.)

Changing :data:`VALUE_FIELDS` or the canonicalisation is a **breaking cache
invalidation event** for every consumer: every digest changes at once. Bump
the scheme string when you do it, so the change is legible in a trace.

Verifying a recorded digest: use :func:`value_digest_matches`
-------------------------------------------------------------
Which body fields ``v2`` leaves out depends on the :class:`lacing.Derived`
markers registered when the digest is computed, so a recorded digest is checked
with :func:`value_digest_matches`, whose docstring says what it accepts and why
(lacing#89).

The verifier must register the same markers as the producer, or the producer
none; otherwise a match it should find reads changed (a spurious miss, never a
wrong hit). So a marker *added to a schema that already had one* is a spurious
miss, unless the trace recorded the exclusion set.

A digest of the exclusion set in the scheme tag would not help: a trace records
one scheme for parents of many body schemas. A trace that records each entry's
exclusion set ``D'`` itself can verify under it, through
``resolve_derived=lambda uri: D'``, but only while ``D'`` is a subset of today's
derived paths: a marker since removed means the field now counts, and verifying
under the old ``D'`` would be a wrong hit. That is a trace-format concern for
consumers.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable, Collection, Iterator, Mapping
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from lacing.model import Annotation


__all__ = [
    "annotation_value_digest",
    "annotation_body_digest",
    "value_digest_matches",
    "accepted_value_digests",
    "NonStringBodyKeyError",
    "VALUE_FIELDS",
    "BODY_FIELDS",
    "VALUE_DIGEST_SCHEME",
    "VALUE_DIGEST_SCHEMES",
    "BODY_DIGEST_SCHEME",
    "MAX_MIXED_BYTES",
    "MAX_MIXED_FILLS",
    "registered_prefills",
    "registered_derived_paths",
]

#: What ``resolve_derived`` returns for a ``body_schema_uri``: the derived paths,
#: or a ``Mapping`` of each path to the value its field holds before the fill
#: (a pre-fill value that is not JSON is tried as ``None``).
DerivedResolver = Callable[
    [str], Collection[Sequence[str | None]] | Mapping[Sequence[str | None], Any]
]


class NonStringBodyKeyError(TypeError):
    """An annotation ``body`` contains a mapping key that is not a ``str``.

    JSON object keys are strings, so ``model_dump(mode="json")`` coerces
    non-string keys — and two distinct keys can coerce to the *same* string,
    silently annihilating an entry. ``{1: "a", "1": "b"}`` dumps to
    ``{"1": "b"}``; a body differing only in the lost entry would digest
    identically, which is a wrong cache **hit**.

    Since lacing#24 the *envelope* refuses such a body at validation — the
    producer-side fix. This error lives here rather than in ``lacing.model``
    because this module is deliberately import-light (stdlib only, pinned by
    test) and the model can import from it, not vice versa.
    """


def reject_non_string_keys(value: Any, path: str = "body") -> None:
    """Raise :class:`NonStringBodyKeyError` for any non-``str`` mapping key.

    Walks nested mappings and sequences, because the key-collapse hazard is
    just as real one level down: ``{"k": {1: "a", "1": "b"}}`` loses an entry
    exactly the same way. ``path`` is threaded through so the error names the
    offending location rather than just the annotation.

    The single implementation behind two enforcement points: the
    ``Annotation.body`` validator (the primary gate, lacing#24) and this
    module's pre-digest re-check (defense-in-depth — ``model_copy`` /
    ``model_construct`` bypass validators, and a wrong digest is a wrong
    cache *hit*).
    """
    if isinstance(value, dict):
        for key, sub in value.items():
            if not isinstance(key, str):
                raise NonStringBodyKeyError(
                    f"{path} has a non-str key {key!r} of type "
                    f"{type(key).__name__}. JSON object keys are strings, so "
                    f"this key would be coerced — and a coercion collision "
                    f"silently drops an entry, which would make two different "
                    f"annotations digest alike. Fix the producer so the body "
                    f"contains only JSON types."
                )
            reject_non_string_keys(sub, f"{path}[{key!r}]")
    elif isinstance(value, (list, tuple)):
        for index, sub in enumerate(value):
            reject_non_string_keys(sub, f"{path}[{index}]")


VALUE_FIELDS: tuple[str, ...] = (
    "body",
    "body_schema_uri",
    "confidence",
    "reference",
    "tier",
)
"""Annotation fields that constitute its *value*. See the module docstring for
why each is in, and why ``id`` and ``provenance`` are out."""

BODY_FIELDS: tuple[str, ...] = ("body", "body_schema_uri")
"""The narrower payload for :func:`annotation_body_digest`.

Note what this drops, which is more than timing: the **entire** ``reference``
(*which asset* / *which node* / *which annotation*, not just *when*), plus
``tier`` and ``confidence``. Two annotations over different assets digest
alike here."""

VALUE_DIGEST_SCHEME = "lacing/annotation-value-digest/v2"
"""Domain-separation tag mixed into :func:`annotation_value_digest` by default.

``v2`` leaves the body's :class:`lacing.Derived` fields out (see
:mod:`lacing.derived`); ``v1`` digested the whole body. A trace that recorded a
``v1`` digest is still verifiable: pass ``scheme="lacing/annotation-value-digest/v1"``.
Verify a recorded digest with :func:`value_digest_matches`, not by recomputing it."""

_V1_SCHEME = "lacing/annotation-value-digest/v1"

VALUE_DIGEST_SCHEMES: tuple[str, ...] = (_V1_SCHEME, VALUE_DIGEST_SCHEME)
"""Every scheme :func:`annotation_value_digest` can compute, oldest first. Only
the latest excludes derived fields."""

MAX_MIXED_BYTES = 1_500_000
"""Default budget of bytes :func:`value_digest_matches` digests over mixed-state
bodies (lacing#161), beside :data:`MAX_MIXED_FILLS`: each candidate is a whole
canonical dump of the body plus a SHA-256, so the count alone made a miss cost
the body's size times 1024 (2.15 s at 5000 images). A miss tries at most
``MAX_MIXED_BYTES // len(body)`` candidates (at least one), so a small body
still gets the whole count and a large one a bounded cost, about 50 ms with the
default. ``None`` is no byte budget."""

MAX_MIXED_FILLS = 1024
"""Default budget of mixed-state bodies :func:`value_digest_matches` tries
(lacing#152, lacing#157): a body whose derived fields were filled one
occurrence at a time was recorded with each occurrence in its own state (as
now, absent, ``null``, at its pre-fill value), and every combination is a
candidate. There are ``3**n`` of them or more, so they are tried likeliest
first (see :func:`value_digest_matches`), and at most this many.

What it reaches, by enumeration, counting only the images filled now (those
still ``null`` now are held as they are): with a ``null`` pre-fill (artful's
``PanelImage``), a trace recorded before a panel's last fill on up to 1024
images when that image was ``null`` then, 512 when absent; before its last two
on up to 43 when both were ``null``, 22 when one was absent and one ``null``;
before its last three, all ``null``, on up to 15. A non-null pre-fill adds a
state per image: 512, 341, 31, 15 and 11. Past the budget, a body recorded in
a less likely state reads as changed: a spurious miss, never a wrong hit. An
occurrence ``null`` now but absent when recorded is moved only after every
combination of the filled ones, so with seven or more filled images it is past
the budget.

Cost: a miss computes up to this many more digests, each over the whole body
(about 0.45 s at 1,000 images)."""

BODY_DIGEST_SCHEME = "lacing/annotation-body-digest/v1"
"""Domain-separation tag mixed into :func:`annotation_body_digest`."""


def annotation_value_digest(
    annotation: "Annotation",
    *,
    scheme: str = VALUE_DIGEST_SCHEME,
    resolve_derived: DerivedResolver | None = None,
) -> str:
    """Return the SHA-256 hex digest of ``annotation``'s value.

    Covers ``body``, ``body_schema_uri``, ``tier``, ``reference`` and
    ``confidence``. Excludes ``id`` and ``provenance``, so a regeneration that
    produces identical content produces an identical digest. Also excludes the
    body's :class:`lacing.Derived` fields (scheme ``v2`` onwards): a value
    derivable from another field of the body does not change what a render reads.

    A body with no derived fields (no marker, or a schema that is not
    registered) digests exactly as under ``v1``, so only marked schemas change
    digest. To check a digest a trace recorded, call :func:`value_digest_matches`.

    ``scheme`` selects which computation to run, so a digest recorded under an
    older scheme can be re-verified (see :data:`VALUE_DIGEST_SCHEMES`).
    ``resolve_derived`` maps a ``body_schema_uri`` to the paths to leave out; the
    default reads the registered body schema (:func:`registered_prefills`), and
    a schema that is not registered excludes nothing. It may return a plain
    collection of paths, or a ``Mapping`` of path to pre-fill value: the value
    an unfilled field holds, which :func:`value_digest_matches` tries besides
    ``None`` (a collection means ``None`` for each).

    Use this for freshness and early cutoff. For optimistic concurrency use
    :func:`lacing.server.etag.annotation_etag` instead — two digests, two
    jobs, and neither substitutes for the other.

    >>> from uuid import uuid4
    >>> from lacing import Annotation, MediaRef, Provenance
    >>> from lacing import RationalTime, TimeInterval
    >>> def make(**kw):
    ...     base = dict(
    ...         id=uuid4(),
    ...         tier="words",
    ...         reference=MediaRef(
    ...             asset_id="sha256:abc",
    ...             interval=TimeInterval(RationalTime(0), RationalTime(24000)),
    ...         ),
    ...         body={"text": "hello"},
    ...         body_schema_uri="annot://schema/word/v1",
    ...         provenance=Provenance(
    ...             was_generated_by="agent:m@1",
    ...             was_attributed_to="thor",
    ...             generated_at_time=RationalTime.now(),
    ...         ),
    ...     )
    ...     base.update(kw)
    ...     return Annotation(**base)

    A regeneration — new ``id``, new timestamp, same content — digests the same:

    >>> a = make()
    >>> b = make(provenance=Provenance(
    ...     was_generated_by="agent:m@1",
    ...     was_attributed_to="thor",
    ...     generated_at_time=RationalTime(999),
    ... ))
    >>> annotation_value_digest(a) == annotation_value_digest(b)
    True

    A changed body does not:

    >>> annotation_value_digest(make(body={"text": "goodbye"})) == (
    ...     annotation_value_digest(a)
    ... )
    False
    """
    return next(_value_digests(annotation, scheme, resolve_derived))


def value_digest_matches(
    annotation: "Annotation",
    recorded: str,
    *,
    scheme: str = VALUE_DIGEST_SCHEME,
    resolve_derived: DerivedResolver | None = None,
    max_mixed_fills: int = MAX_MIXED_FILLS,
    max_mixed_bytes: int | None = MAX_MIXED_BYTES,
) -> bool:
    """Whether ``recorded``, a value digest a trace stored under ``scheme``, still
    describes ``annotation``'s value.

    The check a freshness verifier makes, instead of comparing
    :func:`annotation_value_digest` with ``recorded`` by hand. Besides the
    digest computed now, it accepts the ones a producer that did not know the
    body's :class:`lacing.Derived` paths (no marker yet, or schema not
    registered) would have recorded for the same value, all ``v1``-tagged: the
    whole current body (nothing changed since); the current body with the
    derived fields dropped (they were absent then and have been filled since,
    the change ``v2`` exists to ignore); and the current body with the derived
    fields set to ``None``, or to their pre-fill values (they were stored that
    way then: by default the JSON default each field declares, which is what a
    ``model_dump()`` stores for a plain default, not for a ``default_factory``,
    which declares none, nor through a ``field_serializer``).
    It does so under ``v1`` as well, where the whole-body digest is the computed
    one: which fields are derivable belongs to the schema, not to the scheme.

    None of these is a wrong cache hit. With ``D`` today's derived paths, the
    whole-body digest matches only if the recorded body *is* the current one,
    the dropped one only if it is the current body minus ``D``, and the filled
    ones only if it is the current body with ``D`` set to ``None`` or to the
    pre-fill values. Dropping and filling touch nothing outside ``D``, so either
    way the two bodies agree outside ``D``, which is exactly what the ``v2``
    digest already accepts. ``resolve_derived`` is as in
    :func:`annotation_value_digest`.

    Derived fields filled one occurrence at a time (each image of a panel)
    leave bodies recorded in **mixed** states: one occurrence filled, another
    ``null``, a third absent. Those are accepted too, each occurrence in any of
    its states (lacing#152), and for the same reason: every mix agrees with the
    current body outside ``D``. They are tried last, likeliest first
    (lacing#157): moving only the occurrences filled now before moving those
    still ``null`` or at their pre-fill, fewest occurrences moved first, each
    at its pre-fill value before ``null`` before absent; and at most
    ``max_mixed_fills`` of them (:data:`MAX_MIXED_FILLS`), and no more than
    ``max_mixed_bytes`` of canonical JSON in all (:data:`MAX_MIXED_BYTES`, so a
    body of a thousand occurrences costs about 50 ms, not seconds). A body
    recorded in a state past either budget reads as changed.

    >>> from uuid import uuid4
    >>> from lacing import Annotation, MediaRef, Provenance
    >>> from lacing import RationalTime, TimeInterval
    >>> def make(body):
    ...     return Annotation(
    ...         id=uuid4(), tier="panels",
    ...         reference=MediaRef(
    ...             asset_id="sha256:abc",
    ...             interval=TimeInterval(RationalTime(0), RationalTime(24000)),
    ...         ),
    ...         body=body,
    ...         body_schema_uri="annot://schema/panel/v1",
    ...         provenance=Provenance(
    ...             was_generated_by="agent:m@1",
    ...             was_attributed_to="thor",
    ...             generated_at_time=RationalTime.now(),
    ...         ),
    ...     )
    >>> recorded = annotation_value_digest(make({"artifact_id": "a1"}))

    The schema then gains a marker (``asset_id`` derives from ``artifact_id``),
    and the derived field is filled:

    >>> marked = lambda uri: {("asset_id",)}
    >>> filled = make({"artifact_id": "a1", "asset_id": "sha256:h"})
    >>> annotation_value_digest(filled, resolve_derived=marked) == recorded
    False
    >>> value_digest_matches(filled, recorded, resolve_derived=marked)
    True
    >>> value_digest_matches(
    ...     make({"artifact_id": "a2"}), recorded, resolve_derived=marked
    ... )
    False
    """
    return recorded in _value_digests(
        annotation,
        scheme,
        resolve_derived,
        max_mixed_fills=max_mixed_fills,
        max_mixed_bytes=max_mixed_bytes,
    )


def accepted_value_digests(
    annotation: "Annotation",
    *,
    scheme: str = VALUE_DIGEST_SCHEME,
    resolve_derived: DerivedResolver | None = None,
    max_mixed_fills: int = MAX_MIXED_FILLS,
    max_mixed_bytes: int | None = MAX_MIXED_BYTES,
) -> frozenset[str]:
    """Every digest :func:`value_digest_matches` accepts for ``annotation``.

    For a verifier that memoizes per annotation and scheme and checks many
    recorded digests against one set; ``value_digest_matches`` stays the lazy
    one-off check. ``resolve_derived``, ``max_mixed_fills`` and ``max_mixed_bytes``
    are as in :func:`value_digest_matches`.
    """
    return frozenset(
        _value_digests(
            annotation,
            scheme,
            resolve_derived,
            max_mixed_fills=max_mixed_fills,
            max_mixed_bytes=max_mixed_bytes,
        )
    )


def annotation_body_digest(annotation: "Annotation") -> str:
    """Return the SHA-256 hex digest of ``{body, body_schema_uri}`` only.

    The narrow sibling of :func:`annotation_value_digest`. It drops the
    **entire** ``reference`` — *which asset* / *which node* / *which
    annotation*, not merely *when* — plus ``tier`` and ``confidence``. So the
    same caption over two **different assets** digests identically here, as
    does the same body asserted on two different tiers or at two different
    confidences.

    That is a correctness bug in any consumer that reads any of those. Reach
    for it only when the consumer demonstrably depends on nothing but what the
    annotation *says*; prefer :func:`annotation_value_digest` otherwise.

    >>> from uuid import uuid4
    >>> from lacing import Annotation, MediaRef, Provenance
    >>> from lacing import RationalTime, TimeInterval
    >>> def over(asset):
    ...     return Annotation(
    ...         id=uuid4(), tier="words",
    ...         reference=MediaRef(
    ...             asset_id=asset,
    ...             interval=TimeInterval(RationalTime(0), RationalTime(24000)),
    ...         ),
    ...         body={"text": "hello"},
    ...         body_schema_uri="annot://schema/word/v1",
    ...         provenance=Provenance(
    ...             was_generated_by="agent:m@1",
    ...             was_attributed_to="thor",
    ...             generated_at_time=RationalTime.now(),
    ...         ),
    ...     )

    Different **assets**, identical body digest — this is the footgun:

    >>> annotation_body_digest(over("sha256:interview")) == (
    ...     annotation_body_digest(over("sha256:broadcast"))
    ... )
    True
    >>> annotation_value_digest(over("sha256:interview")) == (
    ...     annotation_value_digest(over("sha256:broadcast"))
    ... )
    False

    >>> from uuid import uuid4
    >>> from lacing import Annotation, MediaRef, Provenance
    >>> from lacing import RationalTime, TimeInterval
    >>> def make(interval):
    ...     return Annotation(
    ...         id=uuid4(),
    ...         tier="words",
    ...         reference=MediaRef(asset_id="sha256:abc", interval=interval),
    ...         body={"text": "hello"},
    ...         body_schema_uri="annot://schema/word/v1",
    ...         provenance=Provenance(
    ...             was_generated_by="agent:m@1",
    ...             was_attributed_to="thor",
    ...             generated_at_time=RationalTime.now(),
    ...         ),
    ...     )
    >>> early = make(TimeInterval(RationalTime(0), RationalTime(24000)))
    >>> late = make(TimeInterval(RationalTime(24000), RationalTime(48000)))
    >>> annotation_body_digest(early) == annotation_body_digest(late)
    True
    >>> annotation_value_digest(early) == annotation_value_digest(late)
    False
    """
    return _digest(BODY_DIGEST_SCHEME, _payload(annotation, BODY_FIELDS))


def registered_prefills(uri: str) -> Mapping[tuple[str | None, ...], Any]:
    """The :class:`lacing.Derived` paths of the body schema registered at ``uri``,
    each mapped to its pre-fill value (:func:`lacing.derived_prefills`): the
    default ``resolve_derived`` of :func:`annotation_value_digest` and
    :func:`value_digest_matches` (lacing#109).

    Empty for an unregistered ``uri``, as :func:`registered_derived_paths`.
    """
    from lacing.derived import derived_prefills
    from lacing.schema import UnknownBodySchemaError, get_body_schema

    try:
        model = get_body_schema(uri)
    except UnknownBodySchemaError:
        return {}
    return derived_prefills(model)


def registered_derived_paths(uri: str) -> frozenset[tuple[str | None, ...]]:
    """The :class:`lacing.Derived` paths of the body schema registered at ``uri``:
    the paths-only form of :func:`registered_prefills`.

    Empty for an unregistered ``uri``: excluding less can only cost a spurious
    miss, never a wrong hit. Imports :mod:`lacing.schema` on first use, so this
    module stays stdlib-only at import time.
    """
    from lacing.schema import body_derived, is_registered

    return body_derived(uri) if is_registered(uri) else frozenset()


# --- internals ---------------------------------------------------------------


def _value_digests(
    annotation: "Annotation",
    scheme: str,
    resolve_derived: DerivedResolver | None,
    *,
    max_mixed_fills: int = MAX_MIXED_FILLS,
    max_mixed_bytes: int | None = MAX_MIXED_BYTES,
) -> Iterator[str]:
    """The digest of ``annotation`` under ``scheme``, then (lazily) the digests a
    producer unaware of the derived paths would have recorded under the same tag
    for the same value. See :func:`value_digest_matches` for why those are safe.

    The first digest costs what it always did: the body is dropped in place, and
    the whole body is dumped again only when a caller asks for a fallback."""
    if scheme not in VALUE_DIGEST_SCHEMES:
        raise ValueError(
            f"unknown value digest scheme {scheme!r}; known: {VALUE_DIGEST_SCHEMES}"
        )
    payload = _payload(annotation, VALUE_FIELDS)
    is_v1 = scheme == _V1_SCHEME
    if is_v1:  # v1 digests the whole body, and never consults the resolver for it
        yield _digest(_V1_SCHEME, payload)
    paths = (resolve_derived or registered_prefills)(annotation.body_schema_uri)
    if not paths:  # nothing to leave out: byte-identical to v1
        if not is_v1:
            yield _digest(_V1_SCHEME, payload)
        return
    from lacing.derived import fill_paths

    # A pre-fill that is not JSON (a datetime) cannot be in a recorded body:
    # try null for it instead.
    prefills = {
        tuple(path): prefill if _is_json(prefill) else None
        for path in paths
        for prefill in [paths[path] if isinstance(paths, Mapping) else None]
    }
    dropped = _pop_entries(payload["body"], prefills)  # private dump: edit it
    if not is_v1:
        yield _digest(VALUE_DIGEST_SCHEME, payload)
        yield _digest(_V1_SCHEME, _payload(annotation, VALUE_FIELDS))  # unchanged
    if not dropped:  # no derived field present: every fallback is the whole body
        return
    yield _digest(_V1_SCHEME, payload)  # derived fields absent when recorded
    seen = set()  # the null and pre-fill bodies coincide when every occurrence
    # present is of a path whose pre-fill is null: yield that body's digest once
    for fills in _distinct_fills(prefills):  # derived fields stored as null, or
        filled = _payload(annotation, VALUE_FIELDS)  # at their default, then
        if fill_paths(filled["body"], fills):  # else it is the whole body again
            digest = _digest(_V1_SCHEME, filled)
            if digest not in seen:
                seen.add(digest)
                yield digest
    # last, each occurrence in its own state, editing the dropped dump in place
    limit = _mixed_limit(payload, dropped, max_mixed_fills, max_mixed_bytes)
    for mixed in _mixed_fills(payload, dropped, limit=limit):
        yield _digest(_V1_SCHEME, mixed)


def _mixed_limit(
    payload: dict, dropped: list, max_fills: int, max_bytes: int | None
) -> int:
    """How many mixed-state bodies to try: ``max_fills``, cut so that digesting
    them is about ``max_bytes`` of canonical JSON (one body's size is the cost
    of each; at least one is tried). Costs one dump, only when a mix exists."""
    if max_bytes is None or len(dropped) < 2 or max_fills < 1:
        return max_fills
    size = len(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return min(max_fills, max(1, max_bytes // max(size, 1)))


def _is_json(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def _pop_entries(body: dict, prefills: dict) -> list[tuple]:
    """Delete in place every entry of ``body`` a path of ``prefills`` names (as
    :func:`lacing.derived.drop_paths` does), and return each as
    ``(container, key, value, prefill)``, path by path, each in document order."""
    from lacing.derived import occurrences

    dropped = []
    # Shortest paths first: when a custom resolver names both an entry and one
    # inside it, the outer one is popped first, and the inner is then gone.
    for path, prefill in sorted(prefills.items(), key=lambda item: len(item[0])):
        for *parents, key in occurrences(body, path):
            container = _get(body, parents)
            dropped.append((container, key, container.pop(key), prefill))
    return dropped


_ABSENT = object()
"""The state of an occurrence recorded without its key (every other state is
the value it held)."""


def _mixed_fills(payload: dict, dropped: list, *, limit: int) -> Iterator[dict]:
    """``payload``, whose derived entries ``dropped`` were removed, with each of
    them in its own state: as now, absent, ``None``, or its path's pre-fill
    value. Only the mixed combinations (the bodies of the uniform ones were
    tried before), at most ``limit`` of them, the likeliest first, so a miss
    costs ``limit`` digests, never ``3**n``.

    Likeliest first (lacing#157): the occurrences filled now (not ``None``, not
    at their pre-fill) are where a late fill happened, so the combinations that
    move only those come first, each other occurrence held as now (still
    ``null`` or at its pre-fill now, it most likely was then too); then those
    that also move the others. Each in :func:`_by_distance` order.

    ``payload`` is edited in place from one combination to the next, only where
    an occurrence's state changes, so each yield is valid only until the next
    (the caller digests it at once)."""
    same_json = _memoized_same_json()

    if len(dropped) < 2 or limit < 1:  # one site: every combination is uniform
        return
    options = [_states(value, prefill, same_json) for _, _, value, prefill in dropped]

    def uniform(fills: Sequence) -> dict[int, Any]:
        """The combination a uniform fill leaves the sites in: each at the
        state equal to its fill, else as now (it already held it)."""
        return {
            i: state
            for i, (states, fill) in enumerate(zip(options, fills))
            for state in states
            if same_json(state, fill)
        }

    n = len(dropped)
    tried = [
        uniform([_ABSENT] * n),
        uniform([None] * n),
        uniform([prefill for *_, prefill in dropped]),
    ]
    filled = [
        i
        for i, (_, _, value, prefill) in enumerate(dropped)
        if value is not None and not same_json(value, prefill)
    ]
    unfilled = set(range(n)).difference(filled)
    first = (
        {filled[j]: state for j, state in combo.items()}
        for combo in _by_distance([options[i] for i in filled], same=same_json)
    )
    then = (
        combo
        for combo in _by_distance(options, same=same_json)
        if not unfilled.isdisjoint(combo)
    )
    combos = itertools.chain(first, then if unfilled else ())

    def place(i: int, state: Any) -> None:
        container, key, *_ = dropped[i]
        if state is _ABSENT:
            del container[key]
        else:
            container[key] = state

    for container, key, value, _ in dropped:  # start from the body as now
        container[key] = value
    applied: dict[int, Any] = {}  # the sites ``payload`` holds off "as now"
    for combo in itertools.islice((c for c in combos if c not in tried), limit):
        for i in applied.keys() - combo.keys():
            place(i, dropped[i][2])
        for i, state in combo.items():
            if i not in applied or applied[i] is not state:
                place(i, state)
        applied = combo
        yield payload


def _by_distance(
    options: Sequence[Sequence],
    *,
    same: Callable[[Any, Any], bool],
) -> Iterator[dict[int, Any]]:
    """Every combination of the sites' states other than "all as now", each as
    ``{site: state}`` for the sites it moves off "as now"; ``options[i]`` lists
    the states site ``i`` may be moved to, likeliest first.

    Fewest sites moved first: a trace recorded just before the last fill or two
    (the common case, lacing#157) is reached after about ``n`` or ``n**2``
    bodies, not ``3**n``. At each distance, the combinations whose moved sites
    share one state (``same``) come before those mixing states (one absent, one
    ``null``: images appended by different writers), the states taken in the
    order the sites rank them.

    >>> list(_by_distance([["a", "b"], ["a"]], same=lambda x, y: x == y))
    [{0: 'a'}, {1: 'a'}, {0: 'b'}, {0: 'a', 1: 'a'}, {0: 'b', 1: 'a'}]
    """
    forms: list = []  # every distinct state, in the order the sites rank them
    for rank in range(max(map(len, options), default=0)):
        for states in options:
            if rank < len(states) and not any(same(states[rank], f) for f in forms):
                forms.append(states[rank])
    sharing = [
        [(i, s) for i, states in enumerate(options) for s in states if same(s, form)]
        for form in forms
    ]
    for distance in range(1, len(options) + 1):
        for eligible in sharing:
            yield from map(dict, itertools.combinations(eligible, distance))
        for moved in itertools.combinations(range(len(options)), distance):
            for chosen in itertools.product(*(options[i] for i in moved)):
                if not all(same(s, chosen[0]) for s in chosen[1:]):
                    yield dict(zip(moved, chosen))


def _memoized_same_json() -> Callable[[Any, Any], bool]:
    """:func:`lacing.derived.same_json` with each value's canonical key computed
    once (lacing#161): the sites share a handful of objects (``None``, the
    pre-fill, the absent marker) and compare them over and over, so the
    enumeration's set-up was a JSON dump per comparison, 45k of them for a
    panel of a thousand images. A value is kept alive by the cache, so its
    ``id`` is not reused while the comparison runs."""
    from lacing.derived import _json_key

    keys: dict[int, tuple[Any, Any]] = {}

    def key(value: Any) -> Any:
        known = keys.get(id(value))
        if known is None:
            known = keys[id(value)] = (value, _json_key(value))
        return known[1]

    def same(a: Any, b: Any) -> bool:
        return a is b or key(a) == key(b)

    return same


def _states(current: Any, prefill: Any, same: Callable[[Any, Any], bool]) -> list:
    """The states one occurrence may have been recorded in besides its current
    value, likeliest first: its pre-fill value (what ``model_dump()`` writes for
    a plain default), ``None``, absent; one equal to the current value or to an
    earlier one is left out."""
    states: list = []
    for state in (prefill, None, _ABSENT):
        if not any(same(state, other) for other in (current, *states)):
            states.append(state)
    return states


def _get(value: Any, address: Sequence) -> Any:
    for step in address:
        value = value[step]
    return value


def _distinct_fills(prefills: dict) -> list[dict]:
    """The pre-fill bodies worth trying: every derived path ``None`` (a writer
    that stores null), then each at its declared pre-fill value, when that
    differs (a ``model_dump()`` of a field defaulting to ``""``)."""
    nulled = dict.fromkeys(prefills)
    return [nulled] if prefills == nulled else [nulled, prefills]


def _payload(annotation: "Annotation", fields: Sequence[str]) -> dict[str, Any]:
    """Project ``annotation``'s JSON-mode dump onto ``fields``.

    Dumping the whole model once and projecting is deliberate: it routes every
    field through pydantic's JSON serializer, so ``RationalTime`` reaches the
    canonicaliser in its ``{v, r}`` wire form. Hand-assembling the payload from
    raw attributes bypasses that.

    The dump is preceded by :func:`reject_non_string_keys` over the *raw*
    body, because the check has to happen **before** the coercion it exists to
    catch — once dumped, the annihilated entry is already gone.
    """
    # Defense-in-depth, not the primary gate: the envelope validator refuses
    # these at construction (lacing#24), but model_copy/model_construct
    # bypass validators, and a wrong digest here is a wrong cache HIT.
    reject_non_string_keys(annotation.body, "body")
    dumped = annotation.model_dump(mode="json")
    return {field: dumped[field] for field in fields}


def _digest(scheme: str, payload: dict[str, Any]) -> str:
    """SHA-256 hex over ``scheme`` plus the canonical JSON of ``payload``.

    ``sort_keys=True`` canonicalises dict ordering recursively, which is what
    makes the digest independent of insertion order and stable across
    processes. ``scheme`` is a domain-separation tag: without it, two digest
    functions in this module whose payloads happened to coincide would return
    the same hex for different questions.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{scheme}\n{canonical}".encode("utf-8")).hexdigest()
