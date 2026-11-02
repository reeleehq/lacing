"""Derived-field marker: schema reading, path exclusion, and the value-digest scheme."""

from __future__ import annotations

from copy import deepcopy
from itertools import product
from typing import Annotated, Literal
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
    accepted_value_digests,
    annotation_value_digest,
    derived_paths,
    derived_prefills,
    registered_prefills,
    value_digest_matches,
)
from lacing.derived import derived_defaults, drop_paths, fill_paths, null_paths
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


# captured on main (before this change) for the annotation built in test below
GOLDEN_V1 = "525649d43ad4d09ade4f128a22778a90b619eff50eb0aec69f86f4933568426e"


def test_v1_digest_is_unchanged_and_unmarked_bodies_keep_it():
    from uuid import UUID

    ann = _ann({"images": [{"artifact_id": "a1", "asset_id": "h"}]}).model_copy(
        update={
            "id": UUID(int=1),
            "provenance": Provenance(
                was_generated_by="agent:m@1",
                was_attributed_to="thor",
                generated_at_time=RationalTime(5),
            ),
        }
    )
    assert annotation_value_digest(ann, scheme=V1) == GOLDEN_V1
    assert annotation_value_digest(ann) == GOLDEN_V1  # URI unregistered: no marker


def test_registration_rejects_a_bad_marker():
    class Bad(BaseModel):
        a: Annotated[str, Derived("missing")] = ""

    with pytest.raises(ValueError, match="non-derived"):
        register_body_schema("annot://schema/derived-bad/v1", Bad)
    assert "annot://schema/derived-bad/v1" not in schema_module._BODY_REGISTRY


class _Other(BaseModel):
    artifact_id: str = ""
    asset_id: str = ""


def test_union_excludes_only_what_every_alternative_marks():
    class U(BaseModel):
        img: Image | _Other | None = None

    class Same(BaseModel):
        img: Image | Image | None = None

    assert derived_paths(U) == frozenset()
    assert derived_paths(Same) == {("img", "asset_id")}


def test_tuple_positions_must_agree():
    class T(BaseModel):
        pair: tuple[Image, _Other]

    class T2(BaseModel):
        pair: tuple[Image, Image]

    assert derived_paths(T) == frozenset()
    assert derived_paths(T2) == {("pair", None, "asset_id")}


def test_map_values_are_not_walked_beside_declared_properties():
    class M(BaseModel, extra="allow"):
        meta: _Other = _Other()
        __pydantic_extra__: dict[str, Image]

    assert derived_paths(M) == frozenset()


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
    assert annotation_value_digest(
        a, resolve_derived=only_x
    ) == annotation_value_digest(b, resolve_derived=only_x)


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


# --- verifying a recorded digest across a marker addition (lacing#89) ---------


def _recorded_before_the_marker(body):
    """What a producer that had not registered the schema stored under v2."""
    assert not schema_module.is_registered(URI)
    return annotation_value_digest(_ann(body))


def test_a_digest_recorded_before_the_marker_still_matches(registered):
    body = {"images": [{"artifact_id": "a1"}], "asset_id": "root"}
    schema_module._BODY_REGISTRY.pop(URI)  # producer side: no marker known
    recorded = _recorded_before_the_marker(body)
    register_body_schema(URI, Body)

    assert annotation_value_digest(_ann(body)) != recorded  # the bug: reads changed
    assert value_digest_matches(_ann(body), recorded)
    filled = {"images": [{"artifact_id": "a1", "asset_id": "h"}], "asset_id": "root"}
    assert value_digest_matches(_ann(filled), recorded)


def test_a_pre_marker_digest_still_sees_real_changes(registered):
    schema_module._BODY_REGISTRY.pop(URI)
    recorded = _recorded_before_the_marker({"images": [{"artifact_id": "a1"}]})
    register_body_schema(URI, Body)

    for changed in (
        {"images": [{"artifact_id": "a2", "asset_id": "h"}]},  # source moved
        {"images": [{"artifact_id": "a1", "asset_id": "h"}], "asset_id": "x"},
        {"images": [{"artifact_id": "a1"}, {"artifact_id": "a3"}]},
    ):
        assert not value_digest_matches(_ann(changed), recorded), changed


