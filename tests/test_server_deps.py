"""Tests for lacing.server.deps — lazily-built default store/op-log singletons."""

import pytest

from lacing.server import deps


@pytest.fixture(autouse=True)
def _clean():
    deps.reset_default_store()
    deps.reset_default_oplog()
    yield
    deps.reset_default_store()
    deps.reset_default_oplog()


def test_get_store_is_cached_singleton():
    s = deps.get_store()
    assert deps.get_store() is s


def test_get_oplog_is_cached_singleton():
    o = deps.get_oplog()
    assert deps.get_oplog() is o


def test_factories_build_fresh_objects():
    assert deps.default_store_factory() is not deps.default_store_factory()
    assert deps.default_oplog_factory() is not deps.default_oplog_factory()


def test_reset_store_rebuilds_and_closes():
    s = deps.get_store()
    closed = []
    s.close = lambda: closed.append(1)  # instance attr shadows method
    deps.reset_default_store()
    assert closed == [1]
    assert deps.get_store() is not s


def test_reset_oplog_rebuilds():
    o = deps.get_oplog()
    deps.reset_default_oplog()
    assert deps.get_oplog() is not o


def test_reset_swallows_close_errors():
    class Boom:
        def close(self):
            raise RuntimeError("x")

    deps._active_store = Boom()
    deps._active_oplog = Boom()
    deps.reset_default_store()
    deps.reset_default_oplog()
    assert deps._active_store is None and deps._active_oplog is None


def test_reset_without_active_is_noop():
    deps.reset_default_store()
    deps.reset_default_oplog()
