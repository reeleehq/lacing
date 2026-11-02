"""Registry identity (lacing#19): versioned adapters, no silent replacement,
and an explicit default version per body schema name.
"""

from __future__ import annotations

import warnings

import pytest
from pydantic import BaseModel

import lacing
import lacing.adapters as adapters
from lacing import schema as lacing_schema
from lacing.adapters import AdapterSpec, register_adapter
from lacing.schema import (
    default_version,
    migrate_to_default,
    migrate_to_latest,
    register_body_schema,
    register_migration,
)

URI = "annot://schema/identity-demo/v1"


@pytest.fixture(autouse=True)
def isolated_registries():
    """Snapshot and restore the adapter, body schema, default and migration registries."""
    import lacing.bodies  # noqa: F401  built-ins in the snapshot

    registries = (
        adapters._REGISTRY,
        lacing_schema._BODY_REGISTRY,
        lacing_schema._MIGRATION_REGISTRY,
        lacing_schema._DEFAULT_VERSIONS,
    )
    snapshots = [dict(r) for r in registries]
    try:
        yield
    finally:
        for registry, snapshot in zip(registries, snapshots):
            registry.clear()
            registry.update(snapshot)


@pytest.fixture
def no_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        yield


class _A(BaseModel):
    text: str


class _B(BaseModel):
    text: str


def _load(source, **kwargs):
    raise NotImplementedError


def _other_load(source, **kwargs):
    raise NotImplementedError


def _dump(store, target=None, **kwargs):
    return None


def _adapter(load=_load, **kwargs):
    return register_adapter(name="identity-demo", load=load, dump=_dump, **kwargs)


def _migration(func, **kwargs):
    register_migration(
        schema_name="identity-demo", from_version=1, to_version=2, **kwargs
    )(func)


def _step(body):
    return body


def _other_step(body):
    return {**body, "other": True}


# ---------------------------------------------------------------------------
# The replacement rule, for each of the three registries
# ---------------------------------------------------------------------------


class TestBodySchemaReplacement:
    def test_identical_is_silent(self, no_warnings):
        register_body_schema(URI, _A)
        register_body_schema(URI, _A)
        assert lacing_schema.get_body_schema(URI) is _A

    def test_different_warns_and_replaces(self):
        register_body_schema(URI, _A)
        with pytest.warns(lacing.RegistryConflictWarning, match="force=True") as rec:
            register_body_schema(URI, _B)
        assert lacing_schema.get_body_schema(URI) is _B
        message = str(rec[0].message)
        assert URI in message and "_A" in message and "_B" in message
        assert rec[0].filename == __file__  # points at the caller

    def test_force_is_silent(self, no_warnings):
        register_body_schema(URI, _A)
        register_body_schema(URI, _B, force=True)
        assert lacing_schema.get_body_schema(URI) is _B


class TestMigrationReplacement:
    def test_identical_is_silent(self, no_warnings):
        _migration(_step)
        _migration(_step)
        assert lacing_schema._MIGRATION_REGISTRY[("identity-demo", 1)] == (2, _step)

    def test_different_warns_and_replaces(self):
        _migration(_step)
        with pytest.warns(lacing.RegistryConflictWarning) as rec:

            @register_migration(
                schema_name="identity-demo", from_version=1, to_version=2
            )
            def _decorated(body):
                return body

        assert lacing_schema._MIGRATION_REGISTRY[("identity-demo", 1)] == (
            2,
            _decorated,
        )
        assert rec[0].filename == __file__  # points at the decorated definition

    def test_force_is_silent(self, no_warnings):
        _migration(_step)
        _migration(_other_step, force=True)
        assert lacing_schema._MIGRATION_REGISTRY[("identity-demo", 1)] == (
            2,
            _other_step,
        )


