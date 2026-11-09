"""Derived-field marker: schema reading, path exclusion, and the value-digest scheme."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
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
from lacing.digest import (
    MAX_MIXED_FILLS,
    VALUE_DIGEST_SCHEME,
    VALUE_DIGEST_SCHEMES,
    _value_digests,
)
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
                # the set, not the lazy check: each miss of the lazy one tries
                # every mixed-state body (lacing#152); their agreement and order
                # are tested on their own below
                matches = digest in accepted
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


def test_null_and_fill_paths_accept_values_that_are_not_json():
    body = {"maybe": datetime(2026, 1, 1), "images": [{"asset_id": {1, 2}}]}
    assert null_paths(body, {("maybe",), ("images", None, "asset_id")}) is True
    assert body == {"maybe": None, "images": [{"asset_id": None}]}


# --- bodies recorded in mixed fill states (lacing#152) ------------------------


def _images(*states):
    """A body of images; each image's ``asset_id`` is a value, None, or _ABSENT."""
    images = []
    for i, state in enumerate(states):
        image = {"artifact_id": f"a{i}"}
        if state is not _ABSENT:
            image["asset_id"] = state
        images.append(image)
    return {"images": images}


def _recorded_unaware(body):
    """The v1 digest a producer that knew no derived path recorded for ``body``."""
    schema_module._BODY_REGISTRY.pop(URI)
    try:
        return annotation_value_digest(_ann(body), scheme=V1)
    finally:
        register_body_schema(URI, Body)


@pytest.mark.parametrize(
    "recorded_states",
    [("h0", None), (_ABSENT, None), (None, _ABSENT), ("h0", _ABSENT), ("h0", "")],
)
@pytest.mark.parametrize("scheme", VALUE_DIGEST_SCHEMES)
def test_a_body_recorded_in_mixed_fill_states_matches_after_the_fill(
    registered, recorded_states, scheme
):
    """Images filled one at a time: recorded with one filled and the other null
    or absent (or at its default), verified once both are filled."""
    schema_module._BODY_REGISTRY.pop(URI)  # recorded by a producer unaware of D
    recorded = annotation_value_digest(_ann(_images(*recorded_states)), scheme=V1)
    register_body_schema(URI, Body)
    filled = _ann(_images("h0", "h1"))
    assert value_digest_matches(filled, recorded, scheme=scheme)
    assert recorded in accepted_value_digests(filled, scheme=scheme)


def test_a_mixed_state_match_still_needs_the_rest_of_the_body_unchanged(registered):
    schema_module._BODY_REGISTRY.pop(URI)
    recorded = annotation_value_digest(_ann(_images("h0", None)), scheme=V1)
    register_body_schema(URI, Body)
    moved = _images("h0", "h1")
    moved["images"][1]["artifact_id"] = "other"  # a source changed
    assert not value_digest_matches(_ann(moved), recorded)
    # a filled occurrence whose value differs from today's is not vouched for
    assert not value_digest_matches(
        _ann(_images("h0", "h1")),
        annotation_value_digest(_ann(_images("x", None)), scheme=V1),
    )


def _budget_needed(ann, recorded):
    """The smallest ``max_mixed_fills`` under which ``recorded`` matches ``ann``:
    its 1-based place among the mixed candidates (None if it is not one)."""
    uniform = list(_value_digests(ann, V1, None, max_mixed_fills=0))
    mixed = list(_value_digests(ann, V1, None))[len(uniform) :]
    return mixed.index(recorded) + 1 if recorded in mixed else None


def test_mixed_states_past_the_budget_read_as_changed(registered):
    """A body recorded in a mixed state matches under a budget that reaches it,
    and reads as changed one below."""
    filled = _ann(_images("h0", "h1", "h2"))
    recorded = _recorded_unaware(_images("h0", _ABSENT, None))
    k = _budget_needed(filled, recorded)
    assert k is not None and k > 1
    assert value_digest_matches(filled, recorded, max_mixed_fills=k)
    assert recorded in accepted_value_digests(filled, max_mixed_fills=k)
    assert not value_digest_matches(filled, recorded, max_mixed_fills=k - 1)
    assert recorded not in accepted_value_digests(filled, max_mixed_fills=k - 1)


def test_uniform_candidates_come_first_and_none_repeats(registered):
    """A normal match costs what it did before lacing#152: the candidates the
    uniform fallbacks produced (whole, absent, null, default) come first, in
    that order, then only mixed ones, each digest once."""
    ann = _ann(_images("h0", "h1"))
    whole, absent, null, default = (
        _recorded_unaware(_images(*states))
        for states in [("h0", "h1"), (_ABSENT, _ABSENT), (None, None), ("", "")]
    )
    for scheme in VALUE_DIGEST_SCHEMES:
        uniform = [whole, absent, null, default]
        if scheme == VALUE_DIGEST_SCHEME:
            uniform.insert(0, annotation_value_digest(ann, scheme=scheme))
        digests = list(_value_digests(ann, scheme, None))
        assert digests[: len(uniform)] == uniform
        mixed = digests[len(uniform) :]
        assert mixed and len(set(digests)) == len(digests)
        assert _recorded_unaware(_images("h0", None)) in mixed


