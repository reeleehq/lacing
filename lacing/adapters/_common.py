"""Format-neutral plumbing shared by the I/O adapters.

What several adapters need, whatever the format, lives here once:

- :func:`iter_with_intervals`: the annotations of a store that have a time
  interval, whatever their reference kind (TextGrid, WebVTT, SubRip, W3C Web
  Annotation);
- :func:`iter_with_media_intervals`: the same, restricted to ``MediaRef``
  references (ELAN EAF, JAMS, OpenTimelineIO, Label Studio);
- :func:`display_text`: the readable text of an annotation body (``text``,
  else ``title``), ``None`` for a metadata-only body. The cue writers (SubRip,
  WebVTT, LRC) skip what has none, so a chapter's title becomes a cue and an
  episode's metadata does not become an empty one; TextGrid and ELAN label
  with it and still write an unlabelled annotation (an empty interval is
  structure there); the chapters writer titles with it. The podcast
  transcript does not use it: a segment is speech, so only ``text`` counts;
- :func:`read_text`: a text ``source`` given as bytes, a path, or inline
  text, byte-order mark stripped; a ``str`` naming an existing file is that
  file (:func:`existing_file`), whatever it looks like (WebVTT, SubRip, LRC,
  ASS);
- :func:`load_json`: a JSON ``source`` given as bytes, a path, or inline text
  (Label Studio, W3C Web Annotation, and, with exact ``Decimal`` numbers, the
  Podcasting 2.0 transcript and chapters adapters). It keeps its own rules (plain UTF-8, a
  BOM is a JSON error, a folder is read as a path) rather than calling
  :func:`read_text`, so those two adapters behave exactly as before.

Helpers specific to one family of formats live in their own module (the cue
formats' clock and payload helpers are in :mod:`lacing.adapters._cues`).

Private to :mod:`lacing.adapters`: it registers no adapter (the provenance
sweep test skips ``_``-prefixed modules and checks that they register none).

>>> from lacing.store import MemoryStore
>>> list(iter_with_intervals(MemoryStore()))
[]
>>> load_json('{"a": 1}')
{'a': 1}
>>> display_text({"title": "Intro", "img": "a.jpg"})
'Intro'
"""

from __future__ import annotations

import codecs
import json
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from lacing.model import Annotation, MediaRef
from lacing.store import IntervalAnnotationStore


_BOM = "\ufeff"
_JSON_INLINE_PREFIXES = ("{", "[")

#: Body keys that hold an annotation's readable text, in preference order: a
#: cue's or a word's ``text``, then a chapter's ``title``. Not ``name``: an
#: OpenTimelineIO clip's ``name`` is a file name, not something to caption.
DISPLAY_TEXT_KEYS: tuple[str, ...] = ("text", "title")


def display_text(body: Any, *, keys: Sequence[str] = DISPLAY_TEXT_KEYS) -> str | None:
    """The readable text of an annotation ``body``: the value of the first of
    ``keys`` that holds a string or a number (never a bool), as a string;
    ``None`` when none does, as for a metadata-only body (a podcast episode's
    fields, LRC ID tags), so cue writers skip it rather than write an empty
    cue.

    Under the first key, an empty string counts (an empty cue stays a cue, so
    a file round-trips); under a later key, a blank string is passed over, so
    an empty ``title`` never stands in for a missing ``text``. Pass ``keys``
    for another preference (the chapters writer puts ``title`` first).

    >>> display_text({"text": "hi", "title": "T"})
    'hi'
    >>> display_text({"text": None, "title": "T"})
    'T'
    >>> display_text({"text": ""}), display_text({"title": " "})
    ('', None)
    >>> display_text({"version": "1.2.0", "fields": {"title": "Ep 7"}}) is None
    True
    >>> display_text({"text": "a", "title": "T"}, keys=("title", "text"))
    'T'
    """
    if not isinstance(body, Mapping):
        return None
    for position, key in enumerate(keys):
        value = body.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        text = str(value)
        if position == 0 or text.strip():
            return text
    return None