def test_a_derived_value_recorded_unmarked_then_changed_reads_changed(registered):
    """The whole-body candidates need the derived field absent or unchanged:
    an unmarked producer that recorded ``asset_id="h"`` cannot vouch for
    ``asset_id="other"``. A spurious miss, not a wrong hit."""
    schema_module._BODY_REGISTRY.pop(URI)
    recorded = _recorded_before_the_marker(
        {"images": [{"artifact_id": "a1", "asset_id": "h"}]}
    )
    register_body_schema(URI, Body)
    assert not value_digest_matches(
        _ann({"images": [{"artifact_id": "a1", "asset_id": "other"}]}), recorded
    )


def test_a_current_digest_matches_itself(registered):
    ann = _ann({"images": [{"artifact_id": "a1", "asset_id": "h"}]})
    assert value_digest_matches(ann, annotation_value_digest(ann))
    unregistered = _ann({"x": 1}, uri="annot://schema/nope/v1")
    assert value_digest_matches(unregistered, annotation_value_digest(unregistered))


def test_an_unchanged_body_recorded_unmarked_with_the_derived_field_matches(
    registered,
):
    """Only the whole-body candidate can match here: the derived field was
    present when recorded, so dropping it from the current body changes it."""
    body = {"images": [{"artifact_id": "a1", "asset_id": "h"}]}
    schema_module._BODY_REGISTRY.pop(URI)
    recorded = _recorded_before_the_marker(body)
    register_body_schema(URI, Body)
    assert value_digest_matches(_ann(body), recorded)


def test_v1_traces_accept_a_filled_derived_field_not_a_changed_source(registered):
    def boom(uri):
        raise AssertionError("v1 digest must not consult the resolver")

    before = _ann({"images": [{"artifact_id": "a1"}]})
    recorded = annotation_value_digest(before, scheme=V1, resolve_derived=boom)
    assert value_digest_matches(before, recorded, scheme=V1)
    filled = _ann({"images": [{"artifact_id": "a1", "asset_id": "h"}]})
    assert value_digest_matches(filled, recorded, scheme=V1)
    moved = _ann({"images": [{"artifact_id": "a2", "asset_id": "h"}]})
    assert not value_digest_matches(moved, recorded, scheme=V1)


# --- a derived field stored as null before the fill (lacing#102) -------------

_NULL_BEFORE = {"images": [{"artifact_id": "a1", "asset_id": None}], "maybe": None}
_FILLED = {"images": [{"artifact_id": "a1", "asset_id": "h"}], "maybe": "m"}


def test_a_derived_field_stored_as_null_then_filled_matches_under_v2(registered):
    """What a ``model_dump()`` writer records: the key present, ``null``, until
    the late fill. Recorded by a producer that had not registered the schema."""
    schema_module._BODY_REGISTRY.pop(URI)
    recorded = _recorded_before_the_marker(_NULL_BEFORE)
    register_body_schema(URI, Body)
    assert value_digest_matches(_ann(_FILLED), recorded)
    assert recorded in accepted_value_digests(_ann(_FILLED))


def test_a_derived_field_stored_as_null_then_filled_matches_under_v1(registered):
    recorded = annotation_value_digest(_ann(_NULL_BEFORE), scheme=V1)
    assert value_digest_matches(_ann(_FILLED), recorded, scheme=V1)
    assert recorded in accepted_value_digests(_ann(_FILLED), scheme=V1)


def test_a_null_before_digest_still_sees_real_changes(registered):
    recorded = annotation_value_digest(_ann(_NULL_BEFORE), scheme=V1)
    for changed in (
        {"images": [{"artifact_id": "a2", "asset_id": "h"}], "maybe": "m"},
        {"images": [{"artifact_id": "a1", "asset_id": "h"}], "asset_id": "x"},
        {"images": [{"artifact_id": "a1", "asset_id": "h"}, {"artifact_id": "a3"}]},
    ):
        assert not value_digest_matches(_ann(changed), recorded, scheme=V1), changed


# --- a derived field stored at its declared default (lacing#109) ------------

_DEFAULT_BEFORE = {"images": [{"artifact_id": "a1", "asset_id": ""}]}  # Image()


def test_a_derived_field_stored_at_its_default_then_filled_matches_under_v2(
    registered,
):
    """``Image(artifact_id="a1").model_dump()`` stores ``asset_id=""`` until the
    fill. Recorded by a producer that had not registered the schema."""
    assert Image(artifact_id="a1").model_dump() == _DEFAULT_BEFORE["images"][0]
    schema_module._BODY_REGISTRY.pop(URI)
    recorded = _recorded_before_the_marker(_DEFAULT_BEFORE)
    register_body_schema(URI, Body)
    filled = _ann({"images": [{"artifact_id": "a1", "asset_id": "h"}]})
    assert value_digest_matches(filled, recorded)
    assert recorded in accepted_value_digests(filled)