class TestAdapterReplacement:
    def test_identical_is_silent(self, no_warnings):
        first = _adapter()
        assert _adapter() == first

    def test_different_warns_and_replaces(self):
        _adapter()
        with pytest.warns(lacing.RegistryConflictWarning) as rec:
            spec = _adapter(load=_other_load)
        assert adapters.get_adapter("identity-demo") is spec
        assert rec[0].filename == __file__

    def test_new_version_is_a_different_spec(self):
        _adapter(version="1.0.0")
        with pytest.warns(lacing.RegistryConflictWarning):
            _adapter(version="1.1.0")

    def test_force_is_silent(self, no_warnings):
        _adapter()
        spec = _adapter(load=_other_load, force=True)
        assert adapters.get_adapter("identity-demo") is spec


# ---------------------------------------------------------------------------
# Explicit default version
# ---------------------------------------------------------------------------


def _three_versions_with_chain():
    for v in (1, 2, 3):
        register_body_schema(f"annot://schema/identity-demo/v{v}", _A)
    for v in (1, 2):
        register_migration(
            schema_name="identity-demo", from_version=v, to_version=v + 1
        )(lambda body, v=v: {**body, f"to_v{v + 1}": True})


class TestDefaultVersion:
    def test_falls_back_to_the_highest(self):
        _three_versions_with_chain()
        assert default_version("identity-demo") == 3
        assert default_version("never-registered") is None

    def test_declared_default_wins_and_publishing_v3_does_not_move_it(self):
        register_body_schema("annot://schema/identity-demo/v1", _A)
        register_body_schema("annot://schema/identity-demo/v2", _A, default=True)
        _three_versions_with_chain()  # publishes v3 after the default was declared
        assert lacing_schema.latest_version("identity-demo") == 3
        assert default_version("identity-demo") == 2
        for migrate_fn in (migrate_to_default, migrate_to_latest):
            body, target = migrate_fn({"text": "hi"}, from_uri=URI)
            assert target == "annot://schema/identity-demo/v2"
            assert body == {"text": "hi", "to_v2": True}

    def test_declaring_a_different_default_warns(self):
        _three_versions_with_chain()
        register_body_schema("annot://schema/identity-demo/v2", _A, default=True)
        with pytest.warns(lacing.RegistryConflictWarning, match="default version"):
            register_body_schema("annot://schema/identity-demo/v3", _A, default=True)
        assert default_version("identity-demo") == 3

    def test_redeclaring_the_same_default_is_silent(self, no_warnings):
        register_body_schema("annot://schema/identity-demo/v2", _A, default=True)
        register_body_schema("annot://schema/identity-demo/v2", _A, default=True)
        assert default_version("identity-demo") == 2

    def test_clear_registry_clears_declared_defaults(self):
        register_body_schema("annot://schema/identity-demo/v2", _A, default=True)
        lacing_schema.clear_registry()
        assert lacing_schema._DEFAULT_VERSIONS == {}


# ---------------------------------------------------------------------------
# Adapter version in provenance
# ---------------------------------------------------------------------------


class TestAdapterVersion:
    def test_generator_id_with_version(self):
        spec = _adapter(version="1.2.0")
        assert spec.generator_id == lacing.GeneratorId(
            "adapter", "identity-demo", "1.2.0"
        )
        assert str(spec.generator_id) == "adapter:identity-demo@1.2.0"

    def test_generator_id_without_version(self):
        spec = AdapterSpec(
            name="identity-demo", extensions=(), media_types=(), load=_load, dump=_dump
        )
        assert spec.version is None
        assert str(spec.generator_id) == "adapter:identity-demo"

    def test_built_in_adapter_is_versioned(self):
        from lacing.adapters import webvtt

        assert adapters.get_adapter("webvtt").version == webvtt.ADAPTER_VERSION
        assert webvtt.GENERATED_BY == "adapter:webvtt@1.0.0"

    def test_loaded_annotations_carry_the_versioned_id(self):
        from tests.test_adapter_webvtt import SAMPLE_VTT, adapter_module

        store = adapter_module.load(SAMPLE_VTT, rate=1000)
        generators = {a.provenance.was_generated_by for a in store.all()}
        assert generators == {"adapter:webvtt@1.0.0"}
