"""Shared plumbing for the Podcasting 2.0 JSON adapters (transcript, chapters).

Both formats are JSON documents whose times are JSON numbers of seconds,
possibly fractional (``"startTime": 1.001``), and whose end times may be
missing. What they have in common lives here, once:

- :func:`load_podcast_json`: the document, with every non-integer number read
  as an exact :class:`~decimal.Decimal` (never a ``float``);
- :func:`parse_seconds`: such a number to a ``RationalTime`` at a rate,
  exactly, raising when the rate cannot hold it;
- :func:`inferred_ends`: the end a reader gives an item that has no
  ``endTime`` (the next later start, or a point for the last item);
- :func:`seconds_number`: a ``RationalTime`` back to a JSON number, written as
  an exact decimal when it has one, else truncated to the millisecond;
- :func:`plain_json`: non-time numbers back to plain JSON values, so bodies
  stay JSON-serialisable;
- :func:`dumps_json`: the document as UTF-8 JSON, with the time numbers
  written verbatim.

The format-neutral helpers (reading a ``source``, the annotations that have a
time interval) are in :mod:`lacing.adapters._common`; the millisecond rule is
:func:`lacing.adapters._cues.rational_to_ms`, shared with WebVTT and SubRip.

Private to :mod:`lacing.adapters`: it registers no adapter (the provenance
sweep test skips ``_``-prefixed modules and checks that they register none).

>>> from decimal import Decimal
>>> parse_seconds(Decimal("1.001"), 1000, where="segments[0].startTime")
RationalTime(1001, 1000)
>>> seconds_number(RationalTime(1001, 1000)).text
'1.001'
"""

from __future__ import annotations

import json
import os
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any

from lacing.adapters._common import load_json
from lacing.adapters._cues import MS_PER_SECOND, rational_to_ms
from lacing.time import LossyTimeConversionError, RationalTime


END_INFERRED_KEY = "end_inferred"
"""Body key set to ``True`` on an item whose ``endTime`` was absent and
inferred on load; the dump leaves ``endTime`` out again while the end is
still the one a reader would infer."""

JSON_INDENT = 2

# Bounds the decimal exponent of a time, so a number like ``1e999999999``
# is refused instead of being expanded into a billion-digit integer.
_MAX_DECIMAL_EXPONENT = 64
_DECIMAL_BASE = 10


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load_podcast_json(source: str | bytes | os.PathLike, *, format_name: str) -> dict:
    """The JSON object of ``source``, non-integer numbers as ``Decimal``.

    Raises ``ValueError`` when the document is not JSON or not an object.
    """
    try:
        data = load_json(source, parse_float=Decimal)
    except json.JSONDecodeError as e:
        raise ValueError(f"{format_name}: not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(
            f"{format_name}: the document must be a JSON object, "
            f"got {type(data).__name__}"
        )
    return data


def parse_seconds(value: Any, rate: int, *, where: str) -> RationalTime:
    """``value`` seconds (a JSON integer or ``Decimal``) at ``rate``, exactly.

    ``where`` names the field in error messages (``"chapters[2].endTime"``).
    Raises ``ValueError`` for a value that is not a finite, non-negative
    number, and :class:`~lacing.time.LossyTimeConversionError` (a
    ``ValueError``) when ``rate`` cannot hold it exactly.

    >>> parse_seconds(Decimal("0.333"), 1000, where="t")
    RationalTime(333, 1000)
    >>> parse_seconds(Decimal("0.0005"), 1000, where="t")
    Traceback (most recent call last):
    ...
    lacing.time.LossyTimeConversionError: t: 0.0005 s cannot be exactly represented at rate 1000
    """
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError(f"{where}: expected a number of seconds, got {value!r}")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{where}: not a finite number: {value!r}")
        if value and abs(value.adjusted()) > _MAX_DECIMAL_EXPONENT:
            raise ValueError(f"{where}: number out of range: {value}")
    if value < 0:
        raise ValueError(f"{where}: negative time {value}")
    seconds = Fraction(value)
    try:
        return RationalTime.from_seconds(seconds, rate=rate)
    except LossyTimeConversionError as e:
        raise LossyTimeConversionError(
            f"{where}: {value} s cannot be exactly represented at rate {rate}"
        ) from e


