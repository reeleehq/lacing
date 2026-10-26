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
every key of that name elsewhere in the body.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from typing import Any

from pydantic import BaseModel

__all__ = ["Derived", "DerivedPath", "ANY_ITEM", "derived_paths", "drop_paths"]

#: One step of a path through a body: an object key, or :data:`ANY_ITEM`.
DerivedPath = tuple["str | None", ...]

#: Path step standing for "every element of a list / every value of a map".
ANY_ITEM = None

_SCHEMA_MODES = ("validation", "serialization")
_MARK = "x-derived"
_COMBINATORS = ("anyOf", "oneOf", "allOf")
_ITEM_KEYS = ("items", "prefixItems", "additionalProperties")


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


def _collect(
    node: Any, defs: dict, prefix: DerivedPath, stack: tuple[str, ...], out: set
) -> None:
    """Add to ``out`` the path of every marked property reachable from ``node``."""
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
            out.add((*prefix, name))
    for key in _COMBINATORS:
        for member in node.get(key, ()):
            _collect(member, defs, prefix, stack, out)
    for key in _ITEM_KEYS:
        sub = node.get(key)
        for member in sub if isinstance(sub, list) else (sub,):
            _collect(member, defs, (*prefix, ANY_ITEM), stack, out)


@lru_cache(maxsize=256)
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
    out: set[DerivedPath] = set()
    for mode, by_alias in product(_SCHEMA_MODES, (True, False)):
        schema = model.model_json_schema(mode=mode, by_alias=by_alias)
        _collect(schema, schema.get("$defs", {}), (), (), out)
    return frozenset(out)


def drop_paths(value: Any, paths: frozenset[DerivedPath] | set[DerivedPath]) -> None:
    """Delete, in place, the entries of the JSON-like ``value`` named by ``paths``."""
    for path in paths:
        _drop(value, path)


def _drop(value: Any, path: DerivedPath) -> None:
    head, *rest = path
    if isinstance(value, dict):
        targets = list(value) if head is ANY_ITEM else [head]
        for key in targets:
            if key not in value:
                continue
            if rest:
                _drop(value[key], tuple(rest))
            else:
                del value[key]
    elif isinstance(value, list) and head is ANY_ITEM and rest:
        for item in value:
            _drop(item, tuple(rest))
