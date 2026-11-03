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
- :func:`interval_sort_key`: cue order, for the annotations a cue writer
  emits (:func:`lacing.adapters._common.iter_with_intervals`);
- :func:`assign_words` / :func:`place_words`: for formats with lines and
  timed words inside them (LRC, ASS karaoke), which line a word goes in and
  where its text sits in that line.

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
from bisect import bisect_right
from collections.abc import Sequence
from fractions import Fraction
from itertools import accumulate
from typing import Protocol, TypeVar

from lacing.model import Annotation
from lacing.time import RationalTime


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


class TimedText(Protocol):
    """A line or a word to write: exact bounds and its text."""

    @property
    def start(self) -> Fraction: ...

    @property
    def end(self) -> Fraction: ...

    @property
    def text(self) -> str: ...


_L = TypeVar("_L", bound=TimedText)
_W = TypeVar("_W", bound=TimedText)


def place_words(text: str, words: Sequence[_W]) -> list[tuple[_W, int]]:
    """``(word, position)`` of each word found in ``text``, in order; a word
    the text does not contain (after the previous one) is dropped."""
    placed: list[tuple[_W, int]] = []
    cursor = 0
    for w in words:
        found = text.find(w.text, cursor)
        if found >= 0:
            placed.append((w, found))
            cursor = found + len(w.text)
    return placed


def assign_words(lines: Sequence[_L], words: Sequence[_W]) -> dict[int, list[_W]]:
    """Words per line index. A word goes to the latest-starting line that
    contains it in time *and* whose text contains it; failing that, to the
    latest-starting line that contains it in time. A word no line contains is
    dropped. Each line's words keep the order of ``words``.

    ``lines`` is sorted by start. Each word scans back from the last line that
    starts by the word's start, and stops as soon as no earlier line can reach
    the word's end (a running maximum of ends), so a word in a gap costs one
    step and the scan only walks lines that overlap the word.
    """
    starts = [line.start for line in lines]
    reach = list(accumulate((line.end for line in lines), max))
    by_line: dict[int, list[_W]] = {}
    for w in words:
        chosen = None
        i = bisect_right(starts, w.start) - 1
        while i >= 0 and reach[i] >= w.end:
            if lines[i].end >= w.end:
                if w.text in lines[i].text:
                    chosen = i
                    break
                if chosen is None:
                    chosen = i  # the latest holder, kept unless a better one
            i -= 1
        if chosen is not None:
            by_line.setdefault(chosen, []).append(w)
    return by_line
