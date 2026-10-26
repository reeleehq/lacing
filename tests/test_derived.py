"""Derived-field marker: schema reading, path exclusion, and the value-digest scheme."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field

from lacing import (
    Annotation,
    Derived,
    MediaRef,
    Provenance,
    RationalTime,
    TimeInterval,
    annotation_value_digest,
    derived_paths,
)
from lacing.digest import VALUE_DIGEST_SCHEME, VALUE_DIGEST_SCHEMES
from lacing import schema as schema_module
from lacing.schema import register_body_schema

URI = "annot://schema/derived-test/v1"
V1 = VALUE_DIGEST_SCHEMES[0]


class Image(BaseModel):
    artifact_id: str = ""
    asset_id: Annotated[str, Derived("artifact_id")] = ""


class Body(BaseModel):
    images: list[Image] = []
    by_name: dict[str, Image] = {}
    asset_id: str = ""  # same name as the derived one, NOT derived at the root
    maybe: Annotated[str | None, Derived("asset_id")] = None


@pytest.fixture
def registered():
    register_body_schema(URI, Body)
    yield
    schema_module._BODY_REGISTRY.pop(URI, None)


def _ann(body, uri=URI):
    return Annotation(
        id=uuid4(),
        tier="t",
        reference=MediaRef(
            asset_id="sha256:abc",
            interval=TimeInterval(RationalTime(0), RationalTime(24000)),
        ),
        body=body,
        body_schema_uri=uri,
        provenance=Provenance(
            was_generated_by="agent:m@1",
            was_attributed_to="thor",
            generated_at_time=RationalTime.now(),
        ),
    )


def test_paths_are_exact_not_by_name():
    assert derived_paths(Body) == {
        ("images", None, "asset_id"),
        ("by_name", None, "asset_id"),
        ("maybe",),
    }


def test_marker_lands_in_json_schema():
    props = Image.model_json_schema()["properties"]
    assert props["asset_id"]["x-derived"] == "artifact_id"


def test_filling_a_derived_field_keeps_the_digest(registered):
    before = _ann({"images": [{"artifact_id": "a1"}], "asset_id": "root"})
    after = _ann(
        {"images": [{"artifact_id": "a1", "asset_id": "h"}], "asset_id": "root"}
    )
    assert annotation_value_digest(before) == annotation_value_digest(after)


def test_source_and_same_named_other_fields_still_count(registered):
    base = _ann({"images": [{"artifact_id": "a1"}], "asset_id": "root"})
    assert annotation_value_digest(base) != annotation_value_digest(
        _ann({"images": [{"artifact_id": "a2"}], "asset_id": "root"})
    )
    assert annotation_value_digest(base) != annotation_value_digest(
        _ann({"images": [{"artifact_id": "a1"}], "asset_id": "other"})
    )


def test_v1_scheme_still_digests_the_whole_body(registered):
    before = _ann({"images": [{"artifact_id": "a1"}]})
    after = _ann({"images": [{"artifact_id": "a1", "asset_id": "h"}]})
    assert annotation_value_digest(before, scheme=V1) != annotation_value_digest(
        after, scheme=V1
    )
    assert annotation_value_digest(before, scheme=V1) != annotation_value_digest(before)


def test_does_not_mutate_the_annotation(registered):
    body = {"images": [{"artifact_id": "a1", "asset_id": "h"}]}
    ann = _ann(body)
    annotation_value_digest(ann)
    assert ann.body == {"images": [{"artifact_id": "a1", "asset_id": "h"}]}


def test_unregistered_schema_excludes_nothing():
    a = _ann({"x": 1}, uri="annot://schema/nope/v1")
    b = _ann({"x": 2}, uri="annot://schema/nope/v1")
    assert annotation_value_digest(a) != annotation_value_digest(b)


def test_injected_resolver_wins():
    a = _ann({"x": 1, "y": 1}, uri="annot://schema/nope/v1")
    b = _ann({"x": 2, "y": 1}, uri="annot://schema/nope/v1")
    only_x = lambda uri: {("x",)}
    assert annotation_value_digest(a, derived_paths=only_x) == annotation_value_digest(
        b, derived_paths=only_x
    )


def test_unknown_scheme_is_refused():
    with pytest.raises(ValueError, match="unknown value digest scheme"):
        annotation_value_digest(_ann({}), scheme="nope")


def test_source_must_be_a_non_derived_sibling():
    class NoSource(BaseModel):
        a: Annotated[str, Derived("missing")] = ""

    class Chain(BaseModel):
        a: str = ""
        b: Annotated[str, Derived("a")] = ""
        c: Annotated[str, Derived("b")] = ""

    for model in (NoSource, Chain):
        with pytest.raises(ValueError, match="non-derived"):
            derived_paths(model)


def test_marker_inside_a_container_is_refused():
    class Inner(BaseModel):
        src: str = ""
        xs: list[Annotated[str, Derived("src")]] = Field(default_factory=list)

    with pytest.raises(ValueError, match="as a whole"):
        derived_paths(Inner)


def test_recursive_model_terminates():
    class Node(BaseModel):
        src: str = ""
        d: Annotated[str, Derived("src")] = ""
        kids: list["Node"] = []

    Node.model_rebuild()
    assert ("d",) in derived_paths(Node)


def test_bad_marker_source():
    with pytest.raises(ValueError):
        Derived("")


def test_scheme_constants():
    assert VALUE_DIGEST_SCHEME == VALUE_DIGEST_SCHEMES[-1] != V1
