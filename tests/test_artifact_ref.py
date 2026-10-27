"""Tests for lacing.artifact_ref and ArtifactStore.resolve (lacing#90)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from lacing import (
    ARTIFACT_REF_PREFIX,
    Artifact,
    ArtifactRef,
    ArtifactStore,
    ResolvedArtifact,
    content_hash_of,
    resolve_in_mall,
)
from lacing.artifact_ref import is_artifact_ref

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
    assert ref.format() == text
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
    [
        "take.srt",
        "artifact:",
        "artifact: Hello there.",
        "artifact:/k",
        "x artifact:k",
        f"artifact:a@{PIN}@{PIN}",  # the key would end in a pin
    ],
)
def test_parse_refuses_what_is_not_a_reference(text):
    assert not is_artifact_ref(text)
    with pytest.raises(ValueError, match="not an artifact reference"):
        ArtifactRef.parse(text)


def test_is_artifact_ref_is_exactly_parse_succeeding():
    text = f"{ARTIFACT_REF_PREFIX}a@{PIN}@{PIN}"
    assert not is_artifact_ref(text)
    with pytest.raises(ValueError, match="not an artifact reference") as raised:
        ArtifactRef.parse(text)
    assert isinstance(raised.value.__cause__, ValueError)  # the key's own error


@pytest.mark.parametrize(
    "kwargs",
    [
        {"key": ""},
        {"key": "a b"},
        {"key": "/k"},
        {"key": "k@" + PIN},  # would read back as a pinned reference
        {"key": "k", "store": "a/b"},
        {"key": "k", "store": ""},
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
        # the rest is not a key itself: the whole name stays with the default
        (
            "artifact:takes//a",
            {"transcripts": {}, "takes": {}},
            ("transcripts", "takes//a"),
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
    expected = ResolvedArtifact("k", art, art.asset_id, b"hello")
    assert store.resolve("artifact:k") == expected
    assert store.resolve(ArtifactRef("k")) == expected


def test_resolve_pinned_reads_the_pinned_bytes_after_the_key_is_resaved(store):
    first, second = _artifact(b"v1"), _artifact(b"v2")
    store.save("k", first, data=b"v1")
    pinned = ArtifactRef("k", pin=first.asset_id)
    assert store.resolve(pinned) == ("k", first, first.asset_id, b"v1")

    store.save("k", second, data=b"v2")
    # no record holds v1 now
    assert store.resolve(pinned) == (None, None, first.asset_id, b"v1")
    assert store.resolve("artifact:k").data == b"v2"


def test_resolve_pinned_names_the_other_key_that_holds_the_bytes(store):
    first, second = _artifact(b"v1"), _artifact(b"v2")
    store.save("k", first, data=b"v1")
    store.save("k", second, data=b"v2")
    store.save("elsewhere", first)
    resolved = store.resolve(ArtifactRef("k", pin=first.asset_id))
    assert (resolved.key, resolved.record, resolved.data) == ("elsewhere", first, b"v1")


def test_resolve_pinned_survives_a_deleted_key(store):
    art = _artifact(b"v1")
    store.save("k", art, data=b"v1")
    del store["k"]
    assert store.resolve(f"artifact:k@{art.asset_id}") == (
        None,
        None,
        art.asset_id,
        b"v1",
    )


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


def test_resolve_refuses_text_that_is_not_a_reference():
    with pytest.raises(ValueError, match="not an artifact reference"):
        ArtifactStore.in_memory().resolve("k")


# -- records of other shapes ----------------------------------------------------


class _ReeleeRecord(BaseModel):
    """reelee's shape: the content hash is ``content_hash``; there is no asset_id."""

    content_hash: str | None = None
    mime: str = "text/plain"


def test_content_hash_of_reads_asset_id_then_content_hash():
    art = _artifact(b"x")
    assert content_hash_of(art) == art.asset_id
    assert content_hash_of(_ReeleeRecord(content_hash=PIN)) == PIN
    assert content_hash_of(_ReeleeRecord()) is None


def test_resolve_a_reelee_record_pinned_and_unpinned():
    store = ArtifactStore.in_memory()
    content_hash = store.put_blob(b"reel")
    record = _ReeleeRecord(content_hash=content_hash)
    store["clip.mp4"] = record
    assert store.resolve("artifact:clip.mp4") == (
        "clip.mp4",
        record,
        content_hash,
        b"reel",
    )
    pinned = store.resolve(f"artifact:clip.mp4@{content_hash}")
    assert pinned == ("clip.mp4", record, content_hash, b"reel")
    assert store.count_refs(content_hash) == 1


def test_resolve_a_record_with_no_content_yet_raises_key_error():
    store = ArtifactStore.in_memory()
    store["stage1"] = _ReeleeRecord()  # filed before its bytes exist
    with pytest.raises(KeyError, match="has no content yet"):
        store.resolve("artifact:stage1")


def test_resolve_on_a_store_without_blobs_raises_key_error():
    store = ArtifactStore(catalog={})
    art = _artifact(b"x")
    store["k"] = art
    with pytest.raises(KeyError, match="no bytes"):
        store.resolve("artifact:k")
    with pytest.raises(KeyError, match="no bytes"):
        store.resolve(f"artifact:k@{art.asset_id}")


