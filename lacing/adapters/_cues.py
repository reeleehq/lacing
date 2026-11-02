"""Shared plumbing for the flat-cue caption adapters (WebVTT, SubRip).

Both formats are one stream of timed text cues with millisecond timestamps
written ``HH:MM:SS<sep>mmm`` (``.`` in WebVTT, ``,`` in SubRip). What they have
in common lives here, once:

- :func:`read_text`: a ``source`` given as bytes, a path, or inline text;
- :func:`ms_to_rational` / :func:`rational_to_ms`: integer milliseconds to and
  from :class:`~lacing.time.RationalTime`, never through floats;
- :func:`hms_to_ms` / :func:`format_hms`: clock fields to milliseconds and back,
  with the decimal separator as an argument;
- :func:`cue_payload` / :func:`format_cue_time`: what a cue writer emits for a
  text and a time;
- :func:`iter_with_intervals` / :func:`interval_sort_key`: the annotations a
  cue writer can emit (those with a time interval, whatever their reference
  kind), in cue order.

Private to :mod:`lacing.adapters`: it registers no adapter (the provenance
sweep test skips ``_``-prefixed modules and checks that they register none).

>>> format_hms(hms_to_ms(1, 2, 3, millis=456), separator=",")
'01:02:03,456'
>>> rational_to_ms(ms_to_rational(1001, 1000))
1001
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from fractions import Fraction
from pathlib import Path

from lacing.model import Annotation
from lacing.store import IntervalAnnotationStore
from lacing.time import RationalTime


MS_PER_SECOND = 1000
_MS_PER_MINUTE = 60 * MS_PER_SECOND
_MS_PER_HOUR = 60 * _MS_PER_MINUTE

# Caption files are UTF-8; ``utf-8-sig`` also strips a leading byte-order mark.
TEXT_ENCODING = "utf-8-sig"
_BOM = "\ufeff"


def read_text(
    source: str | bytes | os.PathLike, *, looks_inline: Callable[[str], bool]
) -> str:
    """The text of ``source``: bytes (UTF-8), a path, or inline content.

    A ``str`` is inline content when ``looks_inline(source)`` says so;
    otherwise it is read as a path if one exists there, and is taken as
    inline content if not (the format's parser then reports what is wrong).
    Bytes, files and inline text alike lose a leading byte-order mark.
    """
    if isinstance(source, (bytes, bytearray)):
        return bytes(source).decode(TEXT_ENCODING)
    if not isinstance(source, str) and isinstance(source, os.PathLike):
        return Path(os.fspath(source)).read_text(encoding=TEXT_ENCODING)
    s = str(source).removeprefix(_BOM)
    if looks_inline(s):
        return s
    p = Path(s)
    if p.is_file():  # not exists(): "" or a folder is not a caption file
        return p.read_text(encoding=TEXT_ENCODING)
    return s


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
    minutes, rem = divmod(rem, _MS_PER_MINUTE)
    seconds, ms = divmod(rem, MS_PER_SECOND)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{ms:03d}"


def iter_with_intervals(store: IntervalAnnotationStore) -> Iterator[Annotation]:
    """Every annotation in ``store`` that has a time interval (any reference kind).

    Uses ``store.all()`` when the store has it, else the mapping protocol.
    """
    iter_all = getattr(store, "all", None)
    if callable(iter_all):
        for a in iter_all():
            if a.interval is not None:
                yield a
        return
    for key in store:  # type: ignore[attr-defined]
        for a in store[key]:  # type: ignore[index]
            if a.interval is not None:
                yield a


def interval_sort_key(a: Annotation) -> tuple[Fraction, Fraction]:
    """Cue order: by start, then by end (exact, rate-independent)."""
    iv = a.interval
    assert iv is not None  # callers pass what iter_with_intervals yields
    return (iv.start.to_fraction(), iv.end.to_fraction())


_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def cue_payload(text: str) -> str:
    """``text`` as a cue payload: lines joined by ``\\n``, blank ones dropped,
    since in both WebVTT and SubRip a blank line ends the cue.

    >>> cue_payload("one\\n\\n  \\r\\ntwo")
    'one\\ntwo'
    """
    return "\n".join(line for line in _LINE_BREAK.split(text) if line.strip())


def format_cue_time(t: RationalTime, *, separator: str, format_name: str) -> str:
    """``t`` as ``HH:MM:SS<separator>mmm``, sub-milliseconds truncated.

    Raises ``ValueError`` for a negative time, checked before truncation (which
    would turn ``-1/3000`` s into zero): neither format can write one.
    """
    if t.to_fraction() < 0:
        raise ValueError(f"{format_name} cannot represent a negative time: {t!r}")
    return format_hms(rational_to_ms(t), separator=separator)
