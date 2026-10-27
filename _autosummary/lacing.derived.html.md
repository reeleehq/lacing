# lacing.derived

Which body fields are *derived* from another field of the same object.

A body schema marks a field whose value can be recomputed from a sibling field
by annotating it with [`Derived`](#lacing.derived.Derived), naming that sibling:

```default
from typing import Annotated
from pydantic import BaseModel
from lacing import Derived, derived_paths

class PanelImage(BaseModel):
    artifact_id: str = ""
    asset_id: Annotated[str, Derived("artifact_id")] = ""   # hash of the bytes

class Body(BaseModel):
    images: list[PanelImage] = []

derived_paths(Body)  # {('images', None, 'asset_id')}   (None = any list item / map value)
```

The reason to mark one: a host sometimes learns the value *after* the annotation
was saved (a content hash known only once an upload is ingested). Writing it
changes nothing a render reads, so [`lacing.annotation_value_digest()`](lacing.html.md#lacing.annotation_value_digest) leaves
derived fields out and the write does not make downstream results look stale.

The marker is carried into the exported JSON Schema as `x-derived` (the raw
schema only: json-schema-to-zod drops `x-*` keys), and [`derived_paths()`](#lacing.derived.derived_paths)
reads that same schema, so the export and the digest cannot disagree.

Two rules keep the exclusion honest, since leaving out a field that is *not*
derivable would make two different values digest alike (a wrong cache hit):

- the marker names a **source** field that exists in the same object and is
  itself not derived (a schema error otherwise, raised by [`derived_paths()`](#lacing.derived.derived_paths));
- it sits on a field as a whole, not inside a container (`list[Annotated[...]]`
  is refused, since “the sibling” would then be undefined).

Paths are exact: only the marked field of the marked model is excluded, not
every key of that name elsewhere in the body. Where a path is ambiguous it is
dropped, never guessed: in a union (`A | B`) a field is excluded only if every
object alternative marks it, tuple positions must agree, and the values of a map
that also declares properties are not walked. A recursive model is walked one
level only. Each of these costs at most a spurious cache miss, never a wrong hit.
Field names and aliases are both read as spellings of a field, as in
[`lacing.location_fields()`](lacing.html.md#lacing.location_fields).

### Module Attributes

| [`DerivedPath`](#lacing.derived.DerivedPath)   | an object key, or [`ANY_ITEM`](#lacing.derived.ANY_ITEM).   |
|----------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`ANY_ITEM`](#lacing.derived.ANY_ITEM)      | Path step standing for "every element of a list / every value of a map".       |

### Functions

| [`derived_paths`](#lacing.derived.derived_paths)(model)     | The paths, from the root of a `model` body, of its [`Derived`](#lacing.derived.Derived) fields.   |
|---------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`drop_paths`](#lacing.derived.drop_paths)(value, paths) | Delete, in place, the entries of the JSON-like `value` named by `paths`; return whether any was there to delete.      |

### Classes

| [`Derived`](#lacing.derived.Derived)(source)   | Field marker: this body field is derivable from the sibling field `source`.   |
|--------------------------------------------------------------------|-------------------------------------------------------------------------------|

### lacing.derived.ANY_ITEM *= None*

Path step standing for “every element of a list / every value of a map”.

### *class* lacing.derived.Derived(source)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Field marker: this body field is derivable from the sibling field `source`.

### lacing.derived.DerivedPath

an object key, or [`ANY_ITEM`](#lacing.derived.ANY_ITEM).

* **Type:**
  One step of a path through a body

alias of [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[str | None, …]

### lacing.derived.derived_paths(model)

The paths, from the root of a `model` body, of its [`Derived`](#lacing.derived.Derived) fields.

A step is an object key or [`ANY_ITEM`](#lacing.derived.ANY_ITEM) (every list element / map value).
Keys are spelled as in `model`’s JSON Schema in both modes, so a field’s
name, `alias` and `serialization_alias` all count, as in
[`lacing.location_fields()`](lacing.html.md#lacing.location_fields). Cached per model class.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – a marker names a source that is not a non-derived sibling,
      or sits on a container item / union member instead of a whole field.
* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]]

### lacing.derived.drop_paths(value, paths)

Delete, in place, the entries of the JSON-like `value` named by `paths`;
return whether any was there to delete.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
