"""Shared pytest fixtures.

The Postgres-backed store is tested via ``pytest-postgresql``, which spawns
a sandboxed PostgreSQL using the locally installed binary (no running
service required). If neither ``pytest-postgresql`` nor the Postgres
binary is available, those tests are skipped automatically.
"""

from __future__ import annotations

import sqlite3

import pytest

from lacing.testing.postgres import postgres_unavailable


def _postgres_ok() -> bool:
    """pytest-postgresql and a ``pg_ctl`` are there (psycopg is lacing's own dependency
    for the Postgres store, so it is not asked here)."""
    return postgres_unavailable(modules=("pytest_postgresql",)) is None


# Auto-load the pytest-postgresql plugin only when both prerequisites are met.
# Otherwise, register a marker so tests can skip cleanly.
if _postgres_ok():
    pytest_plugins = ("pytest_postgresql",)


def pytest_collection_modifyitems(config, items):  # pragma: no cover
    if _postgres_ok():
        return
    # Skip any test that requests the postgres fixture.
    skip_pg = pytest.mark.skip(
        reason="postgres binary or pytest-postgresql not available",
    )
    for item in items:
        if "postgres_store" in getattr(item, "fixturenames", ()):
            item.add_marker(skip_pg)


@pytest.fixture
def opened_sqlite_connections(monkeypatch) -> list[sqlite3.Connection]:
    """Every connection ``sqlite3.connect`` opens during the test, in order.

    For asserting a failed constructor closed its handle (lacing#91).
    """
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def recording_connect(*args, **kwargs):
        opened.append(real_connect(*args, **kwargs))
        return opened[-1]

    monkeypatch.setattr(sqlite3, "connect", recording_connect)
    return opened


@pytest.fixture
def isolated_body_registry():
    """The body-schema, migration and default-version registries, restored in
    place after the test, so what a test registers does not leak into later
    ones (lacing#122). Yields the body-schema registry.

    The built-in bodies are imported first, so they are in the snapshot:
    imported for the first time inside the test, they would be cleared on
    restore, and a later ``import lacing.bodies.word`` (a no-op by then) would
    leave ``word/v1`` unregistered for every test after it. Restoring in place
    also covers a reference to a registry taken before the test. Not isolated:
    ``on_register`` listeners (none subscribe in lacing today).
    """
    import lacing.bodies  # noqa: F401  registers the built-in body schemas
    from lacing import schema

    registries = (
        schema._BODY_REGISTRY,
        schema._MIGRATION_REGISTRY,
        schema._DEFAULT_VERSIONS,
    )
    snapshots = [dict(r) for r in registries]
    try:
        yield schema._BODY_REGISTRY
    finally:
        for registry, snapshot in zip(registries, snapshots):
            registry.clear()
            registry.update(snapshot)