def iter_with_intervals(store: IntervalAnnotationStore) -> Iterator[Annotation]:
    """Every annotation in ``store`` that has a time interval (any reference kind).

    Uses ``store.all()`` when the store has it, else the mapping protocol, and
    yields in that iteration order.
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


def iter_with_media_intervals(store: IntervalAnnotationStore) -> Iterator[Annotation]:
    """The annotations of :func:`iter_with_intervals` whose reference is a
    ``MediaRef``, in the same order: what a writer for a media-only format
    can place (a ``NodeRef`` or ``AnnotationRef`` interval has no media
    timeline to land on).
    """
    for a in iter_with_intervals(store):
        if isinstance(a.reference, MediaRef):
            yield a


# (BOM, codec) pairs, longest BOM first (a UTF-32 LE BOM starts with UTF-16 LE's).
_BOM_CODECS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode_text(
    data: bytes, *, encoding: str | None = None, nameable: bool = True
) -> str:
    """``data`` as text, with no leading byte-order mark.

    ``encoding=None`` sniffs a BOM (UTF-8, UTF-16 LE/BE, UTF-32 LE/BE) and
    otherwise reads UTF-8. A named ``encoding`` is used as given (a UTF-8 BOM
    is still dropped). A failure is a ``UnicodeDecodeError`` that names the
    ``encoding=`` keyword, unless the caller has none to offer
    (``nameable=False``: JSON, which is UTF-8 by its standard).

    >>> decode_text("é".encode("utf-16"))
    'é'
    >>> decode_text("é".encode("cp1252"), encoding="cp1252")
    'é'
    >>> try:
    ...     decode_text("é".encode("cp1252"))
    ... except UnicodeDecodeError as error:
    ...     "pass encoding=" in str(error)
    True
    """
    sniffed = None
    if encoding is None:
        sniffed = next(
            (name for bom, name in _BOM_CODECS if data.startswith(bom)), None
        )
    codec = encoding or sniffed or "utf-8"
    try:
        return data.decode(codec).removeprefix(_BOM)
    except UnicodeDecodeError as error:
        if sniffed is not None:
            hint = f"it starts with a {sniffed} BOM but does not decode as {sniffed}"
        elif not nameable:
            hint = "not UTF-8"
        elif encoding is not None:
            hint = "wrong encoding= for this text"
        else:
            hint = "not UTF-8: pass encoding=, e.g. encoding='cp1252' or 'utf-16'"
        error.reason += f" ({hint})"
        raise


def existing_file(s: str) -> Path | None:
    """``s`` as the path of an existing file, ``None`` when it names none.

    A ``str`` with a line break is content, never a path (no stat is made),
    and one the OS cannot take as a path (too long, a NUL) names no file. Not
    ``exists()``: ``""`` or a folder is not a text file.

    >>> existing_file("[00:01.00]hello\\n") is None, existing_file("a\\0b") is None
    (True, True)
    """
    if "\n" in s or "\r" in s:
        return None
    p = Path(s)
    try:
        return p if p.is_file() else None
    except (OSError, ValueError):  # ENAMETOOLONG, an embedded NUL
        return None


def read_text(
    source: str | bytes | os.PathLike,
    *,
    encoding: str | None = None,
) -> str:
    """The text of ``source``: bytes, a path, or inline content.

    A ``str`` is read as a path when it names an existing file
    (:func:`existing_file`), and is inline content otherwise (the format's
    parser then reports what is wrong). The file wins even when the name
    looks like content: ``"[Group] Show - 01.ass"`` is a file name, not an
    ASS or LRC header. Bytes and files are decoded by :func:`decode_text`
    (``encoding`` named, or a BOM sniffed, else UTF-8); ``encoding`` does not
    apply to a ``str``, which is already text. Bytes, files and inline text
    alike lose a leading byte-order mark.

    >>> read_text(b"\\xef\\xbb\\xbfWEBVTT")
    'WEBVTT'
    >>> read_text("[ar:Someone]")  # no such file: inline content
    '[ar:Someone]'
    """
    if isinstance(source, (bytes, bytearray)):
        return decode_text(bytes(source), encoding=encoding)
    if not isinstance(source, str) and isinstance(source, os.PathLike):
        return decode_text(Path(os.fspath(source)).read_bytes(), encoding=encoding)
    s = str(source).removeprefix(_BOM)
    p = existing_file(s)
    if p is not None:
        return decode_text(p.read_bytes(), encoding=encoding)
    return s


def load_json(
    source: str | bytes | os.PathLike,
    *,
    parse_float: Callable[[str], Any] | None = None,
    parse_constant: Callable[[str], Any] | None = None,
) -> Any:
    """The JSON value of ``source``: bytes (UTF-8, or a BOM-marked UTF-16/32), a
    path, or inline JSON.

    A ``str`` whose first non-blank character opens an object or an array is
    inline JSON; otherwise it is read as a path if one exists there, and is
    parsed as inline JSON if not (``json`` then reports what is wrong).

    ``parse_float`` is passed to :func:`json.loads`: ``None`` (the default)
    reads non-integer numbers as ``float``; ``decimal.Decimal`` reads them
    exactly, as written (the podcast adapters' times). ``parse_constant``,
    also passed to :func:`json.loads`, maps the non-standard ``NaN``,
    ``Infinity`` and ``-Infinity`` (``None`` keeps ``json``'s floats).

    >>> load_json(b'[1, 2]')
    [1, 2]
    >>> load_json(b'\\xef\\xbb\\xbf[1]')  # a UTF-8 byte-order mark
    [1]
    >>> from decimal import Decimal
    >>> load_json('[1.001]', parse_float=Decimal)
    [Decimal('1.001')]
    """

    def parse(text: str) -> Any:
        return json.loads(text, parse_float=parse_float, parse_constant=parse_constant)

    if isinstance(source, (bytes, bytearray)):
        return parse(_decode_json(bytes(source)))
    if not isinstance(source, str) and isinstance(source, os.PathLike):
        return parse(_decode_json(Path(os.fspath(source)).read_bytes()))
    s = str(source).removeprefix(_BOM)
    if s.lstrip().startswith(_JSON_INLINE_PREFIXES):
        return parse(s)
    p = Path(s)
    if p.exists():
        return parse(_decode_json(p.read_bytes()))
    return parse(s)


def _decode_json(data: bytes) -> str:
    """JSON bytes as text: UTF-8 (the standard's), a byte-order mark tolerated
    (``json.loads`` refuses one), UTF-16/32 sniffed from theirs."""
    return decode_text(data, nameable=False)