def test_a_miss_computes_at_most_max_mixed_fills_more_digests(registered, monkeypatch):
    """``max_mixed_fills`` bounds the digests a miss computes, whatever the
    body's size: a thousand occurrences cost the uniform ones plus that many."""
    from lacing import digest

    computed = []
    real = digest._digest
    monkeypatch.setattr(
        digest, "_digest", lambda *a: computed.append(1) or real(*a), raising=True
    )

    def cost(ann, **kw):
        computed.clear()
        assert not value_digest_matches(ann, "0" * 64, **kw)
        return len(computed)

    ann = _ann(_images(*(f"h{i}" for i in range(1000))))
    uniform = 5  # v2, whole, absent, null, ""
    assert cost(ann, max_mixed_fills=0) == uniform
    assert cost(ann, max_mixed_fills=8) == uniform + 8
    assert cost(_ann(_images(*(f"h{i}" for i in range(20))))) == (
        uniform + MAX_MIXED_FILLS
    )


_NULL_PREFILL = {("images", None, "asset_id"): None}  # as artful's PanelImage


@pytest.mark.parametrize("n", [7, 9, 12])
@pytest.mark.parametrize(
    "unfilled",
    [(None,), (_ABSENT,), (None, None), (_ABSENT, _ABSENT), (_ABSENT, None)],
)
@pytest.mark.parametrize("resolver", ["registered", "null-prefill"])
def test_a_late_fill_on_many_images_matches_under_the_default_cap(
    registered, n, unfilled, resolver
):
    """lacing#157: a trace recorded just before the last image or two were
    filled (left null, absent, or one of each) matches once all are filled,
    however many images the panel holds; it was past the 3**n cap at 7."""
    resolve = {"registered": None, "null-prefill": lambda uri: _NULL_PREFILL}
    filled = [f"h{i}" for i in range(n)]
    recorded = _recorded_unaware(_images(*filled[: n - len(unfilled)], *unfilled))
    ann = _ann(_images(*filled))
    for scheme in VALUE_DIGEST_SCHEMES:
        assert value_digest_matches(
            ann, recorded, scheme=scheme, resolve_derived=resolve[resolver]
        )


def test_a_single_late_fill_is_among_the_first_mixed_bodies_tried(registered):
    """Fewest occurrences moved first, the pre-fill state (here null) first:
    image ``i`` still null at record time is the ``i + 1``-th mixed body tried,
    so it matches under that budget and reads as changed one below."""
    resolve = lambda uri: _NULL_PREFILL
    n = 30
    filled = [f"h{i}" for i in range(n)]
    ann = _ann(_images(*filled))
    for i in (0, n - 1):
        recorded = _recorded_unaware(_images(*filled[:i], None, *filled[i + 1 :]))
        for budget, matches in [(i + 1, True), (i, False)]:
            assert matches == value_digest_matches(
                ann, recorded, resolve_derived=resolve, max_mixed_fills=budget
            )
    # and far-off states still match when the budget reaches them
    recorded = _recorded_unaware(_images(*filled[:4], *[None] * 2, _ABSENT))
    assert value_digest_matches(
        _ann(_images(*filled[:7])), recorded, resolve_derived=resolve
    )
    six = ("h0", None, _ABSENT, "h3", None, _ABSENT)
    assert value_digest_matches(
        _ann(_images(*(f"h{i}" for i in range(6)))),
        _recorded_unaware(_images(*six)),
        resolve_derived=resolve,
    )


@pytest.mark.parametrize("late", [(None, None), (_ABSENT, None), (_ABSENT, _ABSENT)])
@pytest.mark.parametrize("resolver", ["registered", "null-prefill"])
def test_late_fills_among_many_null_images_match_under_the_default_budget(
    registered, late, resolver
):
    """lacing#157: 60 images, 4 filled now and the rest still null, traced
    before the last 2 fills: only the filled images are where a fill happened,
    so they are moved first and the trace is reached at once."""
    resolve = {"registered": None, "null-prefill": lambda uri: _NULL_PREFILL}
    n, k = 60, 4
    now = [f"h{i}" for i in range(k)] + [None] * (n - k)
    recorded = _recorded_unaware(_images(*now[: k - 2], *late, *now[k:]))
    ann = _ann(_images(*now))
    for scheme in VALUE_DIGEST_SCHEMES:
        assert value_digest_matches(
            ann, recorded, scheme=scheme, resolve_derived=resolve[resolver]
        )


