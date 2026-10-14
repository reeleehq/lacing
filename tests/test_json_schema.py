"""``default_factory`` fields export their default in the JSON Schema (lacing#62).

``default_factory`` alone writes no ``default``, so a schema-derived zod mirror
parses an absent value as ``undefined``. :class:`DefaultFactoryJsonSchema`
closes that for every field, and these tests guard every registered body so a
future ``default_factory`` field cannot slip through.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

import lacing.bodies  # noqa: F401  (registers the body schemas)
from lacing.json_schema import DefaultFactoryJsonSchema, SchemaModel
from lacing.model import Annotation, Provenance
from lacing.schema import export_json_schemas, get_body_schema, registered_uris

COMMITTED = Path(__file__).resolve().parents[1] / "lacing" / "schema"


def _zero_arg_factory_fields(model: type[BaseModel]):
    for name, field in model.model_fields.items():
        factory = field.default_factory
        if factory is not None and not field.default_factory_takes_validated_data:
            yield name, field


@pytest.mark.parametrize("uri", registered_uris())
def test_every_default_factory_field_of_a_body_exports_its_default(uri):
    from lacing.schema import json_schema

    model = get_body_schema(uri)
    props = json_schema(uri).get("properties", {})
    for name, field in _zero_arg_factory_fields(model):
        key = field.alias or name
        assert "default" in props[key], f"{uri}: {name} exports no default"
        # The exported default is what the model actually defaults to.
        instance = model.model_construct()
        assert props[key]["default"] == json.loads(json.dumps(getattr(instance, name)))
        assert key not in json_schema(uri).get("required", [])


def test_the_reported_fields_now_export_a_default():
    from lacing.schema import json_schema

    props = json_schema("annot://schema/review/v1")["properties"]
    assert props["target_annotation_ids"]["default"] == []
    props = json_schema("annot://schema/continuity-violation/v1")["properties"]
    assert props["evidence"]["default"] == {}
    props = json_schema("annot://schema/reference-lock/v1")["properties"]
    assert props["params"]["default"] == {}


def test_envelope_provenance_exports_its_default_too():
    assert Provenance.model_json_schema()["properties"]["was_derived_from"][
        "default"
    ] == []
    defs = Annotation.model_json_schema()["$defs"]["Provenance"]["properties"]
    assert defs["was_derived_from"]["default"] == []


def test_committed_schemas_match_the_models(tmp_path):
    """Regenerate with ``export_json_schemas('lacing/schema')`` after a model change."""
    export_json_schemas(tmp_path)
    for fresh in tmp_path.rglob("*.json"):
        committed = COMMITTED / fresh.relative_to(tmp_path)
        assert json.loads(committed.read_text()) == json.loads(fresh.read_text()), (
            f"{committed.relative_to(COMMITTED.parent.parent)} is stale"
        )


def test_plain_base_models_get_the_default_through_the_generator():
    class Plain(BaseModel):
        xs: list[int] = Field(default_factory=list)

    props = Plain.model_json_schema(schema_generator=DefaultFactoryJsonSchema)[
        "properties"
    ]
    assert props["xs"]["default"] == []
    assert "default" not in Plain.model_json_schema()["properties"]["xs"]


def test_schema_model_does_it_without_being_asked():
    class Mine(SchemaModel):
        xs: list[int] = Field(default_factory=list)

    assert Mine.model_json_schema()["properties"]["xs"]["default"] == []


def test_factories_with_no_honest_static_default_are_left_alone():
    class Odd(SchemaModel):
        model_config = {"arbitrary_types_allowed": True}
        stamp: object = Field(default_factory=object)  # not JSON-encodable
        derived: int = Field(default_factory=lambda data: len(data))  # needs data

    props = Odd.model_json_schema()["properties"]
    assert "default" not in props["stamp"]
    assert "default" not in props["derived"]
