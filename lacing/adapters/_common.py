"""Format-neutral plumbing shared by the I/O adapters.

What several adapters need, whatever the format, lives here once:

- :func:`iter_with_intervals`: the annotations of a store that have a time
  interval, whatever their reference kind (TextGrid, WebVTT, SubRip, W3C Web
  Annotation);
- :func:`iter_with_media_intervals`: the same, restricted to ``MediaRef``
  references (ELAN EAF, JAMS, OpenTimelineIO, Label Studio);
- :func:`read_text`: a text ``source`` given as bytes, a path, or inline
  text, byte-order mark stripped (WebVTT, SubRip);
- :func:`load_json`: a JSON ``source`` given as bytes, a path, or inline text
  (Label Studio, W3C Web Annotation). It keeps its own rules (plain UTF-8, a
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
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from lacing.model import Annotation, MediaRef
from lacing.store import IntervalAnnotationStore


# ``utf-8-sig`` decodes UTF-8 and also strips a leading byte-order mark.
TEXT_ENCODING = "utf-8-sig"
_BOM = "\ufeff"
JSON_ENCODING = "utf-8"
_JSON_INLINE_PREFIXES = ("{", "[")


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


def read_text(
    source: str | bytes | os.PathLike, *, looks_inline: Callable[[str], bool]
) -> str:
    """The text of ``source``: bytes (UTF-8), a path, or inline content.

    A ``str`` is inline content when ``looks_inline(source)`` says so;
    otherwise it is read as a path if one exists there, and is taken as
    inline content if not (the format's parser then reports what is wrong).
    Bytes, files and inline text alike lose a leading byte-order mark.

    >>> read_text(b"\\xef\\xbb\\xbfWEBVTT", looks_inline=lambda s: True)
    'WEBVTT'
    """
    if isinstance(source, (bytes, bytearray)):
        return bytes(source).decode(TEXT_ENCODING)
    if not isinstance(source, str) and isinstance(source, os.PathLike):
        return Path(os.fspath(source)).read_text(encoding=TEXT_ENCODING)
    s = str(source).removeprefix(_BOM)
    if looks_inline(s):
        return s
    p = Path(s)
    if p.is_file():  # not exists(): "" or a folder is not a text file
        return p.read_text(encoding=TEXT_ENCODING)
    return s


def load_json(source: str | bytes | os.PathLike) -> Any:
    """The JSON value of ``source``: bytes (UTF-8), a path, or inline JSON.

    A ``str`` whose first non-blank character opens an object or an array is
    inline JSON; otherwise it is read as a path if one exists there, and is
    parsed as inline JSON if not (``json`` then reports what is wrong).

    >>> load_json(b'[1, 2]')
    [1, 2]
    """
    if isinstance(source, (bytes, bytearray)):
        return json.loads(bytes(source).decode(JSON_ENCODING))
    if not isinstance(source, str) and isinstance(source, os.PathLike):
        return json.loads(Path(os.fspath(source)).read_text(encoding=JSON_ENCODING))
    s = str(source)
    if s.lstrip().startswith(_JSON_INLINE_PREFIXES):
        return json.loads(s)
    p = Path(s)
    if p.exists():
        return json.loads(p.read_text(encoding=JSON_ENCODING))
    return json.loads(s)
