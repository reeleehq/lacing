"""Shared pytest fixtures.

The Postgres-backed store is tested via ``pytest-postgresql``, which spawns
a sandboxed PostgreSQL using the locally installed binary (no running
service required). If neither ``pytest-postgresql`` nor the Postgres
binary is available, those tests are skipped automatically.
"""

from __future__ import annotations

import shutil
import sqlite3

import pytest


def _have_postgres_binary() -> bool:
    return any(
        shutil.which(name) is not None for name in ("pg_ctl", "postgres")
    )


def _have_pytest_postgresql() -> bool:
    try:
        import pytest_postgresql  # noqa: F401
        return True
    except ImportError:
        return False


# Auto-load the pytest-postgresql plugin only when both prerequisites are met.
# Otherwise, register a marker so tests can skip cleanly.
if _have_pytest_postgresql() and _have_postgres_binary():
    pytest_plugins = ("pytest_postgresql",)


def pytest_collection_modifyitems(config, items):  # pragma: no cover
    if _have_pytest_postgresql() and _have_postgres_binary():
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
def isolated_body_registry(monkeypatch):
    """The body-schema registry and declared default versions, restored after
    the test, so what a test registers does not leak into later ones
    (lacing#122). Yields the test's working copy of the registry.

    The built-in bodies are imported first, so they are in the real registry:
    imported for the first time inside the test, they would register only in
    the copy, and a later ``import lacing.bodies.word`` (a no-op by then)
    would leave ``word/v1`` unregistered for every test after it."""
    import lacing.bodies  # noqa: F401  registers the built-in body schemas
    from lacing import schema

    registry = dict(schema._BODY_REGISTRY)
    monkeypatch.setattr(schema, "_BODY_REGISTRY", registry)
    monkeypatch.setattr(schema, "_DEFAULT_VERSIONS", dict(schema._DEFAULT_VERSIONS))
    return registry
