"""Which body fields are *derived* from another field of the same object.

A body schema marks a field whose value can be recomputed from a sibling field
by annotating it with :class:`Derived`, naming that sibling::

    from typing import Annotated
    from pydantic import BaseModel
    from lacing import Derived, derived_paths

    class PanelImage(BaseModel):
        artifact_id: str = ""
        asset_id: Annotated[str, Derived("artifact_id")] = ""   # hash of the bytes

    class Body(BaseModel):
        images: list[PanelImage] = []

    derived_paths(Body)  # {('images', None, 'asset_id')}   (None = any list item / map value)

The reason to mark one: a host sometimes learns the value *after* the annotation
was saved (a content hash known only once an upload is ingested). Writing it
changes nothing a render reads, so :func:`lacing.annotation_value_digest` leaves
derived fields out and the write does not make downstream results look stale.

The marker is carried into the exported JSON Schema as ``x-derived`` (the raw
schema only: json-schema-to-zod drops ``x-*`` keys), and :func:`derived_paths`
reads that same schema, so the export and the digest cannot disagree.

Two rules keep the exclusion honest, since leaving out a field that is *not*
derivable would make two different values digest alike (a wrong cache hit):

- the marker names a **source** field that exists in the same object and is
  itself not derived (a schema error otherwise, raised by :func:`derived_paths`);
- it sits on a field as a whole, not inside a container (``list[Annotated[...]]``
  is refused, since "the sibling" would then be undefined).

Paths are exact: only the marked field of the marked model is excluded, not
every key of that name elsewhere in the body. Where a path is ambiguous it is
dropped, never guessed: in a union (``A | B``) a field is excluded only if every
object alternative marks it, tuple positions must agree, and the values of a map
that also declares properties are not walked. A recursive model is walked one
level only. Each of these costs at most a spurious cache miss, never a wrong hit.
Field names and aliases are both read as spellings of a field, as in
:func:`lacing.location_fields`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

__all__ = [
    "Derived",
    "DerivedPath",
    "ANY_ITEM",
    "derived_paths",
    "derived_prefills",
    "derived_defaults",
    "drop_paths",
    "fill_paths",
    "null_paths",
    "occurrences",
]

#: One step of a path through a body: an object key, or :data:`ANY_ITEM`.
DerivedPath = tuple["str | None", ...]
PathSet = frozenset[DerivedPath] | set[DerivedPath]

#: Path step standing for "every element of a list / every value of a map".
ANY_ITEM = None

_SCHEMA_MODES = ("validation", "serialization")
_MARK = "x-derived"
_SCALAR_TYPES = ("null", "string", "number", "integer", "boolean")


@dataclass(frozen=True)
class Derived:
    """Field marker: this body field is derivable from the sibling field ``source``."""

    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source:
            raise ValueError(f"Derived needs a source field name, got {self.source!r}")

    def __get_pydantic_json_schema__(self, core_schema: Any, handler: Any) -> dict:
        schema = handler(core_schema)
        if schema.get(_MARK, self.source) != self.source:
            raise ValueError(
                f"a field is marked derived from two sources: "
                f"{schema[_MARK]!r} and {self.source!r}"
            )
        return {**schema, _MARK: self.source}


_NO_DEFAULT = object()
"""A derived field whose schema declares no default (a required field, or one
with a ``default_factory``), or whose defaults disagree across union members or
schema modes."""


def _json_key(value: Any) -> Any:
    """``value`` as canonical JSON text, so that ``0`` is not ``False``, ``1`` is
    not ``1.0`` and ``[0]`` is not ``[False]``; ``value`` itself when it is not
    JSON (compared by ``==`` then)."""
    try:
        return json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return value


def same_json(a: Any, b: Any) -> bool:
    """Whether two values are equal as JSON (see :func:`_json_key`): ``0`` is
    not ``False``; values that are not JSON (a ``datetime``) compare by ``==``
    instead of raising. Shared with :mod:`lacing.digest`."""
    return a is b or _json_key(a) == _json_key(b)


def _note(out: dict, path: DerivedPath, default: Any) -> None:
    """Record ``path`` with ``default``; a disagreeing second default forgets it."""
    known = out.get(path, default)
    if known is _NO_DEFAULT or default is _NO_DEFAULT or not same_json(known, default):
        default = _NO_DEFAULT
    out[path] = default


def _collect(
    node: Any, defs: dict, prefix: DerivedPath, stack: tuple[str, ...], out: dict
) -> None:
    """Add to ``out`` the path of every marked property reachable from ``node``,
    mapped to its declared JSON default (:data:`_NO_DEFAULT` when none)."""
    if not isinstance(node, dict):
        return
    if _MARK in node:  # marked properties are consumed below, never recursed into
        raise ValueError(
            "Derived must annotate a field as a whole, not an item of a container "
            "or a union member"
        )
    ref = node.get("$ref")
    if ref is not None:
        name = ref.rsplit("/", 1)[-1]
        if name not in stack and name in defs:  # a recursive model is walked once
            _collect(defs[name], defs, prefix, (*stack, name), out)
    properties = node.get("properties", {})
    for name, prop in properties.items():
        source = prop.get(_MARK)
        if source is None:
            _collect(prop, defs, (*prefix, name), stack, out)
        elif source not in properties or properties[source].get(_MARK):
            raise ValueError(
                f"field {name!r} is derived from {source!r}, which must be "
                f"another, non-derived field of the same object"
            )
        else:
            _note(out, (*prefix, name), prop.get("default", _NO_DEFAULT))
    for member in node.get("allOf", ()):
        _collect(member, defs, prefix, stack, out)
    for key in ("anyOf", "oneOf"):
        _merge(out, _common(node.get(key, ()), defs, prefix, stack))
    # One path per element is only sound if every element agrees, so a tuple's
    # positions are intersected; a map's extra values are skipped when the
    # object also declares properties (they would be told apart from them only
    # by key name).
    _merge(out, _common(node.get("prefixItems", ()), defs, (*prefix, ANY_ITEM), stack))
    if isinstance(node.get("items"), dict):
        _collect(node["items"], defs, (*prefix, ANY_ITEM), stack, out)
    extra = node.get("additionalProperties")
    if isinstance(extra, dict) and not properties:
        _collect(extra, defs, (*prefix, ANY_ITEM), stack, out)


def _merge(out: dict, found: dict) -> None:
    for path, default in found.items():
        _note(out, path, default)


def _common(
    members: Any, defs: dict, prefix: DerivedPath, stack: tuple[str, ...]
) -> dict:
    """Paths marked by *every* non-scalar member (``A | B`` drops only what both
    mark), each with the default they all declare."""
    per_member = []
    for member in members:
        if isinstance(member, dict) and member.get("type") in _SCALAR_TYPES:
            continue  # a null / str / number alternative has no fields to confuse
        found: dict = {}
        _collect(member, defs, prefix, stack, found)
        per_member.append(found)
    if not per_member:
        return {}
    shared = set.intersection(*(set(found) for found in per_member))
    out: dict = {}
    for found in per_member:
        for path in shared:
            _note(out, path, found[path])
    return out


@lru_cache(maxsize=256)
def _derived(model: type[BaseModel]) -> Mapping[DerivedPath, Any]:
    """Every derived path of ``model``, with its declared default; cached."""
    out: dict = {}
    for mode, by_alias in product(_SCHEMA_MODES, (True, False)):
        schema = model.model_json_schema(mode=mode, by_alias=by_alias)
        _collect(schema, schema.get("$defs", {}), (), (), out)
    return MappingProxyType(out)


def derived_paths(model: type[BaseModel]) -> frozenset[DerivedPath]:
    """The paths, from the root of a ``model`` body, of its :class:`Derived` fields.

    A step is an object key or :data:`ANY_ITEM` (every list element / map value).
    Keys are spelled as in ``model``'s JSON Schema in both modes, so a field's
    name, ``alias`` and ``serialization_alias`` all count, as in
    :func:`lacing.location_fields`. Cached per model class.

    Raises:
        ValueError: a marker names a source that is not a non-derived sibling,
            or sits on a container item / union member instead of a whole field.
    """
    return frozenset(_derived(model))


def derived_prefills(model: type[BaseModel]) -> Mapping[DerivedPath, Any]:
    """Every path of :func:`derived_paths`, mapped to the value its field holds
    before it is filled: its declared JSON default, or ``None`` when there is
    none (see :func:`derived_defaults` for which paths have one).

    A fresh deep copy on every call, so mutating it cannot reach the cache.

    Raises:
        ValueError: as :func:`derived_paths`.
    """
    return {
        path: None if default is _NO_DEFAULT else deepcopy(default)
        for path, default in _derived(model).items()
    }


def derived_defaults(model: type[BaseModel]) -> dict[DerivedPath, Any]:
    """The JSON default each of ``model``'s :class:`Derived` fields declares,
    by path. For a plain default (``= ""``) that is what a ``model_dump()``
    stores before the field is filled; a ``field_serializer`` may store
    something else.

    Only paths with one unambiguous default: a required field has none, nor has
    a ``default_factory`` one (pydantic writes no JSON default for it), nor a
    path whose union members or schema modes disagree. A fresh deep copy on
    every call, so mutating it cannot reach the cache.

    Raises:
        ValueError: as :func:`derived_paths`.
    """
    return {
        path: deepcopy(default)
        for path, default in _derived(model).items()
        if default is not _NO_DEFAULT
    }


def drop_paths(value: Any, paths: PathSet) -> bool:
    """Delete, in place, the entries of the JSON-like ``value`` named by ``paths``;
    return whether any was there to delete."""
    return _edit_paths(value, ((path, _delete) for path in paths))


def null_paths(value: Any, paths: PathSet) -> bool:
    """Set, in place, the entries of the JSON-like ``value`` named by ``paths`` to
    ``None`` (keys that are absent stay absent); return whether any changed."""
    return fill_paths(value, dict.fromkeys(paths))


def fill_paths(value: Any, fills: Mapping[DerivedPath, Any]) -> bool:
    """Set, in place, each entry of the JSON-like ``value`` named by a path of
    ``fills`` to that path's value (keys that are absent stay absent); return
    whether any changed. Each entry gets its own deep copy of the value."""
    return _edit_paths(value, ((path, _setter(fill)) for path, fill in fills.items()))


def occurrences(value: Any, path: DerivedPath) -> list[tuple]:
    """The addresses (key and list-index steps) of every existing entry ``path``
    names in the JSON-like ``value``, in document order: the entries
    :func:`drop_paths` and :func:`fill_paths` would edit.

    >>> occurrences({"images": [{"id": "h"}, {}, {"id": None}]}, ("images", ANY_ITEM, "id"))
    [('images', 0, 'id'), ('images', 2, 'id')]
    """
    return [address for address, _, _ in _entries(value, path)]


def _entries(
    value: Any, path: Any, address: tuple = ()
) -> Iterator[tuple[tuple, dict, Any]]:
    """``(address, container, key)`` for every existing entry ``path`` names in
    ``value``, in document order: the one walk behind :func:`occurrences` and
    the edits. Lazy, so an edit made at one entry is seen by the walk after it
    (only the final key of a container is ever edited, which no later entry of
    the same path passes through)."""
    head, *rest = path
    if isinstance(value, dict):
        for key in list(value) if head is ANY_ITEM else [head]:
            if key not in value:
                continue
            if rest:
                yield from _entries(value[key], rest, (*address, key))
            else:
                yield (*address, key), value, key
    elif isinstance(value, list) and head is ANY_ITEM and rest:
        for index, item in enumerate(value):
            yield from _entries(item, rest, (*address, index))


def _delete(container: dict, key: Any) -> bool:
    del container[key]
    return True


_IMMUTABLE_JSON = (str, int, float, bool, type(None))


def _setter(fill: Any) -> Callable[[dict, Any], bool]:
    if fill is None:  # the common fill: no encoding needed, nothing to copy

        def set_none(container: dict, key: Any) -> bool:
            changed = container[key] is not None
            container[key] = None
            return changed

        return set_none
    fill_key = _json_key(fill)  # once per path, not once per entry
    copy = (lambda v: v) if isinstance(fill, _IMMUTABLE_JSON) else deepcopy

    def set_(container: dict, key: Any) -> bool:
        current = container[key]
        changed = current is not fill and _json_key(current) != fill_key
        container[key] = copy(fill)
        return changed

    return set_


def _edit_paths(
    value: Any, edits: Iterable[tuple[DerivedPath, Callable[[dict, Any], bool]]]
) -> bool:
    """Apply each ``(path, edit)`` pair to ``value`` (see :func:`_edit`); return
    whether any reported a change."""
    # a list, not a generator: ``any`` would stop at the first path edited
    return any([_edit(value, path, edit) for path, edit in edits])


def _edit(value: Any, path: DerivedPath, edit: Callable[[dict, Any], bool]) -> bool:
    """Apply ``edit(container, key)`` to every existing entry ``path`` names in
    ``value``; return whether any call reported a change."""
    edited = False
    for _, container, key in _entries(value, path):
        edited |= edit(container, key)  # every entry, even after a change
    return edited
