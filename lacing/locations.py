"""Which body fields hold locations (urls, file paths).

A body schema marks a field whose value is a location by annotating it with
:class:`Location`; consumers that must treat locations specially (redaction,
write gates, edit guards) ask the schema instead of guessing from key names::

    from typing import Annotated
    from pydantic import BaseModel
    from lacing import Location, location_fields

    class Body(BaseModel):
        before_image: Annotated[str, Location("path")] = ""
        label: str = ""

    location_fields(Body)  # {'before_image': 'path'}
    Body.model_json_schema()["properties"]["before_image"]["x-location"]  # 'path'

The marker is carried into the exported JSON Schema as ``x-location`` (the raw
schema only: json-schema-to-zod drops ``x-*`` keys), and
:func:`lacing.schema.body_locations` answers for a registered
``body_schema_uri``. A marker may sit on the field as a whole
(``Annotated[str | None, Location("url")]``, ``Annotated[dict[str, str], ...]``)
or inside a container (``list[Annotated[str, Location("path")]]``), and on
fields of nested models: :func:`location_fields` reads the same JSON Schema the
export writes, so the two cannot disagree. For a marked map, the *values* are
the locations, not the keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Literal

from pydantic import BaseModel

LocationKind = Literal["url", "path"]

__all__ = ["Location", "LocationKind", "location_fields"]


_KINDS = ("url", "path")
_SCHEMA_MODES = ("validation", "serialization")


@dataclass(frozen=True)
class Location:
    """Field marker: this body field holds a location of ``kind``."""

    kind: LocationKind

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(
                f"Location kind must be one of {_KINDS}, got {self.kind!r}"
            )

    def __get_pydantic_json_schema__(self, core_schema: Any, handler: Any) -> dict:
        schema = handler(core_schema)
        if schema.get("x-location", self.kind) != self.kind:
            raise ValueError(
                f"a field is marked with two location kinds: "
                f"{schema['x-location']!r} and {self.kind!r}"
            )
        return {**schema, "x-location": self.kind}


def _own_kinds(schema: Any) -> set[str]:
    """``x-location`` kinds in ``schema`` and its containers/unions, not following ``$ref``."""
    if isinstance(schema, list):
        return set().union(*map(_own_kinds, schema)) if schema else set()
    if not isinstance(schema, dict):
        return set()
    kinds = {schema["x-location"]} if "x-location" in schema else set()
    for key in (
        "anyOf",
        "oneOf",
        "allOf",
        "prefixItems",
        "items",
        "additionalProperties",
    ):
        kinds |= _own_kinds(schema.get(key))
    return kinds


def _marked_properties(schema: dict) -> dict[str, LocationKind]:
    out: dict[str, LocationKind] = {}
    for node in [schema, *schema.get("$defs", {}).values()]:
        for name, prop in node.get("properties", {}).items():
            kinds = _own_kinds(prop)
            if len(kinds) > 1:
                raise ValueError(f"field {name!r} is marked with two location kinds")
            for kind in kinds:
                if out.setdefault(name, kind) != kind:
                    raise ValueError(
                        f"{name!r} is declared both {out[name]!r} and {kind!r}"
                    )
    return out


def location_fields(model: type[BaseModel]) -> dict[str, LocationKind]:
    """``{field spelling: kind}`` for the :class:`Location`-marked fields of ``model``
    and of the models nested in it.

    Spellings are the property names of ``model``'s JSON Schema in both modes,
    so a field's name (``populate_by_name``), ``alias``, ``validation_alias`` and ``serialization_alias``
    all count. A name marked with two kinds is an error.
    """
    out: dict[str, LocationKind] = {}
    for mode, by_alias in product(_SCHEMA_MODES, (True, False)):
        for name, kind in _marked_properties(
            model.model_json_schema(mode=mode, by_alias=by_alias)
        ).items():
            if out.setdefault(name, kind) != kind:
                raise ValueError(
                    f"{name!r} is declared both {out[name]!r} and {kind!r}"
                )
    return out
