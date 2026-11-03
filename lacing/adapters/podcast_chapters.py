"""Podcasting 2.0 ``podcast:chapters`` JSON adapter.

The JSON chapters format of the Podcast Namespace (version 1.2): a version,
optional episode fields, and a list of chapters, each with a start time and
optional end time, title, image, link, table-of-contents flag and location::

    {
      "version": "1.2.0",
      "author": "John Doe",
      "title": "Episode 7 - Making Progress",
      "chapters": [
        {"startTime": 0, "title": "Intro"},
        {"startTime": 168, "title": "Hearing Aids", "img": "https://example.com/a.jpg"},
        {"startTime": 4826, "toc": false,
         "location": {"name": "Eiffel Tower, Paris", "geo": "geo:48.858093,2.294694"}}
      ]
    }

Spec: "JSON Chapters Format", version 1.2,
https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/examples/chapters/jsonChapters.md,
referenced by the ``<podcast:chapters>`` tag,
https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/tags/chapters.md.

Tiers and bodies:

- ``chapters`` (stereotype ``NONE``; override with ``tier=``): one annotation
  per chapter, body ``annot://schema/podcast-chapter/v1``: every field of the
  chapter object except ``startTime`` and ``endTime``, with its value and in
  file order (``title``, ``img``, ``url``, ``toc``, ``location``, and any
  field the spec does not name, such as the ``value`` of the spec's complex
  example), so a chapter round-trips to the same JSON value (see "Numbers").
  A ``null`` ``title``, ``img``, ``url``, ``toc`` or ``location`` is an
  absent one: it is left out on load, and the dump leaves it out too.
  ``"end_inferred": true`` is added when the chapter had no ``endTime`` (a
  chapter that already has a field of that name is refused).
- ``episode`` (stereotype ``NONE``; override with ``episode_tier=``):
  **one** metadata annotation, a point at time 0, body
  ``annot://schema/podcast-chapters-episode/v1``
  ``{"version": str | None, "fields": {...}}``, where ``fields`` holds every
  other top-level field (``author``, ``title``, ``podcastName``,
  ``description``, ``fileName``, ``waypoints``, and any unnamed one) with
  its value and in file order. These describe the file, not a chapter, so they live on
  one annotation rather than in every chapter body, the way the LRC adapter
  keeps its ID tags; a store from another format dumps without inventing any.

End times:
    ``endTime`` is optional, and ``null`` is the same as absent. A chapter
    without one ends where the next *later*
    chapter starts (chapters sharing a start all end at the next later
    start), whatever the order of the file (the spec assumes ascending
    ``startTime``); the last chapter is a point (``start == end``).
    :func:`dump` leaves ``endTime`` out again for a chapter whose end was
    inferred and is still the one a reader would infer, and writes it
    otherwise, so a file round-trips and an edited end is kept.

Time discipline:
    Times are JSON numbers of seconds ("float precision" in the spec). They
    are read as exact ``Decimal`` values (``json.loads(...,
    parse_float=Decimal)``, never ``float``), then converted exactly to
    ``RationalTime``. With ``rate=None`` (the default) the rate is the
    smallest power of ten, at least 1000, that holds every time in the file
    exactly: ``1.001`` is ``RationalTime(1001, 1000)``, and ``0.0000625`` or
    ``0.30000000000000004`` raise the rate rather than lose precision. An
    explicit ``rate`` that cannot hold a time raises
    ``LossyTimeConversionError`` naming the chapter and the rate that would
    hold every time. On dump a time is written as an exact decimal when it
    has a terminating expansion, else truncated to the millisecond, which
    keeps the order of times (see
    :func:`lacing.adapters._podcast.seconds_number`).

Numbers:
    A number that is not a time is kept as the nearest ``float`` and written
    back as that value (``1.50`` is written ``1.5``; a PHP-style
    ``48.858092999999997`` becomes ``48.858093``, as any JSON reader reads it).
    ``NaN``, ``Infinity`` and ``1e400`` (not finite) are refused on load,
    naming the chapter and the field. Bodies stay plain JSON, which a SQLite store
    or the server needs.

Lossy fields on dump:
    Provenance, confidence, schema URIs and tier metadata are dropped. The
    ``version`` is the episode annotation's, else ``1.2.0``. Without ``tier=``,
    the annotations written as chapters are those with the chapter body
    schema; with ``tier=``, every annotation of that tier with a time interval
    and an object body, its ``title`` taken from a string ``title`` field, else
    from a string ``text`` field (a WebVTT chapters track, a SubRip cue).
    Chapters are written in start, then end, order. Top-level fields are
    written before ``chapters``.

Media type and extension:
    The spec says a chapters file "should be served with a Content-type of
    'application/json+chapters'", which this adapter registers. It does not
    register the generic ``application/json``. Its extension is the compound
    ``.chapters.json``; a bare ``.json`` stays with the W3C Web Annotation
    adapter.

Malformed input raises ``ValueError`` naming the chapter index
(``chapters[3]``): a document that is not a JSON object, ``chapters`` missing
or not a list, a chapter that is not an object, a ``startTime`` or
``endTime`` that is not a number, negative or not finite, an ``endTime``
before its ``startTime``, a ``title``, ``img`` or ``url`` that is not a
string, a ``toc`` that is not a boolean, a ``location`` that is not an
object, a number a float cannot hold exactly, or a non-string ``version``.
"""