def test_the_holder_scan_skips_a_damaged_record(tmp_path):
    store = ArtifactStore.from_directory(tmp_path)
    (tmp_path / "catalog" / "a-damaged.json").write_text("not json")
    first, second = _artifact(b"v1"), _artifact(b"v2")
    store.save("k", first, data=b"v1")
    store.save("k", second, data=b"v2")
    store.save("z-holder", first)
    resolved = store.resolve(ArtifactRef("k", pin=first.asset_id))
    assert (resolved.key, resolved.data) == ("z-holder", b"v1")


# -- read=False -----------------------------------------------------------------


def test_resolve_without_reading_checks_the_bytes_exist(store):
    art = _artifact(b"big video")
    store.save("k", art, data=b"big video")
    assert store.resolve("artifact:k", read=False) == ("k", art, art.asset_id, None)
    pinned = store.resolve(f"artifact:k@{art.asset_id}", read=False)
    assert pinned == ("k", art, art.asset_id, None)
    assert b"".join(store.iter_blob(pinned.content_hash)) == b"big video"
    with pytest.raises(KeyError):
        store.resolve(f"artifact:k@{PIN}", read=False)


def test_resolve_without_reading_does_not_check_the_pin():
    store = ArtifactStore.in_memory()
    store.blobs[PIN] = b"tampered"
    assert store.resolve(f"artifact:k@{PIN}", read=False).data is None


# -- the happy path does not list the catalog -------------------------------------


class _UnlistableCatalog(dict):
    def __iter__(self):
        raise AssertionError("the catalog was listed")


def test_a_pinned_resolve_of_a_key_that_holds_the_pin_does_not_list_the_catalog():
    store = ArtifactStore(catalog=_UnlistableCatalog(), blobs={})
    first, second = _artifact(b"v1"), _artifact(b"v2")
    store.save("k", first, data=b"v1")
    assert store.resolve(f"artifact:k@{first.asset_id}").data == b"v1"
    assert store.resolve("artifact:k").data == b"v1"
    store.save("k", second, data=b"v2")
    with pytest.raises(AssertionError, match="listed"):  # only the fallback scans
        store.resolve(f"artifact:k@{first.asset_id}")


# -- resolve_in_mall ----------------------------------------------------------------


@pytest.fixture
def mall():
    transcripts, takes = ArtifactStore.in_memory(), ArtifactStore.in_memory()
    transcripts.save("k", _artifact(b"transcript"), data=b"transcript")
    takes.save("a", _artifact(b"take"), data=b"take")
    return {"transcripts": transcripts, "takes": takes}


def test_resolve_in_mall_picks_the_store(mall):
    def data(ref):
        return resolve_in_mall(ref, mall, default_store="transcripts").data

    assert data("artifact:takes/a") == b"take"
    assert data("artifact:k") == b"transcript"
    assert data(ArtifactRef("a", store="takes")) == b"take"
    pin = mall["takes"]["a"].asset_id
    resolved = resolve_in_mall(
        f"artifact:takes/a@{pin}", mall, default_store="transcripts", read=False
    )
    assert (resolved.key, resolved.data) == ("a", None)


def test_resolve_in_mall_refuses_a_store_not_in_the_mall(mall):
    with pytest.raises(LookupError, match="'transcripts', 'takes'") as caught:
        resolve_in_mall(ArtifactRef("a", store="nope"), mall, default_store="takes")
    assert not isinstance(caught.value, KeyError)  # "no such store", not "no such key"
    with pytest.raises(LookupError, match="'missing'"):
        resolve_in_mall("artifact:k", mall, default_store="missing")


def test_resolve_in_mall_refuses_a_store_that_cannot_resolve(mall):
    mall["plain"] = {"k": 1}
    with pytest.raises(TypeError, match="no resolve method"):
        resolve_in_mall("artifact:plain/k", mall, default_store="transcripts")


# -- second review (lacing#90) ------------------------------------------------


def test_an_unprefixed_manifest_reference_parses_on_request():
    """an records ``<store>/<key>@<sha256>`` with no prefix in a take's manifest."""
    text = f"transcripts/k@{PIN}"
    with pytest.raises(ValueError, match="not an artifact reference"):
        ArtifactRef.parse(text)
    ref = ArtifactRef.parse(text, require_prefix=False)
    assert (ref.key, ref.pin) == ("transcripts/k", PIN)
    assert ArtifactRef.parse("artifact:k", require_prefix=False).key == "k"
    with pytest.raises(ValueError):
        ArtifactRef.parse("/k", require_prefix=False)


def test_an_uppercase_pin_is_a_pin_kept_lowercase():
    ref = ArtifactRef.parse("artifact:k@" + PIN.upper())
    assert (ref.key, ref.pin) == ("k", PIN)
    assert ArtifactRef("k", pin=PIN.upper()).pin == PIN
    with pytest.raises(ValueError):
        ArtifactRef("k@" + PIN.upper())  # would read back as a pin


def test_non_text_is_not_a_reference():
    assert not is_artifact_ref(None)
    assert not is_artifact_ref(123)
    with pytest.raises(TypeError):
        ArtifactRef.parse(123)


class _CountingStore(dict):
    """A mall store whose truthiness would list its catalog."""

    def __bool__(self):
        raise AssertionError("bool() lists the catalog")

    def __len__(self):
        raise AssertionError("len() lists the catalog")


def test_locate_does_not_list_the_default_store():
    mall = {"transcripts": _CountingStore(), "takes": _CountingStore()}
    ref = ArtifactRef.parse(f"artifact:takes/gone@{PIN}")
    assert ref.locate(mall, default_store="transcripts").store == "takes"
