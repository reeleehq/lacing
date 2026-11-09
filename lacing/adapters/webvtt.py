"""WebVTT (W3C TimedText) adapter.

WebVTT is a flat caption format: one stream of cues, no tier hierarchy.
Cues have a start time, an end time, optional id and settings, and a payload
(text with limited inline markup).

We map cues to a single tier named ``cues`` (override with ``tier=``).
Each cue becomes one ``Annotation`` whose body holds:

    {"text": str, "id": str | None, "settings": dict[str, str]}

Lossy fields on dump:
    Provenance, confidence, schema URIs, and tier metadata are dropped.
    Only the text, id (if present), and settings are emitted. Blank lines
    inside a cue's text are dropped (a blank line ends a cue), and a negative
    time raises ``ValueError`` (WebVTT has none). A cue payload may not contain
    ``-->`` (a player would read it as a new cue's timing line), so it is
    written ``--&gt;``, which renders as ``-->``; payloads are kept raw on load,
    so it reads back as ``--&gt;`` (lacing#129). A cue id with ``-->`` or a
    line break cannot be written at all and raises ``ValueError``.

Time discipline:
    WebVTT timestamps are ``HH:MM:SS.mmm`` or ``MM:SS.mmm`` (with milliseconds).
    Parsing goes through integer milliseconds to avoid float ingestion. Default
    rate is 1000 (millisecond precision); override with ``rate=`` if your
    project uses a different canonical rate. On dump, sub-millisecond times
    are truncated to the millisecond (shared with SubRip, see
    :mod:`lacing.adapters._cues`).

Spec: https://www.w3.org/TR/webvtt1/
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._common import display_text, iter_with_intervals, read_text
from lacing.adapters._cues import (
    cue_payload,
    format_cue_time,
    hms_to_ms,
    interval_sort_key,
    ms_to_rational,
    select_cue_annotations,
    split_cue_lines,
)
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval

ADAPTER_NAME = "webvtt"
ADAPTER_VERSION = "1.0.0"
GENERATED_BY = str(adapter_generator_id(ADAPTER_NAME, ADAPTER_VERSION))
BODY_SCHEMA_URI = "annot://schema/webvtt-cue/v1"
DEFAULT_TIER_NAME = "cues"
DEFAULT_RATE = 1000
DEFAULT_ASSET_ID = "webvtt:unspecified"


_TIMESTAMP_RE = re.compile(r"^\s*(?:(\d+):)?([0-5]?\d):([0-5]?\d)\.(\d{3})\s*$")
_CUE_TIMING_RE = re.compile(r"^\s*([\d:.]+)\s+-->\s+([\d:.]+)\s*(.*)$")


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def _parse_timestamp(s: str, rate: int) -> RationalTime:
    """Parse ``HH:MM:SS.mmm`` or ``MM:SS.mmm`` into a ``RationalTime``.

    Hours optional. Milliseconds always 3 digits per WebVTT.
    """
    m = _TIMESTAMP_RE.match(s)
    if m is None:
        raise ValueError(f"invalid WebVTT timestamp: {s!r}")
    hours = int(m.group(1)) if m.group(1) else 0
    total_ms = hms_to_ms(
        hours, int(m.group(2)), int(m.group(3)), millis=int(m.group(4))
    )
    return ms_to_rational(total_ms, rate)  # exact: ms / 1000 quantized at `rate`


def _format_timestamp(t: RationalTime) -> str:
    """Format as ``HH:MM:SS.mmm``; sub-millisecond times are truncated."""
    return format_cue_time(t, separator=".", format_name="WebVTT")


_ARROW, _ESCAPED_ARROW = "-->", "--&gt;"


def _escape_arrows(payload: str) -> str:
    """``payload`` with every ``-->`` written ``--&gt;``: the spec forbids the
    arrow in a cue payload, and its entity escape renders the same.

    >>> _escape_arrows("a --> b --->")
    'a --&gt; b ---&gt;'
    """
    return payload.replace(_ARROW, _ESCAPED_ARROW)


def _checked_cue_id(cue_id: str) -> str:
    """``cue_id`` if WebVTT can write it: the spec forbids ``-->`` and line
    breaks in an id, and ids have no escape."""
    if _ARROW in cue_id or "\n" in cue_id or "\r" in cue_id:
        raise ValueError(
            f"a WebVTT cue id cannot contain '-->' or a line break: {cue_id!r}"
        )
    return cue_id


def _parse_settings(s: str) -> dict[str, str]:
    """Parse cue settings like ``align:start position:50%`` into a dict."""
    out: dict[str, str] = {}
    for token in s.split():
        if ":" in token:
            key, _, value = token.partition(":")
            out[key] = value
    return out


def _format_settings(d: dict[str, str]) -> str:
    return " ".join(f"{k}:{v}" for k, v in d.items())


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str = DEFAULT_ASSET_ID,
    attribution: str = "anonymous",
    tier: str = DEFAULT_TIER_NAME,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse a WebVTT file or string/bytes into a ``MemoryStore``."""
    text = read_text(source, looks_inline=_looks_like_inline_vtt)

    store = MemoryStore()
    store.add_tier(Tier(tier))
    now = RationalTime.now(rate)

    cues = list(_iter_cues(text, rate))
    for cue in cues:
        store.add(
            Annotation(
                id=uuid4(),
                tier=tier,
                reference=MediaRef(asset_id=asset_id, interval=cue["interval"]),
                body={
                    "text": cue["text"],
                    "id": cue["id"],
                    "settings": cue["settings"],
                },
                body_schema_uri=BODY_SCHEMA_URI,
                provenance=Provenance(
                    was_generated_by=GENERATED_BY,
                    was_attributed_to=attribution,
                    generated_at_time=now,
                    activity="import",
                ),
            )
        )

    return store


