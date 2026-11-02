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
  chapter object except ``startTime`` and ``endTime``, verbatim and in file
  order (``title``, ``img``, ``url``, ``toc``, ``location``, and any field the
  spec does not name, such as the ``value`` of the spec's complex example), so
  a chapter round-trips losslessly. Numbers in those fields are plain JSON
  numbers. ``"end_inferred": true`` is added when the chapter had no
  ``endTime`` (a chapter that already has a field of that name is refused).
- ``episode`` (stereotype ``NONE``; override with ``episode_tier=``):
  **one** metadata annotation, a point at time 0, body
  ``annot://schema/podcast-chapters-episode/v1``
  ``{"version": str | None, "fields": {...}}``, where ``fields`` holds every
  other top-level field (``author``, ``title``, ``podcastName``,
  ``description``, ``fileName``, ``waypoints``, and any unnamed one) verbatim
  and in file order. These describe the file, not a chapter, so they live on
  one annotation rather than in every chapter body, the way the LRC adapter
  keeps its ID tags; a store from another format dumps without inventing any.

End times:
    ``endTime`` is optional. A chapter without one ends where the next *later*
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
    ``RationalTime`` at ``rate`` (default 1000): ``1.001`` is
    ``RationalTime(1001, 1000)``. A time the rate cannot hold exactly raises
    ``LossyTimeConversionError``. On dump a time is written as an exact
    decimal when it has a terminating expansion, else truncated to the
    millisecond, which keeps the order of times (see
    :func:`lacing.adapters._podcast.seconds_number`).

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
``endTime`` that is missing, not a number, negative or not finite, an
``endTime`` before its ``startTime``, a ``title``, ``img`` or ``url`` that is
not a string, a ``toc`` that is not a boolean, a ``location`` that is not an
object, or a non-string ``version``.
"""

from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._common import iter_with_intervals
from lacing.adapters._cues import interval_sort_key
from lacing.adapters._podcast import (
    END_INFERRED_KEY,
    dumps_json,
    inferred_ends,
    load_podcast_json,
    parse_seconds,
    plain_json,
    seconds_number,
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
DEFAULT_TIER_NAME = "chapters"
DEFAULT_EPISODE_TIER_NAME = "episode"
DEFAULT_RATE = 1000
DEFAULT_ASSET_ID = "podcast-chapters:unspecified"
EXTENSION = ".chapters.json"
MEDIA_TYPE = "application/json+chapters"
FORMAT_VERSION = "1.2.0"
FORMAT_NAME = "podcast chapters JSON"

_TIME_FIELDS = ("startTime", "endTime")
_STRING_FIELDS = ("title", "img", "url")


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


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


def _parse_chapter(ch: Any, rate: int, *, index: int) -> dict[str, Any]:
    """``{"start", "end" (or None), "body"}`` of one chapter, validated."""
    where = f"chapters[{index}]"
    if not isinstance(ch, dict):
        raise ValueError(f"{where}: a chapter must be an object, got {ch!r}")
    if "startTime" not in ch:
        raise ValueError(f"{where}: missing startTime")
    _check_optional_fields(ch, where=where)
    start = parse_seconds(ch["startTime"], rate, where=f"{where}.startTime")
    end = None
    if "endTime" in ch:
        end = parse_seconds(ch["endTime"], rate, where=f"{where}.endTime")
        if end < start:
            raise ValueError(f"{where}: endTime {ch['endTime']} is before startTime")
    body = {k: plain_json(v) for k, v in ch.items() if k not in _TIME_FIELDS}
    return {"start": start, "end": end, "body": body}


def _parse(data: dict, rate: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The episode body and the parsed chapters of a chapters document."""
    version = data.get("version")
    if version is not None and not isinstance(version, str):
        raise ValueError(f"version must be a string, got {version!r}")
    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        raise ValueError(f"chapters must be a list, got {chapters!r}")
    parsed = [_parse_chapter(c, rate, index=i) for i, c in enumerate(chapters)]
    ends = inferred_ends([p["start"].to_fraction() for p in parsed])
    for p, end in zip(parsed, ends):
        if p["end"] is None:
            p["end"] = RationalTime.from_seconds(end, rate=rate)  # a start: exact
            p["body"][END_INFERRED_KEY] = True
    fields = {
        k: plain_json(v) for k, v in data.items() if k not in ("version", "chapters")
    }
    return {"version": version, "fields": fields}, parsed


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str = DEFAULT_ASSET_ID,
    attribution: str = "anonymous",
    tier: str = DEFAULT_TIER_NAME,
    episode_tier: str = DEFAULT_EPISODE_TIER_NAME,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse a podcast chapters JSON file, bytes or text into a ``MemoryStore``.

    Args:
        source: Bytes (UTF-8), a path, or inline JSON text.
        rate: Rate of every ``RationalTime`` produced; every time in the file
            must be exact at this rate.
        asset_id: The ``MediaRef.asset_id`` the chapters annotate.
        attribution: ``Provenance.was_attributed_to`` of every annotation.
        tier: Name of the tier the chapters go in.
        episode_tier: Name of the tier of the episode metadata annotation.

    Raises:
        ValueError: On malformed input, naming the chapter index.
    """
    episode, chapters = _parse(load_podcast_json(source, format_name=FORMAT_NAME), rate)

    store = MemoryStore()
    store.add_tier(Tier(tier))
    store.add_tier(Tier(episode_tier))
    now = RationalTime.now(rate)

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

    zero = RationalTime.zero(rate)
    add(episode_tier, TimeInterval(zero, zero), episode, EPISODE_BODY_SCHEMA_URI)
    for ch in chapters:
        add(tier, TimeInterval(ch["start"], ch["end"]), ch["body"], BODY_SCHEMA_URI)
    return store


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def _chapter_fields(a: Annotation) -> dict[str, Any]:
    """The non-time fields of the chapter ``a`` is written as."""
    body = a.body
    if a.body_schema_uri == BODY_SCHEMA_URI:
        return {k: v for k, v in body.items() if k not in _TIME_FIELDS}
    title = body.get("title")
    if not isinstance(title, str):
        title = body.get("text")
    return {"title": title} if isinstance(title, str) else {}


def _chapter(a: Annotation, inferred_end: Fraction) -> dict[str, Any]:
    iv = a.interval
    assert iv is not None  # iter_with_intervals filters
    fields = _chapter_fields(a)
    end_was_inferred = fields.pop(END_INFERRED_KEY, None) is True
    chapter: dict[str, Any] = {"startTime": seconds_number(iv.start)}
    if not (end_was_inferred and iv.end.to_fraction() == inferred_end):
        chapter["endTime"] = seconds_number(iv.end)
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

    anns = [a for a in iter_with_intervals(store) if is_chapter(a)]
    anns.sort(key=interval_sort_key)
    ends = inferred_ends([a.interval.start.to_fraction() for a in anns])  # type: ignore[union-attr]
    doc = _episode(store)
    doc["chapters"] = [_chapter(a, end) for a, end in zip(anns, ends)]
    blob = dumps_json(doc)
    if target is None:
        return blob
    Path(os.fspath(target)).write_bytes(blob)
    return None


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