from __future__ import annotations

import os
from fractions import Fraction
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._common import DISPLAY_TEXT_KEYS, display_text, iter_with_intervals
from lacing.adapters._podcast import (
    END_INFERRED_KEY,
    TIME_FIELDS,
    TimedItem,
    dated_items,
    load_podcast_json,
    parse_document,
    plain_json,
    time_fields,
    write_json,
)
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval

ADAPTER_NAME = "podcast_chapters"
ADAPTER_VERSION = "1.0.0"
GENERATED_BY = str(adapter_generator_id(ADAPTER_NAME, ADAPTER_VERSION))
BODY_SCHEMA_URI = "annot://schema/podcast-chapter/v1"
EPISODE_BODY_SCHEMA_URI = "annot://schema/podcast-chapters-episode/v1"
# A chapter from another format is titled by its title first, then its text.
_TITLE_KEYS = ("title", *(k for k in DISPLAY_TEXT_KEYS if k != "title"))
DEFAULT_TIER_NAME = "chapters"
DEFAULT_EPISODE_TIER_NAME = "episode"
DEFAULT_ASSET_ID = "podcast-chapters:unspecified"
EXTENSION = ".chapters.json"
MEDIA_TYPE = "application/json+chapters"
FORMAT_VERSION = "1.2.0"
FORMAT_NAME = "podcast chapters JSON"

_STRING_FIELDS = ("title", "img", "url")
_OPTIONAL_FIELDS = (*_STRING_FIELDS, "toc", "location")


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def _without_nulls(fields: dict[str, Any]) -> dict[str, Any]:
    """``fields`` without the optional spec fields set to ``null`` (absent)."""
    return {
        k: v for k, v in fields.items() if not (k in _OPTIONAL_FIELDS and v is None)
    }


def _check_optional_fields(ch: dict, *, where: str) -> None:
    for key in _STRING_FIELDS:
        if key in ch and not isinstance(ch[key], str):
            raise ValueError(f"{where}: {key} must be a string, got {ch[key]!r}")
    if "toc" in ch and not isinstance(ch["toc"], bool):
        raise ValueError(f"{where}: toc must be a boolean, got {ch['toc']!r}")
    if "location" in ch and not isinstance(ch["location"], dict):
        raise ValueError(f"{where}: location must be an object, got {ch['location']!r}")
    if END_INFERRED_KEY in ch:
        raise ValueError(
            f"{where}: the field {END_INFERRED_KEY!r} is reserved by lacing"
        )


def _chapter_body(item: TimedItem) -> dict[str, Any]:
    """The annotation body of one chapter, its fields validated."""
    fields = _without_nulls(item.fields)
    _check_optional_fields(fields, where=item.where)
    body = {k: plain_json(v, where=f"{item.where}.{k}") for k, v in fields.items()}
    if item.end_inferred:
        body[END_INFERRED_KEY] = True
    return body