def test_a_derived_field_stored_at_its_default_then_filled_matches_under_v1(
    registered,
):
    recorded = annotation_value_digest(_ann(_DEFAULT_BEFORE), scheme=V1)
    filled = _ann({"images": [{"artifact_id": "a1", "asset_id": "h"}]})
    assert value_digest_matches(filled, recorded, scheme=V1)
    moved = _ann({"images": [{"artifact_id": "a2", "asset_id": "h"}]})
    assert not value_digest_matches(moved, recorded, scheme=V1)


def test_an_injected_resolver_can_name_the_prefill_values():
    uri = "annot://schema/nope/v1"
    recorded = annotation_value_digest(_ann({"x": 1, "y": 0}, uri=uri))
    filled = _ann({"x": 1, "y": 9}, uri=uri)
    assert value_digest_matches(filled, recorded, resolve_derived=lambda u: {("y",): 0})
    assert not value_digest_matches(
        filled, recorded, resolve_derived=lambda u: {("y",)}
    )


def test_derived_defaults_reads_the_declared_defaults():
    assert derived_defaults(Body) == {
        ("images", None, "asset_id"): "",
        ("by_name", None, "asset_id"): "",
        ("maybe",): None,
    }


def test_a_required_or_ambiguous_derived_field_has_no_default():
    class A(BaseModel):
        kind: Literal["a"] = "a"
        src: str = ""
        out: Annotated[str, Derived("src")] = "x"

    class B(BaseModel):
        kind: Literal["b"] = "b"
        src: str = ""
        out: Annotated[str, Derived("src")] = "y"

    class Required(BaseModel):
        src: str = ""
        out: Annotated[str, Derived("src")]

    class Either(BaseModel):
        item: A | B

    assert derived_paths(Either) == {("item", "out")}
    assert derived_defaults(Either) == {}  # A says "x", B says "y"
    assert derived_paths(Required) == {("out",)}
    assert derived_defaults(Required) == {}
    assert derived_prefills(Either) == {("item", "out"): None}  # None when none


def test_defaults_are_handed_out_as_copies():
    class M(BaseModel):
        src: str = ""
        tags: Annotated[list[str], Derived("src")] = []

    derived_defaults(M)[("tags",)].append("x")
    derived_prefills(M)[("tags",)].append("x")
    assert derived_defaults(M) == derived_prefills(M) == {("tags",): []}
    fills = derived_prefills(M)
    a, b = {"tags": ["h"]}, {"tags": ["h"]}
    assert fill_paths(a, fills) and fill_paths(b, fills)
    a["tags"].append("y")
    assert b == {"tags": []} and fills == {("tags",): []}


def test_registered_prefills(registered):
    assert registered_prefills(URI) == derived_prefills(Body)
    assert registered_prefills("annot://schema/nope/v1") == {}


def test_fill_paths_tells_json_types_apart():
    assert fill_paths({"y": [0]}, {("y",): [False]})
    assert fill_paths({"y": 1}, {("y",): 1.0})


def test_matching_uses_the_injected_resolver():
    uri = "annot://schema/nope/v1"
    recorded = annotation_value_digest(_ann({"x": 1}, uri=uri))
    only_y = lambda uri: {("y",)}
    assert value_digest_matches(
        _ann({"x": 1, "y": 9}, uri=uri), recorded, resolve_derived=only_y
    )
    assert not value_digest_matches(_ann({"x": 1, "y": 9}, uri=uri), recorded)


def test_matching_refuses_an_unknown_scheme():
    with pytest.raises(ValueError, match="unknown value digest scheme"):
        value_digest_matches(_ann({}), "0" * 64, scheme="nope")


_ABSENT = object()  # "leave the key out", distinct from storing None


def _bodies():
    """A few dozen ``Body`` values that differ in derived and non-derived fields."""
    images = [
        [],
        [{"artifact_id": "a1"}],  # derived field absent
        [{"artifact_id": "a1", "asset_id": "h"}],
        [{"artifact_id": "a1", "asset_id": "h2"}],  # derived field different
        [{"artifact_id": "a1", "asset_id": None}],  # a different scalar
        [{"artifact_id": "a1", "asset_id": ""}],  # at its default (#109)
        [{"artifact_id": "a2", "asset_id": "h"}],  # source changed
    ]
    by_name = [
        None,
        {"k": {"artifact_id": "a1"}},
        {"k": {"artifact_id": "a1", "asset_id": "h"}},
        {"k": {"artifact_id": "a1", "asset_id": None}},  # stored as null (#102)
        {"k": {"artifact_id": "a1", "asset_id": ""}},  # at its default (#109)
    ]
    for imgs, root, maybe, named in product(
        images, (None, "root", "other"), (_ABSENT, None, "m"), by_name
    ):
        body = {"images": deepcopy(imgs)}
        if named is not None:
            body["by_name"] = deepcopy(named)
        if root is not None:
            body["asset_id"] = root  # NOT derived at the root
        if maybe is not _ABSENT:
            body["maybe"] = maybe
        yield body


