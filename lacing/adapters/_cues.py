"""Shared plumbing for the flat-cue caption adapters (WebVTT, SubRip).

Both formats are one stream of timed text cues with millisecond timestamps
written ``HH:MM:SS<sep>mmm`` (``.`` in WebVTT, ``,`` in SubRip). What they have
in common lives here, once:

- :func:`ms_to_rational` / :func:`rational_to_ms`: integer milliseconds to and
  from :class:`~lacing.time.RationalTime`, never through floats;
- :func:`hms_to_ms` / :func:`format_hms`: clock fields to milliseconds and back,
  with the decimal separator as an argument;
- :func:`cue_payload` / :func:`format_cue_time`: what a cue writer emits for a
  text and a time; :func:`nonnegative_ms` is its negative-time check and
  truncation, for writers with another clock layout (LRC's ``mm:ss.xx``);
- :func:`select_cue_annotations`: which tiers a cue writer writes when the
  caller names none (the ``lines`` tier, else every top-level tier);
- :func:`interval_sort_key`: cue order, for the annotations a cue writer
  emits (:func:`lacing.adapters._common.iter_with_intervals`).

The format-neutral helpers (reading a ``source``, the annotations that have a
time interval) are in :mod:`lacing.adapters._common`.

Private to :mod:`lacing.adapters`: it registers no adapter (the provenance
sweep test skips ``_``-prefixed modules and checks that they register none).

>>> format_hms(hms_to_ms(1, 2, 3, millis=456), separator=",")
'01:02:03,456'
>>> rational_to_ms(ms_to_rational(1001, 1000))
1001
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from fractions import Fraction
from typing import Any

from lacing.model import Annotation
from lacing.tier import TierStereotype
from lacing.time import RationalTime
from lacing.tracks.subtitle import LINES_TIER


MS_PER_SECOND = 1000
MS_PER_MINUTE = 60 * MS_PER_SECOND
_MS_PER_HOUR = 60 * MS_PER_MINUTE


def hms_to_ms(hours: int, minutes: int, seconds: int, *, millis: int) -> int:
    """Total milliseconds of a clock reading.

    >>> hms_to_ms(0, 0, 1, millis=1)
    1001
    """
    return (hours * 3600 + minutes * 60 + seconds) * MS_PER_SECOND + millis


def ms_to_rational(total_ms: int, rate: int) -> RationalTime:
    """``total_ms`` milliseconds as a ``RationalTime`` at ``rate``, exactly.

    Raises :class:`~lacing.time.LossyTimeConversionError` (a ``ValueError``)
    when ``rate`` cannot hold a millisecond (e.g. ``rate=24``).

    >>> ms_to_rational(1001, 1000)
    RationalTime(1001, 1000)
    >>> ms_to_rational(1500, 48000).value
    72000
    """
    return RationalTime.from_seconds(Fraction(total_ms, MS_PER_SECOND), rate=rate)


def rational_to_ms(t: RationalTime) -> int:
    """``t`` in whole milliseconds, truncating toward zero.

    Truncation is the cue writers' rounding rule for sub-millisecond times:
    it is monotone, so ``start <= end`` before conversion implies it after
    (an interval shorter than a millisecond may become a point), and for the
    non-negative times a caption file holds it is the floor.

    >>> rational_to_ms(RationalTime(1, 3))  # 333.33... ms
    333
    >>> rational_to_ms(RationalTime(2, 3))  # 666.66... ms, not rounded up
    666
    """
    return int(t.to_fraction() * MS_PER_SECOND)


def format_hms(total_ms: int, *, separator: str) -> str:
    """``total_ms`` as ``HH:MM:SS<separator>mmm``.

    >>> format_hms(3723456, separator=".")
    '01:02:03.456'
    >>> format_hms(1001, separator=",")
    '00:00:01,001'
    """
    hours, rem = divmod(total_ms, _MS_PER_HOUR)
    minutes, rem = divmod(rem, MS_PER_MINUTE)
    seconds, ms = divmod(rem, MS_PER_SECOND)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{ms:03d}"


def select_cue_annotations(
    store: Any,
    annotations: Iterable[Annotation],
    *,
    tier: str | None = None,
    lines_tier: str = LINES_TIER,
) -> list[Annotation]:
    """The ``annotations`` a cue writer emits, by tier.

    A caller-named ``tier`` selects that tier alone. With none, the cues are
    ``lines_tier`` when ``annotations`` has any on it (so a karaoke store's
    words and comments are not written beside its lines), else every
    annotation on a top-level tier: one the store declares with a parent
    constraint (``INCLUDED_IN`` and the like) is a refinement of another tier,
    not a cue stream of its own. A tier the store does not declare, or a store
    that declares none, counts as top-level.

    >>> from types import SimpleNamespace as Ann
    >>> from lacing.tier import Tier
    >>> from lacing.store import MemoryStore
    >>> store = MemoryStore()
    >>> store.add_tier(Tier("lines"))
    >>> store.add_tier(Tier("words", stereotype=TierStereotype.INCLUDED_IN, parent="lines"))
    >>> anns = [Ann(tier="lines"), Ann(tier="words")]
    >>> [a.tier for a in select_cue_annotations(store, anns)]
    ['lines']
    >>> [a.tier for a in select_cue_annotations(store, anns, tier="words")]
    ['words']
    """
    annotations = list(annotations)
    if tier is not None:
        return [a for a in annotations if a.tier == tier]
    if any(a.tier == lines_tier for a in annotations):
        return [a for a in annotations if a.tier == lines_tier]
    tiers_of = getattr(store, "tiers", None)
    nested = {
        t.name
        for t in (tiers_of() if callable(tiers_of) else ())
        if t.stereotype is not TierStereotype.NONE
    }
    return [a for a in annotations if a.tier not in nested]


def interval_sort_key(a: Annotation) -> tuple[Fraction, Fraction]:
    """Cue order: by start, then by end (exact, rate-independent)."""
    iv = a.interval
    assert iv is not None  # callers pass what iter_with_intervals yields
    return (iv.start.to_fraction(), iv.end.to_fraction())


_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def split_cue_lines(text: str) -> list[str]:
    """``text`` split at CRLF, CR or LF only: the line breaks of WebVTT and
    SubRip. Not :meth:`str.splitlines`, which also breaks at ``\\u2028``,
    form feeds and other characters these formats keep inside a line.

    >>> split_cue_lines("a\\r\\nb\\u2028c\\rd")
    ['a', 'b\\u2028c', 'd']
    """
    return _LINE_BREAK.split(text)


def cue_payload(text: str) -> str:
    """``text`` as a cue payload: lines joined by ``\\n``, blank ones dropped,
    since in both WebVTT and SubRip a blank line ends the cue.

    >>> cue_payload("one\\n\\n  \\r\\ntwo")
    'one\\ntwo'
    """
    return "\n".join(line for line in split_cue_lines(text) if line.strip())


def nonnegative_ms(t: RationalTime, *, format_name: str) -> int:
    """``t`` in whole milliseconds, truncated (:func:`rational_to_ms`).

    Raises ``ValueError`` for a negative time, checked before truncation (which
    would turn ``-1/3000`` s into zero): no cue format can write one.

    >>> nonnegative_ms(RationalTime(1, 3), format_name="X")
    333
    """
    if t.to_fraction() < 0:
        raise ValueError(f"{format_name} cannot represent a negative time: {t!r}")
    return rational_to_ms(t)


def format_cue_time(t: RationalTime, *, separator: str, format_name: str) -> str:
    """``t`` as ``HH:MM:SS<separator>mmm``, sub-milliseconds truncated; a
    negative time raises (:func:`nonnegative_ms`)."""
    return format_hms(nonnegative_ms(t, format_name=format_name), separator=separator)