def test_images_still_at_a_non_null_prefill_are_held_as_unfilled(registered):
    """The registered schema's pre-fill is "": images holding "" now are not
    where a fill happened, so the late fills among many such images are
    reached as fast as among null ones."""
    n, k = 60, 4
    now = [f"h{i}" for i in range(k)] + [""] * (n - k)
    ann = _ann(_images(*now))
    for late in [("", ""), (None, None), (_ABSENT, "")]:
        recorded = _recorded_unaware(_images(*now[: k - 2], *late, *now[k:]))
        assert value_digest_matches(ann, recorded)


def test_uniform_digests_are_not_repeated(registered):
    """When no occurrence of a path with a non-null pre-fill is present, the
    null body and the pre-fill body are one body: its digest comes once."""
    resolve = lambda uri: {("images", None, "asset_id"): "", ("maybe",): None}
    ann = _ann({"images": [{"artifact_id": "a0"}], "maybe": ""})
    for scheme in VALUE_DIGEST_SCHEMES:
        digests = list(_value_digests(ann, scheme, resolve))
        assert len(digests) == len(set(digests)) == 3 + (scheme != V1)


def test_a_prefill_that_is_not_json_is_tried_as_null(registered):
    """A custom resolver may return a pre-fill value that is not JSON (as
    fill_paths accepts): it cannot be in a recorded body, so null stands in."""
    resolve = lambda uri: {("images", None, "asset_id"): datetime(2026, 1, 1)}
    filled = _ann(_images("h0", "h1"))
    for recorded_states in [("h0", None), (None, None), (_ABSENT, "h1")]:
        recorded = _recorded_unaware(_images(*recorded_states))
        assert value_digest_matches(filled, recorded, resolve_derived=resolve)
        assert recorded in accepted_value_digests(filled, resolve_derived=resolve)


# -- a miss's cost is bounded in work, not just in count (lacing#161) -----------


def _digests_computed(monkeypatch):
    from lacing import digest

    computed = []
    real = digest._digest
    monkeypatch.setattr(
        digest, "_digest", lambda *a: computed.append(1) or real(*a), raising=True
    )
    return computed


def test_a_miss_on_a_big_body_digests_a_bounded_number_of_bytes(
    registered, monkeypatch
):
    from lacing.digest import MAX_MIXED_BYTES

    computed = _digests_computed(monkeypatch)
    ann = _ann(_images(*(f"h{i}" for i in range(1000))))
    size = len(json.dumps(ann.body, sort_keys=True, separators=(",", ":")))
    uniform = 5
    assert not value_digest_matches(ann, "0" * 64)
    mixed = len(computed) - uniform
    assert 1 <= mixed <= MAX_MIXED_BYTES // size < MAX_MIXED_FILLS
    computed.clear()
    assert not value_digest_matches(ann, "0" * 64, max_mixed_bytes=None)
    assert len(computed) == uniform + MAX_MIXED_FILLS  # no byte budget: the count


def test_the_byte_budget_always_leaves_one_candidate(registered, monkeypatch):
    computed = _digests_computed(monkeypatch)
    ann = _ann(_images(*(f"h{i}" for i in range(50))))
    assert not value_digest_matches(ann, "0" * 64, max_mixed_bytes=1)
    assert len(computed) == 5 + 1


def test_a_small_body_still_gets_the_whole_count(registered, monkeypatch):
    computed = _digests_computed(monkeypatch)
    assert not value_digest_matches(
        _ann(_images(*(f"h{i}" for i in range(20)))), "0" * 64
    )
    assert len(computed) == 5 + MAX_MIXED_FILLS


def test_the_enumerations_setup_dumps_each_value_once_not_per_comparison(
    registered, monkeypatch
):
    from lacing import derived

    dumps = []
    real = derived._json_key
    monkeypatch.setattr(
        derived, "_json_key", lambda v: dumps.append(1) or real(v), raising=True
    )
    n = 1000
    assert not value_digest_matches(
        _ann(_images(*(f"h{i}" for i in range(n)))), "0" * 64, max_mixed_fills=1
    )
    assert len(dumps) < 5 * n  # was ~45 per site


def test_the_memoized_comparison_agrees_with_same_json():
    from datetime import datetime

    from lacing.derived import same_json
    from lacing.digest import _memoized_same_json

    same = _memoized_same_json()
    when = datetime(2026, 1, 1)
    values = [0, False, 1, 1.0, None, "", [0], [False], {"a": 1}, {"a": 1.0}, when]
    for a in values:
        for b in values:
            assert same(a, b) == same_json(a, b), (a, b)