def inferred_ends(starts: Sequence[Fraction]) -> list[Fraction]:
    """The end a reader gives each item of ``starts`` when it has no end time.

    An item ends where the next *later* item starts (items sharing a start
    all end at the next later start); an item with no later start is a point,
    ending where it starts. Order of ``starts`` does not matter.

    >>> inferred_ends([Fraction(0), Fraction(5), Fraction(5), Fraction(9)])
    [Fraction(5, 1), Fraction(9, 1), Fraction(9, 1), Fraction(9, 1)]
    """
    distinct = sorted(set(starts))

    def end_of(start: Fraction) -> Fraction:
        i = bisect_right(distinct, start)
        return distinct[i] if i < len(distinct) else start

    return [end_of(s) for s in starts]


def plain_json(value: Any) -> Any:
    """``value`` with every ``Decimal`` made a ``float``, recursively.

    For the numbers that are not times (an unknown field of a chapter), so a
    body stays plain JSON. A time never goes through here.

    >>> plain_json({"a": [Decimal("0.5"), 1, "x"]})
    {'a': [0.5, 1, 'x']}
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: plain_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain_json(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JsonNumber:
    """A JSON number written verbatim by :func:`dumps_json`."""

    text: str


def _finite_decimal_digits(f: Fraction) -> int | None:
    """How many decimal digits ``f`` needs after the point, ``None`` if its
    expansion does not terminate (its denominator has a prime other than 2
    or 5)."""
    d = f.denominator
    twos = fives = 0
    while d % 2 == 0:
        d //= 2
        twos += 1
    while d % 5 == 0:
        d //= 5
        fives += 1
    return max(twos, fives) if d == 1 else None


def _decimal_text(f: Fraction, digits: int) -> str:
    """``f`` (non-negative, with a terminating expansion of ``digits``
    digits) as a decimal string, without trailing zeros."""
    scale = _DECIMAL_BASE**digits
    scaled = f.numerator * scale // f.denominator  # exact: scale * f is whole
    whole, frac = divmod(scaled, scale)
    if frac == 0:
        return str(whole)
    return f"{whole}.{str(frac).zfill(digits).rstrip('0')}"


def seconds_number(t: RationalTime) -> JsonNumber:
    """``t`` as a JSON number of seconds.

    Exact when ``t`` has a terminating decimal expansion (``1001/1000`` ->
    ``1.001``, ``1/8`` -> ``0.125``). Otherwise (``1/3``, ``1/24000``) it is
    **truncated** to the millisecond (``0.333``), the rule of the cue writers
    (:func:`lacing.adapters._cues.rational_to_ms`): truncation is monotone, so
    written times keep their order and every ``startTime <= endTime``. Raises
    ``ValueError`` for a negative time, which neither format can hold.

    >>> seconds_number(RationalTime(1, 3)).text
    '0.333'
    >>> seconds_number(RationalTime(94, 1)).text
    '94'
    """
    f = t.to_fraction()
    if f < 0:
        raise ValueError(f"a podcast JSON time cannot be negative: {t!r}")
    digits = _finite_decimal_digits(f)
    if digits is None:
        f = Fraction(rational_to_ms(t), MS_PER_SECOND)
        digits = _finite_decimal_digits(f)
        assert digits is not None  # a whole number of milliseconds terminates
    return JsonNumber(_decimal_text(f, digits))


def dumps_json(value: Any) -> bytes:
    """``value`` as UTF-8 JSON indented by :data:`JSON_INDENT`, writing every
    :class:`JsonNumber` verbatim and everything else with :mod:`json`.

    >>> dumps_json({"t": JsonNumber("1.001"), "s": ["é"]}).decode()
    '{\\n  "t": 1.001,\\n  "s": [\\n    "é"\\n  ]\\n}\\n'
    """

    def encode(v: Any, level: int) -> str:
        if isinstance(v, JsonNumber):
            return v.text
        pad = " " * (JSON_INDENT * (level + 1))
        close = " " * (JSON_INDENT * level)
        if isinstance(v, dict) and v:
            items = (
                f"{pad}{json.dumps(str(k), ensure_ascii=False)}: {encode(x, level + 1)}"
                for k, x in v.items()
            )
            return "{\n" + ",\n".join(items) + f"\n{close}}}"
        if isinstance(v, list) and v:
            items = (f"{pad}{encode(x, level + 1)}" for x in v)
            return "[\n" + ",\n".join(items) + f"\n{close}]"
        return json.dumps(v, ensure_ascii=False, allow_nan=False)

    return (encode(value, 0) + "\n").encode("utf-8")