def _episode_body(data: dict, version: str | None) -> dict[str, Any]:
    """The episode annotation's body: the version and other top-level fields."""
    fields = {
        k: plain_json(v, where=k)
        for k, v in data.items()
        if k not in ("version", "chapters")
    }
    return {"version": version, "fields": fields}


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int | None = None,
    rounding: str | None = None,
    asset_id: str = DEFAULT_ASSET_ID,
    attribution: str = "anonymous",
    tier: str = DEFAULT_TIER_NAME,
    episode_tier: str = DEFAULT_EPISODE_TIER_NAME,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse a podcast chapters JSON file, bytes or text into a ``MemoryStore``.

    Args:
        source: Bytes (UTF-8), a path, or inline JSON text.
        rate: Rate of every ``RationalTime`` produced. ``None`` (the default)
            picks the smallest power of ten, at least 1000, at which every
            time in the file is exact, up to ``10**9`` (a store's limit); an
            explicit rate must hold every time exactly, unless ``rounding``.
        rounding: ``None`` (exact or raise), or a
            :meth:`~lacing.time.RationalTime.from_seconds_lossy` mode
            (``"round"``, ``"floor"``, ``"ceil"``) to quantise times instead,
            for files with float noise (``12.300000000000001``).
        asset_id: The ``MediaRef.asset_id`` the chapters annotate.
        attribution: ``Provenance.was_attributed_to`` of every annotation.
        tier: Name of the tier the chapters go in.
        episode_tier: Name of the tier of the episode metadata annotation.

    Raises:
        ValueError: On malformed input, naming the chapter index.
    """
    data = load_podcast_json(source, format_name=FORMAT_NAME)
    doc = parse_document(data, rate=rate, kind="chapters", rounding=rounding)
    bodies = [_chapter_body(item) for item in doc.items]
    episode = _episode_body(data, doc.version)

    store = MemoryStore()
    store.add_tier(Tier(tier))
    store.add_tier(Tier(episode_tier))
    now = RationalTime.now(doc.rate)

    def add(tier_name: str, interval: TimeInterval, body: dict, uri: str) -> None:
        store.add(
            Annotation(
                id=uuid4(),
                tier=tier_name,
                reference=MediaRef(asset_id=asset_id, interval=interval),
                body=body,
                body_schema_uri=uri,
                provenance=Provenance(
                    was_generated_by=GENERATED_BY,
                    was_attributed_to=attribution,
                    generated_at_time=now,
                    activity="import",
                ),
            )
        )

    zero = RationalTime.zero(doc.rate)
    add(episode_tier, TimeInterval(zero, zero), episode, EPISODE_BODY_SCHEMA_URI)
    for item, body in zip(doc.items, bodies):
        add(tier, item.interval, body, BODY_SCHEMA_URI)
    return store


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def _chapter_fields(a: Annotation) -> dict[str, Any]:
    """The non-time fields of the chapter ``a`` is written as."""
    body = a.body
    if a.body_schema_uri == BODY_SCHEMA_URI:
        return {k: v for k, v in _without_nulls(body).items() if k not in TIME_FIELDS}
    title = display_text(body, keys=_TITLE_KEYS)
    return {} if title is None else {"title": title}


def _chapter(a: Annotation, inferred_end: Fraction) -> dict[str, Any]:
    fields = _chapter_fields(a)
    end_was_inferred = fields.pop(END_INFERRED_KEY, None) is True
    chapter: dict[str, Any] = time_fields(
        a, inferred_end, end_was_inferred=end_was_inferred
    )
    chapter.update(fields)
    return chapter


def _episode(store: IntervalAnnotationStore) -> dict[str, Any]:
    """The top-level fields to write: version first, then the episode fields."""
    found = [
        a.body
        for a in iter_with_intervals(store)
        if a.body_schema_uri == EPISODE_BODY_SCHEMA_URI and isinstance(a.body, dict)
    ]
    if len(found) > 1:
        raise ValueError(
            f"{len(found)} episode annotations ({EPISODE_BODY_SCHEMA_URI}); "
            "a chapters file has one set of top-level fields"
        )
    body = found[0] if found else {}
    version = body.get("version")
    fields = body.get("fields")
    head: dict[str, Any] = {
        "version": version if isinstance(version, str) else FORMAT_VERSION
    }
    if isinstance(fields, dict):
        head.update({k: v for k, v in fields.items() if k not in head})
    head.pop("chapters", None)
    return head


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    tier: str | None = None,
    **_kwargs: Any,
) -> bytes | None:
    """Write annotations as podcast chapters JSON.

    Args:
        store: Source store. Chapters are its annotations with a time
            interval and the chapter body schema (or, with ``tier``, every
            annotation of that tier with a time interval and an object body),
            sorted by start then end. The episode metadata annotation, if
            any, gives the version and top-level fields.
        target: Output path. If None, returns bytes (UTF-8 JSON).
        tier: Write the annotations of this tier as chapters (see above).

    Raises:
        ValueError: For a negative time, or for more than one episode
            metadata annotation.
    """

    def is_chapter(a: Annotation) -> bool:
        if not isinstance(a.body, dict):
            return False
        if tier is None:
            return a.body_schema_uri == BODY_SCHEMA_URI
        return a.tier == tier and a.body_schema_uri != EPISODE_BODY_SCHEMA_URI

    anns = (a for a in iter_with_intervals(store) if is_chapter(a))
    doc = _episode(store)
    doc["chapters"] = [_chapter(a, end) for a, end in dated_items(anns)]
    return write_json(doc, target)


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


register_adapter(
    name=ADAPTER_NAME,
    version=ADAPTER_VERSION,
    load=load,
    dump=dump,
    extensions=(EXTENSION,),
    media_types=(MEDIA_TYPE,),
    body_schema_uris=(BODY_SCHEMA_URI, EPISODE_BODY_SCHEMA_URI),
    description=(
        "Podcasting 2.0 podcast:chapters JSON. Chapters with optional end, "
        "title, image, link, toc flag and location; episode fields kept."
    ),
)
