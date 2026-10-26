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

The marker is carried into the exported JSON Schema as ``x-location`` (so the
Zod side can read it), and :func:`lacing.schema.body_locations` answers for a
registered ``body_schema_uri``. The marker applies to the field as a whole
(``Annotated[str | None, Location("url")]``, ``Annotated[list[str], ...]``): a
map or list field takes the kind for every string it holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

LocationKind = Literal["url", "path"]

__all__ = ["Location", "LocationKind", "location_fields"]


@dataclass(frozen=True)
class Location:
    """Field marker: this body field holds a location of ``kind``."""

    kind: LocationKind

    def __get_pydantic_json_schema__(self, core_schema: Any, handler: Any) -> dict:
        schema = handler(core_schema)
        return {**schema, "x-location": self.kind}


def location_fields(model: type[BaseModel]) -> dict[str, LocationKind]:
    """``{field spelling: kind}`` for the :class:`Location`-marked fields of ``model``.

    Every spelling a body may arrive in counts: the field name and its
    ``alias`` / ``serialization_alias``.
    """
    out: dict[str, LocationKind] = {}
    for name, field in model.model_fields.items():
        kinds = {m.kind for m in field.metadata if isinstance(m, Location)}
        if len(kinds) > 1:
            raise ValueError(f"field {name!r} is marked with two location kinds")
        for kind in kinds:
            for spelling in {name, field.alias, field.serialization_alias} - {None}:
                out[spelling] = kind
    return out
