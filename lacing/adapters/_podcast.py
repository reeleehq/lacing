"""Shared plumbing for the Podcasting 2.0 JSON adapters (transcript, chapters).

Both formats are JSON documents holding a ``version`` and a list of timed
items (``segments``, ``chapters``) whose times are JSON numbers of seconds,
possibly fractional (``"startTime": 1.001``), and whose end times may be
missing. What they have in common lives here, once:

- :func:`load_podcast_json`: the document, with every non-integer number read
  as an exact :class:`~decimal.Decimal` (never a ``float``), ``NaN`` and
  ``Infinity`` included, so the field holding one can be named when it is
  refused;
- :func:`parse_document`: the version and the timed items, validated, at the
  given rate or (``rate=None``) at the smallest power of ten, at least 1000,
  that holds every time of the file exactly (:func:`exact_decimal_rate`);
- :func:`plain_json`: the numbers of a field that is not a time back to plain
  JSON values, refusing any a float cannot hold exactly, so bodies stay
  JSON-serialisable and a dump writes back the value that was read;
- :func:`dated_items` and :func:`time_fields`: the dump side of end
  inference (an inferred end is left out again while it is still the one a
  reader would infer);
- :func:`seconds_number`: a ``RationalTime`` back to a JSON number, written as
  an exact decimal when it has one, else truncated to the millisecond;
- :func:`write_json`: the document as UTF-8 JSON, the time numbers written
  verbatim, to a path or as bytes.

The format-neutral helpers (reading a ``source``, the annotations that have a
time interval) are in :mod:`lacing.adapters._common`; the millisecond rule is
:func:`lacing.adapters._cues.rational_to_ms`, shared with WebVTT and SubRip.

Private to :mod:`lacing.adapters`: it registers no adapter (the provenance
sweep test skips ``_``-prefixed modules and checks that they register none).

>>> from decimal import Decimal
>>> exact_decimal_rate([Fraction("1.001"), Fraction("0.0000625")])
10000000
>>> seconds_number(RationalTime(1001, 1000)).text
'1.001'
"""

from __future__ import annotations

import json
import math
import os
import re
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from lacing.adapters._common import load_json
from lacing.adapters._cues import MS_PER_SECOND, interval_sort_key, rational_to_ms
from lacing.model import Annotation
from lacing.time import LossyTimeConversionError, RationalTime, TimeInterval


END_INFERRED_KEY = "end_inferred"
"""Body key set to ``True`` on an item whose ``endTime`` was absent and
inferred on load; the dump leaves ``endTime`` out again while the end is
still the one a reader would infer."""

TIME_FIELDS = ("startTime", "endTime")

JSON_INDENT = 2

MAX_INFERRED_RATE = 10**9
"""The highest rate ``rate=None`` picks. Float noise in a file
(``0.30000000000000004``) would otherwise ask for ``10**17``, and every
annotation's ``generated_at_time`` at such a rate no longer fits a store's
64-bit integer column (a Postgres ``rate`` column is 32-bit). Above it, load
raises and names ``rounding=``."""

MIN_RATE_DIGITS = 3
"""``rate=None`` picks at least ``10**3`` (milliseconds), so files whose
times are whole seconds get the rate of the other cue formats."""

