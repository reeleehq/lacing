"""Tests for lacing.artifact_ref and ArtifactStore.resolve (lacing#90)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from lacing import (
    Artifact,
    ArtifactRef,
    ArtifactStore,
    ResolvedArtifact,
    hash_bytes,
    is_artifact_ref,
)

PIN = "ab" * 32


def _artifact(data: bytes) -> Artifact:
    return Artifact.from_bytes(
        data, kind="text", was_generated_by="agent:test", was_attributed_to="user:test"
    )


# -- the spelling -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "artifact:k",
        "artifact:collide.json",  # reelee's artifact:<id>
        "artifact:takes/a",
        "artifact:transcripts/takes/a@" + PIN,
        "artifact:k@not-a-pin",  # an `@` that is not a pin is part of the key
    ],
)
def test_parse_and_format_round_trip(text):
    ref = ArtifactRef.parse(text)
    assert ref.format() == str(ref) == text
    assert ArtifactRef.parse(ref.format()) == ref


def test_parse_splits_the_pin_and_keeps_the_whole_name_as_key():
    ref = ArtifactRef.parse("  artifact:transcripts/k@" + PIN + "\n")
    assert (ref.store, ref.key, ref.pin) == (None, "transcripts/k", PIN)


def test_a_located_reference_formats_with_its_store():
    ref = ArtifactRef("a", store="takes", pin=PIN)
    assert ref.format() == f"artifact:takes/a@{PIN}"
    located = ArtifactRef.parse(ref.format()).locate(
        {"takes": {"a": 1}}, default_store="transcripts"
    )
    assert located == ref


@pytest.mark.parametrize(
    "text",
    ["take.srt", "artifact:", "artifact: Hello there.", "artifact:/k", "x artifact:k"],
)
def test_parse_refuses_what_is_not_a_reference(text):
    assert not is_artifact_ref(text)
    with pytest.raises(ValueError, match="not an artifact reference"):
        ArtifactRef.parse(text)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"key": ""},
        {"key": "a b"},
        {"key": "/k"},
        {"key": "k@" + PIN},  # would read back as a pinned reference
        {"key": "k", "store": "a/b"},
        {"key": "k", "store": ""},
        {"key": "k", "pin": "AB" * 32},
        {"key": "k", "pin": "ab"},
    ],
)
def test_a_reference_that_would_not_read_back_as_itself_is_refused(kwargs):
    with pytest.raises(ValueError):
        ArtifactRef(**kwargs)


# -- locating the store in a mall (an's rule) ---------------------------------


class _Unanswerable:
    def __contains__(self, key):
        raise RuntimeError("cannot say")


@pytest.mark.parametrize(
    "text, mall, expected",
    [
        # the first segment's store holds the rest
        ("artifact:takes/a", {"transcripts": {}, "takes": {"a": 1}}, ("takes", "a")),
        # the default store holds the whole name: it wins
        (
            "artifact:takes/a",
            {"transcripts": {"takes/a": 1}, "takes": {}},
            ("transcripts", "takes/a"),
        ),
        # neither holds it (a pinned key since deleted): the named store
        ("artifact:takes/a@" + PIN, {"transcripts": {}, "takes": {}}, ("takes", "a")),
        # no such store in the mall
        ("artifact:other/a", {"transcripts": {}}, ("transcripts", "other/a")),
        ("artifact:k", {"transcripts": {}}, ("transcripts", "k")),
        (
            "artifact:takes/",
            {"transcripts": {}, "takes": {}},
            ("transcripts", "takes/"),
        ),
        # a store that cannot answer does not hold the key
        (
            "artifact:takes/a",
            {"transcripts": {}, "takes": _Unanswerable()},
            ("takes", "a"),
        ),
    ],
)
def test_locate(text, mall, expected):
    ref = ArtifactRef.parse(text).locate(mall, default_store="transcripts")
    assert (ref.store, ref.key) == expected
    assert ref.pin == ArtifactRef.parse(text).pin


def test_locate_keeps_a_store_already_named():
    ref = ArtifactRef("a", store="takes")
    assert ref.locate({}, default_store="transcripts") is ref


# -- ArtifactStore.resolve ----------------------------------------------------


@pytest.fixture(params=["memory", "directory"])
def store(request, tmp_path):
    if request.param == "memory":
        return ArtifactStore.in_memory()
    return ArtifactStore.from_directory(tmp_path)


def test_resolve_unpinned_reads_the_record_and_its_bytes(store):
    art = _artifact(b"hello")
    store.save("k", art, data=b"hello")
    assert store.resolve("artifact:k") == ResolvedArtifact(art, b"hello")
    assert store.resolve(ArtifactRef("k")) == (art, b"hello")


def test_resolve_pinned_reads_the_pinned_bytes_after_the_key_is_resaved(store):
    first, second = _artifact(b"v1"), _artifact(b"v2")
    store.save("k", first, data=b"v1")
    pinned = ArtifactRef("k", pin=first.asset_id)
    assert store.resolve(pinned) == (first, b"v1")

    store.save("k", second, data=b"v2")
    assert store.resolve(pinned) == (None, b"v1")  # no record holds v1 now
    assert store.resolve("artifact:k").data == b"v2"

    store.save("elsewhere", first)
    assert store.resolve(pinned) == (first, b"v1")  # a record that still does


def test_resolve_pinned_survives_a_deleted_key(store):
    art = _artifact(b"v1")
    store.save("k", art, data=b"v1")
    del store["k"]
    assert store.resolve(f"artifact:k@{art.asset_id}") == (None, b"v1")


def test_resolve_ignores_the_store_segment(store):
    art = _artifact(b"x")
    store.save("k", art, data=b"x")
    assert store.resolve(ArtifactRef("k", store="anything")).data == b"x"


def test_resolve_missing_key_or_content_raises_key_error(store):
    with pytest.raises(KeyError):
        store.resolve("artifact:nope")
    with pytest.raises(KeyError):
        store.resolve(f"artifact:nope@{PIN}")
    store.save("catalog-only", _artifact(b"never stored"))
    with pytest.raises(KeyError):
        store.resolve("artifact:catalog-only")


def test_resolve_refuses_bytes_that_do_not_hash_to_the_pin():
    store = ArtifactStore.in_memory()
    store.blobs[PIN] = b"tampered"
    with pytest.raises(ValueError, match="do not hash to the pin"):
        store.resolve(f"artifact:k@{PIN}")
    assert hash_bytes(b"tampered") != PIN


def test_resolve_refuses_a_record_without_an_asset_id():
    class Note(BaseModel):
        text: str = ""

    store = ArtifactStore.in_memory()
    store["k"] = Note()
    with pytest.raises(ValueError, match="no asset_id"):
        store.resolve("artifact:k")


def test_resolve_refuses_text_that_is_not_a_reference():
    with pytest.raises(ValueError, match="not an artifact reference"):
        ArtifactStore.in_memory().resolve("k")
