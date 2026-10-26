# lacing.locations

Which body fields hold locations (urls, file paths).

A body schema marks a field whose value is a location by annotating it with
[`Location`](#lacing.locations.Location); consumers that must treat locations specially (redaction,
write gates, edit guards) ask the schema instead of guessing from key names:

```default
from typing import Annotated
from pydantic import BaseModel
from lacing import Location, location_fields

class Body(BaseModel):
    before_image: Annotated[str, Location("path")] = ""
    label: str = ""

location_fields(Body)  # {'before_image': 'path'}
Body.model_json_schema()["properties"]["before_image"]["x-location"]  # 'path'
```

The marker is carried into the exported JSON Schema as `x-location` (the raw
schema only: json-schema-to-zod drops `x-*` keys), and
[`lacing.schema.body_locations()`](lacing.schema.html.md#lacing.schema.body_locations) answers for a registered
`body_schema_uri`. A marker may sit on the field as a whole
(`Annotated[str | None, Location("url")]`, `Annotated[dict[str, str], ...]`)
or inside a container (`list[Annotated[str, Location("path")]]`), and on
fields of nested models: [`location_fields()`](#lacing.locations.location_fields) reads the same JSON Schema the
export writes, so the two cannot disagree. For a marked map, the *values* are
the locations, not the keys.

### Functions

| [`location_fields`](#lacing.locations.location_fields)(model)   | `{field spelling: kind}` for the [`Location`](#lacing.locations.Location)-marked fields of `model` and of the models nested in it.   |
|---------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|

### Classes

| [`Location`](#lacing.locations.Location)(kind)   | Field marker: this body field holds a location of `kind`.   |
|-------------------------------------------------------------------|-------------------------------------------------------------|

### *class* lacing.locations.Location(kind)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Field marker: this body field holds a location of `kind`.

### lacing.locations.location_fields(model)

`{field spelling: kind}` for the [`Location`](#lacing.locations.Location)-marked fields of `model`
and of the models nested in it.

Spellings are the property names of `model`’s JSON Schema in both modes,
so a field’s name (`populate_by_name`), `alias`, `validation_alias` and `serialization_alias`
all count. A name marked with two kinds is an error.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'url'`, `'path'`]]