def _looks_like_inline_vtt(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    head = s.lstrip()[:6].upper()
    return head.startswith("WEBVTT")


def _iter_cues(text: str, rate: int):
    lines = split_cue_lines(text)
    if not lines or not lines[0].lstrip().upper().startswith("WEBVTT"):
        raise ValueError("WebVTT files must start with a 'WEBVTT' header line")

    i = 1
    n = len(lines)
    while i < n:
        # Skip blank lines and NOTE/STYLE/REGION blocks.
        while i < n and lines[i].strip() == "":
            i += 1
        if i >= n:
            break

        followed_by_timing = i + 1 < n and _ARROW in lines[i + 1]
        if lines[i].startswith(("NOTE", "STYLE", "REGION")) and not followed_by_timing:
            # Skip until blank line (a block whose next line is a timing line is
            # a cue whose id happens to start with one of these words).
            while i < n and lines[i].strip() != "":
                i += 1
            continue

        # Optional cue id (line without -->)
        cue_id: str | None = None
        if "-->" not in lines[i]:
            cue_id = lines[i].strip() or None
            i += 1
            if i >= n:
                break

        if "-->" not in lines[i]:
            raise ValueError(f"expected timing line at line {i + 1}, got {lines[i]!r}")

        m = _CUE_TIMING_RE.match(lines[i])
        if m is None:
            raise ValueError(f"invalid timing line: {lines[i]!r}")
        start = _parse_timestamp(m.group(1), rate)
        end = _parse_timestamp(m.group(2), rate)
        settings = _parse_settings(m.group(3) or "")
        i += 1

        # Cue payload: until blank line
        payload_lines: list[str] = []
        while i < n and lines[i].strip() != "":
            payload_lines.append(lines[i])
            i += 1

        yield {
            "id": cue_id,
            "interval": TimeInterval(start, end),
            "settings": settings,
            "text": "\n".join(payload_lines),
        }


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    tier: str | None = None,
    **_kwargs: Any,
) -> bytes | None:
    """Write annotations as WebVTT.

    Args:
        store: Source store. Only annotations from ``tier`` (default: see
            ``tier`` below) with a time interval (any reference kind) and readable
            text (:func:`lacing.adapters._common.display_text`: ``text``,
            else ``title``) are emitted, sorted by start then
            end.
        target: Output path. If None, returns bytes (UTF-8).
        tier: Write only this tier. None (the default) writes the ``lines``
            tier when the store has one, else every top-level tier
            (:func:`lacing.adapters._cues.select_cue_annotations`).
    """
    out_lines: list[str] = ["WEBVTT", ""]

    candidates = select_cue_annotations(store, iter_with_intervals(store), tier=tier)
    candidates.sort(key=interval_sort_key)

    for ann in candidates:
        text = display_text(ann.body)
        if text is None:  # metadata-only: an empty cue would be invented
            continue
        body = ann.body if isinstance(ann.body, dict) else {}
        cue_id = body.get("id")
        settings = body.get("settings", {})

        if cue_id:
            out_lines.append(_checked_cue_id(str(cue_id)))

        timing = (
            f"{_format_timestamp(ann.interval.start)} --> "  # type: ignore[union-attr]
            f"{_format_timestamp(ann.interval.end)}"  # type: ignore[union-attr]
        )
        if settings:
            timing += " " + _format_settings(settings)
        out_lines.append(timing)
        out_lines.append(_escape_arrows(cue_payload(text)))
        out_lines.append("")

    blob = "\n".join(out_lines).encode("utf-8")

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
    extensions=(".vtt",),
    media_types=("text/vtt",),
    body_schema_uris=(BODY_SCHEMA_URI,),
    description="WebVTT subtitle/caption format. Flat cues, no tier hierarchy.",
)
