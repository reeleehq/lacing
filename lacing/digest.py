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
import json
from collections.abc import Callable, Collection, Iterator
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
    "registered_derived_paths",
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

BODY_DIGEST_SCHEME = "lacing/annotation-body-digest/v1"
"""Domain-separation tag mixed into :func:`annotation_body_digest`."""


def annotation_value_digest(
    annotation: "Annotation",
    *,
    scheme: str = VALUE_DIGEST_SCHEME,
    resolve_derived: Callable[[str], Collection[Sequence[str | None]]] | None = None,
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
    default reads the registered body schema (:func:`registered_derived_paths`),
    and a schema that is not registered excludes nothing.

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
    resolve_derived: Callable[[str], Collection[Sequence[str | None]]] | None = None,
) -> bool:
    """Whether ``recorded``, a value digest a trace stored under ``scheme``, still
    describes ``annotation``'s value.

    The check a freshness verifier makes, instead of comparing
    :func:`annotation_value_digest` with ``recorded`` by hand. Besides the
    digest computed now, it accepts the two a producer that did not know the
    body's :class:`lacing.Derived` paths (no marker yet, or schema not
    registered) would have recorded for the same value, both ``v1``-tagged: the
    whole current body (nothing changed since), and the current body with the
    derived fields dropped (they were absent then and have been filled since,
    the change ``v2`` exists to ignore). It does so under ``v1`` as well, where
    the whole-body digest is the computed one: which fields are derivable
    belongs to the schema, not to the scheme.

    None of these is a wrong cache hit. With ``D`` today's derived paths, the
    whole-body digest matches only if the recorded body *is* the current one,
    and the dropped one only if it is the current body minus ``D``. Dropping
    only deletes, so either way the two bodies agree outside ``D``, which is
    exactly what the ``v2`` digest already accepts under ``D``.

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
    return recorded in _value_digests(annotation, scheme, resolve_derived)


def accepted_value_digests(
    annotation: "Annotation",
    *,
    scheme: str = VALUE_DIGEST_SCHEME,
    resolve_derived: Callable[[str], Collection[Sequence[str | None]]] | None = None,
) -> frozenset[str]:
    """Every digest :func:`value_digest_matches` accepts for ``annotation``.

    For a verifier that memoizes per annotation and scheme and checks many
    recorded digests against one set; ``value_digest_matches`` stays the lazy
    one-off check.
    """
    return frozenset(_value_digests(annotation, scheme, resolve_derived))


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


def registered_derived_paths(uri: str) -> frozenset[tuple[str | None, ...]]:
    """The :class:`lacing.Derived` paths of the body schema registered at ``uri``.

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
    resolve_derived: Callable[[str], Collection[Sequence[str | None]]] | None,
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
    paths = (resolve_derived or registered_derived_paths)(annotation.body_schema_uri)
    if not paths:  # nothing to leave out: byte-identical to v1
        if not is_v1:
            yield _digest(_V1_SCHEME, payload)
        return
    dropped_any = _drop_derived(payload["body"], paths)
    if not is_v1:
        yield _digest(VALUE_DIGEST_SCHEME, payload)
        whole = _payload(annotation, VALUE_FIELDS)
        yield _digest(_V1_SCHEME, whole)  # whole body, unchanged since
    if dropped_any:  # else it is the whole-body digest again
        yield _digest(_V1_SCHEME, payload)  # derived fields absent when recorded


def _drop_derived(body: Any, paths: Collection[Sequence[str | None]]) -> bool:
    """Delete ``paths`` from the (already dumped, hence private) ``body`` in place;
    return whether any was there."""
    from lacing.derived import drop_paths

    return drop_paths(body, {tuple(path) for path in paths})


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