def test_matching_is_sound_across_every_pair(registered):
    """A match, under either scheme, only ever means the recorded and current
    bodies agree outside today's derived paths: never a wrong hit."""
    bodies = list(_bodies())
    # Recorded by a producer that knew no marker, and by one that knew today's;
    # each distinct digest once, with the bodies it was recorded for.
    recorded = {scheme: {} for scheme in VALUE_DIGEST_SCHEMES}

    def record():
        for scheme, (r, b) in product(VALUE_DIGEST_SCHEMES, enumerate(bodies)):
            digest = annotation_value_digest(_ann(b), scheme=scheme)
            recorded[scheme].setdefault(digest, set()).add(r)

    schema_module._BODY_REGISTRY.pop(URI)
    record()
    register_body_schema(URI, Body)
    record()
    nulls_only = lambda uri: dict.fromkeys(derived_paths(Body))  # no default fill

    def dropped(body):
        """Today's derived fields removed, by hand: the oracle shares no code
        with the implementation."""
        out = deepcopy(_ann(body).model_dump(mode="json")["body"])
        out.pop("maybe", None)
        for image in [*out.get("images", []), *out.get("by_name", {}).values()]:
            image.pop("asset_id", None)
        return out

    stripped = [dropped(b) for b in bodies]
    fallback_hits = default_only_hits = 0
    for scheme in VALUE_DIGEST_SCHEMES:
        for c, current in enumerate(bodies):
            ann = _ann(current)
            accepted = accepted_value_digests(ann, scheme=scheme)
            without_defaults = accepted_value_digests(
                ann, scheme=scheme, resolve_derived=nulls_only
            )
            for digest, rs in recorded[scheme].items():
                matches = value_digest_matches(ann, digest, scheme=scheme)
                assert matches == (digest in accepted)
                if matches:
                    for r in rs:
                        assert stripped[r] == stripped[c], (scheme, bodies[r], current)
                        fallback_hits += bodies[r] != current
                    default_only_hits += digest not in without_defaults
    assert fallback_hits  # not vacuous: some differing bodies do match
    assert default_only_hits  # and some only through the default fill (#109)
    # The hand-written oracle above is right only for these paths.
    assert derived_paths(Body) == {
        ("images", None, "asset_id"),
        ("by_name", None, "asset_id"),
        ("maybe",),
    }


def test_drop_paths_reports_whether_anything_was_dropped():
    paths = {("images", None, "asset_id"), ("maybe",)}
    unfilled = {"images": [{"artifact_id": "a1"}]}
    assert drop_paths(unfilled, paths) is False
    filled = {"images": [{"artifact_id": "a1"}, {"artifact_id": "a2", "asset_id": "h"}]}
    assert drop_paths(filled, paths) is True
    assert filled == {"images": [{"artifact_id": "a1"}, {"artifact_id": "a2"}]}


def test_null_paths_sets_present_entries_to_none_and_reports_a_change():
    paths = {("images", None, "asset_id"), ("maybe",)}
    unfilled = {"images": [{"artifact_id": "a1"}, {"asset_id": None}]}
    assert null_paths(unfilled, paths) is False  # absent stays absent, None stays
    assert unfilled == {"images": [{"artifact_id": "a1"}, {"asset_id": None}]}
    filled = {"images": [{"artifact_id": "a1"}, {"asset_id": "h"}], "maybe": None}
    assert null_paths(filled, paths) is True
    assert filled == {
        "images": [{"artifact_id": "a1"}, {"asset_id": None}],
        "maybe": None,
    }


def test_fill_paths_sets_each_present_entry_to_its_own_value():
    body = {"images": [{"asset_id": "h"}, {}], "maybe": "m"}
    assert fill_paths(body, {("images", None, "asset_id"): "", ("maybe",): None})
    assert body == {"images": [{"asset_id": ""}, {}], "maybe": None}
    assert not fill_paths(body, {("images", None, "asset_id"): ""})  # no change
