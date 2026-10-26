"""``Location`` marker: which body fields hold urls/paths."""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

import lacing
from lacing import Location, body_locations, location_fields
from lacing.schema import _BODY_REGISTRY, json_schema, register_body_schema

URI = "annot://schema/loc-demo/v1"


class Body(BaseModel):
    before_image: Annotated[str, Location("path")] = ""
    still: Annotated[str | None, Location("url")] = None
    views: Annotated[dict[str, str], Location("url")] = Field(default_factory=dict)
    renamed: Annotated[str, Location("url")] = Field("", alias="renamedAlias")
    label: str = ""
    model_config = {"populate_by_name": True}


@pytest.fixture
def registered():
    register_body_schema(URI, Body)
    yield URI
    _BODY_REGISTRY.pop(URI, None)


def test_marked_fields_by_every_spelling():
    assert location_fields(Body) == {
        "before_image": "path",
        "still": "url",
        "views": "url",
        "renamed": "url",
        "renamedAlias": "url",
    }


def test_unmarked_model_has_none():
    class Plain(BaseModel):
        label: str = ""

    assert location_fields(Plain) == {}


def test_two_kinds_on_one_field_is_an_error():
    class Bad(BaseModel):
        x: Annotated[str, Location("url"), Location("path")] = ""

    with pytest.raises(ValueError, match="two location kinds"):
        location_fields(Bad)


def test_body_locations_by_registered_uri(registered):
    assert body_locations(registered)["before_image"] == "path"
    with pytest.raises(lacing.UnknownBodySchemaError):
        body_locations("annot://schema/nope/v1")


def test_marker_is_exported_in_json_schema(registered):
    props = json_schema(registered)["properties"]
    assert props["before_image"]["x-location"] == "path"
    assert props["still"]["x-location"] == "url"
    assert props["views"]["x-location"] == "url"
    assert "x-location" not in props["label"]
    assert Body(before_image="a.png").before_image == "a.png"  # validation untouched
