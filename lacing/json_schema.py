"""JSON Schema generation that exports ``default_factory`` defaults.

Pydantic writes a ``default`` into a field's JSON Schema only for a literal
``default=``; a ``default_factory`` field exports no ``default`` at all. A
schema-derived zod mirror then parses an absent value as ``undefined`` where the
Python model says ``[]`` / ``{}`` (lacing#40, #62).

:class:`DefaultFactoryJsonSchema` closes that gap for every field at once, so
no model has to remember a per-field ``json_schema_extra={"default": ...}``:
it calls each zero-argument factory and, when the result is JSON-serialisable,
writes it as the field's ``default``. Adding a schema ``default`` never
invalidates an existing document (the field stays optional), so this is
additive.

Use it as ``Model.model_json_schema(schema_generator=DefaultFactoryJsonSchema)``
(:func:`lacing.schema.json_schema` and ``export_json_schemas`` do), or inherit
:class:`SchemaModel` so a plain ``Model.model_json_schema()`` does the same.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode


class DefaultFactoryJsonSchema(GenerateJsonSchema):
    """``GenerateJsonSchema`` that also emits ``default`` for zero-argument factories.

    A factory that takes the validated data, or whose result cannot be encoded
    as JSON, is left without a ``default`` (there is no honest static value).

    >>> from pydantic import BaseModel, Field
    >>> class M(BaseModel):
    ...     tags: tuple[str, ...] = Field(default_factory=tuple)
    ...     meta: dict = Field(default_factory=dict)
    >>> props = M.model_json_schema(schema_generator=DefaultFactoryJsonSchema)["properties"]
    >>> props["tags"]["default"], props["meta"]["default"]
    ([], {})
    """

    def default_schema(self, schema: Any) -> dict[str, Any]:
        json_schema = super().default_schema(schema)
        factory = schema.get("default_factory")
        if (
            factory is None
            or "default" in json_schema
            or schema.get("default_factory_takes_data")
        ):
            return json_schema
        try:
            json_schema["default"] = self.encode_default(factory())
        except Exception:  # noqa: BLE001 - not JSON-serialisable: export none
            pass
        return json_schema


class SchemaModel(BaseModel):
    """``BaseModel`` whose ``model_json_schema()`` exports ``default_factory`` defaults."""

    @classmethod
    def model_json_schema(  # type: ignore[override]
        cls,
        by_alias: bool = True,
        ref_template: str = "#/$defs/{model}",
        schema_generator: type[GenerateJsonSchema] = DefaultFactoryJsonSchema,
        mode: JsonSchemaMode = "validation",
        **kwargs: Any,
    ) -> dict[str, Any]:
        return super().model_json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
            **kwargs,
        )