# Bounds the decimal exponent of a time, so a number like ``1e999999999``
# is refused instead of being expanded into a billion-digit integer.
_MAX_DECIMAL_EXPONENT = 64
_DECIMAL_BASE = 10
# A plain decimal number of seconds written as a string (some hosts emit these).
_DECIMAL_STRING = re.compile(r"\+?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load_podcast_json(source: str | bytes | os.PathLike, *, format_name: str) -> dict:
    """The JSON object of ``source``, non-integer numbers as ``Decimal``.

    ``NaN``, ``Infinity`` and ``-Infinity`` (which :mod:`json` accepts but
    JSON does not have) are read as non-finite ``Decimal`` values, refused
    by :func:`parse_document` and :func:`plain_json` with the field named.
    Raises ``ValueError`` when the document is not JSON or not an object.
    """
    try:
        data = load_json(source, parse_float=Decimal, parse_constant=Decimal)
    except json.JSONDecodeError as e:
        raise ValueError(f"{format_name}: not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(
            f"{format_name}: the document must be a JSON object, "
            f"got {type(data).__name__}"
        )
    return data


def seconds_fraction(value: Any, *, where: str) -> Fraction:
    """``value`` seconds (a JSON integer, ``Decimal`` or numeric string) as an
    exact fraction.

    ``where`` names the field in error messages (``"chapters[2].endTime"``).
    Raises ``ValueError`` for a value that is not a finite, non-negative
    number.

    >>> seconds_fraction(Decimal("0.333"), where="t")
    Fraction(333, 1000)
    >>> seconds_fraction("8.56", where="t")
    Fraction(214, 25)
    >>> seconds_fraction(Decimal("NaN"), where="t")
    Traceback (most recent call last):
    ...
    ValueError: t: not a finite number: NaN
    """
    if isinstance(value, str) and _DECIMAL_STRING.fullmatch(value):
        value = Decimal(value)
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError(f"{where}: expected a number of seconds, got {value!r}")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{where}: not a finite number: {value}")
        if value and abs(value.adjusted()) > _MAX_DECIMAL_EXPONENT:
            raise ValueError(f"{where}: number out of range: {value}")
    if value < 0:
        raise ValueError(f"{where}: negative time {value}")
    return Fraction(value)


def exact_decimal_rate(seconds: Iterable[Fraction]) -> int:
    """The smallest power of ten, at least ``10**MIN_RATE_DIGITS``, at which
    every one of ``seconds`` (decimal numbers, so terminating) is exact.

    >>> exact_decimal_rate([Fraction(1), Fraction("2.5")])
    1000
    >>> exact_decimal_rate([Fraction("0.30000000000000004")])
    100000000000000000
    """
    digits = max((_finite_decimal_digits(s) or 0 for s in seconds), default=0)
    return _DECIMAL_BASE ** max(MIN_RATE_DIGITS, digits)


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


@dataclass(frozen=True, slots=True)
class TimedItem:
    """One validated item: its interval, its other fields (as read, numbers
    still ``Decimal``), whether its end was inferred, and its ``where``
    (``"chapters[3]"``) for the adapter's own error messages."""

    interval: TimeInterval
    fields: dict[str, Any]
    end_inferred: bool
    where: str


@dataclass(frozen=True, slots=True)
class TimedDocument:
    """A parsed podcast JSON document: its ``version``, the rate its times
    are at, and its timed items in file order."""

    version: str | None
    rate: int
    items: list[TimedItem]


def parse_document(
    data: dict, *, rate: int | None, kind: str, rounding: str | None = None
) -> TimedDocument:
    """The version and the timed items (``data[kind]``) of a podcast document.

    Raises ``ValueError`` for a non-string ``version`` or a ``kind`` that is
    not a list, and as :func:`parse_timed_items` does.
    """
    version = data.get("version")
    if version is not None and not isinstance(version, str):
        raise ValueError(f"version must be a string, got {version!r}")
    items = data.get(kind)
    if not isinstance(items, list):
        raise ValueError(f"{kind} must be a list, got {items!r}")
    rate, timed = parse_timed_items(items, rate=rate, kind=kind, rounding=rounding)
    return TimedDocument(version=version, rate=rate, items=timed)


def parse_timed_items(
    items: list, *, rate: int | None, kind: str, rounding: str | None = None
) -> tuple[int, list[TimedItem]]:
    """The rate used and the :class:`TimedItem` of each of ``items``.

    ``rate=None`` uses :func:`exact_decimal_rate` of every time in ``items``,
    up to :data:`MAX_INFERRED_RATE`. ``rounding`` (a
    :meth:`RationalTime.from_seconds_lossy` mode: ``"round"``, ``"floor"``,
    ``"ceil"``) opts in to quantising, at the given rate or at the capped one;
    ``None`` (the default) keeps every time exact or raises.
    An absent or ``null`` ``endTime`` is inferred (:func:`inferred_ends`).
    Raises ``ValueError`` naming the item (``segments[3]``) for an item that
    is not an object, lacks ``startTime``, has a bad time or an ``endTime``
    before its ``startTime``; and :class:`~lacing.time.LossyTimeConversionError`
    when an explicit ``rate`` cannot hold a time, naming the rate that can.
    """
    wheres = [f"{kind}[{i}]" for i in range(len(items))]
    times = [_item_seconds(item, where=w) for item, w in zip(items, wheres)]
    exact = exact_decimal_rate(t for pair in times for t in pair if t is not None)
    if rate is None:
        if exact > MAX_INFERRED_RATE and rounding is None:
            raise LossyTimeConversionError(
                f"{kind}: exact times would need rate={exact}, above the "
                f"{MAX_INFERRED_RATE} a store can hold (float noise such as "
                "0.30000000000000004?); pass rounding='round' to quantise, "
                "optionally with an explicit rate="
            )
        rate = min(exact, MAX_INFERRED_RATE)
    ends = inferred_ends([start for start, _ in times])

    def timed(
        item: dict,
        where: str,
        start: Fraction,
        end: Fraction | None,
        inferred: Fraction,
    ) -> TimedItem:
        def at_rate(seconds: Fraction, field: str) -> RationalTime:
            if rounding is not None:
                return RationalTime.from_seconds_lossy(
                    seconds, rate=rate, mode=rounding
                )
            try:
                return RationalTime.from_seconds(seconds, rate=rate)
            except LossyTimeConversionError as e:
                raise LossyTimeConversionError(
                    f"{where}.{field}: {_decimal_text(seconds)} s cannot be exactly "
                    f"represented at rate {rate}; rate={exact} holds every time "
                    "of the file (rate=None picks it, up to "
                    f"{MAX_INFERRED_RATE}), or pass rounding='round'"
                ) from e

        return TimedItem(
            interval=TimeInterval(
                at_rate(start, "startTime"),
                at_rate(inferred if end is None else end, "endTime"),
            ),
            fields={k: v for k, v in item.items() if k not in TIME_FIELDS},
            end_inferred=end is None,
            where=where,
        )

    return rate, [
        timed(item, w, start, end, inferred)
        for item, w, (start, end), inferred in zip(items, wheres, times, ends)
    ]


def _item_seconds(item: Any, *, where: str) -> tuple[Fraction, Fraction | None]:
    """The start and end (``None`` when absent or ``null``) of ``item``."""
    if not isinstance(item, dict):
        raise ValueError(f"{where}: must be an object, got {item!r}")
    if "startTime" not in item:
        raise ValueError(f"{where}: missing startTime")
    start = seconds_fraction(item["startTime"], where=f"{where}.startTime")
    end_value = item.get("endTime")
    if end_value is None:
        return start, None
    end = seconds_fraction(end_value, where=f"{where}.endTime")
    if end < start:
        raise ValueError(f"{where}: endTime {end_value} is before startTime")
    return start, end


def plain_json(value: Any, *, where: str) -> Any:
    """``value`` with every ``Decimal`` made the ``float`` of the same value.

    For the fields that are not times (an unknown field of a chapter), so a
    body stays plain JSON and a dump writes back the value that was read
    (perhaps spelled differently: ``1.50`` is written ``1.5``). A number with
    more digits than a float has (``48.858092999999997`` from PHP) becomes the
    nearest float, as every JSON reader reads it. Raises ``ValueError`` naming
    the field (``where``, extended with keys and indexes) for a number that is
    not finite: ``NaN``, ``Infinity``, ``1e400``. A time never goes through
    here.

    >>> plain_json({"a": [Decimal("0.5"), 1, "x"]}, where="c")
    {'a': [0.5, 1, 'x']}
    >>> plain_json({"a": [Decimal("1e400")]}, where="c")
    Traceback (most recent call last):
    ...
    ValueError: c.a[0]: not a finite number: 1E+400
    """
    if isinstance(value, Decimal):
        return _finite_float(value, where=where)
    if isinstance(value, dict):
        return {k: plain_json(v, where=f"{where}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [plain_json(v, where=f"{where}[{i}]") for i, v in enumerate(value)]
    return value


def _finite_float(d: Decimal, *, where: str) -> float:
    f = float(d) if d.is_finite() else math.inf
    if math.isinf(f):
        raise ValueError(f"{where}: not a finite number: {d}")
    return f


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dated_items(anns: Iterable[Annotation]) -> list[tuple[Annotation, Fraction]]:
    """``anns`` (all with an interval) in start, then end, order, each with
    the end a reader would infer for it (:func:`inferred_ends`)."""
    ordered = sorted(anns, key=interval_sort_key)
    starts = [a.interval.start.to_fraction() for a in ordered]  # type: ignore[union-attr]
    return list(zip(ordered, inferred_ends(starts)))


def time_fields(
    a: Annotation, inferred_end: Fraction, *, end_was_inferred: bool
) -> dict[str, JsonNumber]:
    """``startTime`` and, unless the end was inferred on load and still is
    the one a reader would infer, ``endTime`` of ``a``."""
    iv = a.interval
    assert iv is not None  # dated_items' annotations have intervals
    out = {"startTime": seconds_number(iv.start)}
    if not (end_was_inferred and iv.end.to_fraction() == inferred_end):
        out["endTime"] = seconds_number(iv.end)
    return out


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


def _decimal_text(f: Fraction, digits: int | None = None) -> str:
    """``f`` (non-negative, with a terminating expansion) as a decimal
    string, without trailing zeros."""
    digits = _finite_decimal_digits(f) if digits is None else digits
    assert digits is not None
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


def write_json(doc: Any, target: str | os.PathLike | None) -> bytes | None:
    """``doc`` as :func:`dumps_json` bytes, written to ``target`` (returning
    ``None``) or returned when ``target`` is ``None``."""
    blob = dumps_json(doc)
    if target is None:
        return blob
    Path(os.fspath(target)).write_bytes(blob)
    return None
