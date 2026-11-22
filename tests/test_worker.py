"""Tests for lacing.worker — optional Arq integration (arq is faked)."""

import asyncio
import sys
import types

import pytest

from lacing import worker


def _fake_arq(monkeypatch):
    arq = types.ModuleType("arq")
    conns = types.ModuleType("arq.connections")

    class RedisSettings:
        pass

    conns.RedisSettings = RedisSettings
    arq.connections = conns
    monkeypatch.setitem(sys.modules, "arq", arq)
    monkeypatch.setitem(sys.modules, "arq.connections", conns)
    return RedisSettings


def test_require_arq_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "arq", None)  # makes `import arq` fail
    with pytest.raises(ImportError, match="lacing\\[arq\\]"):
        worker._require_arq()


def test_default_redis_settings(monkeypatch):
    RedisSettings = _fake_arq(monkeypatch)
    ws = worker.build_worker_settings(store_factory=object, oplog_factory=object)
    assert isinstance(ws.redis_settings, RedisSettings)
    assert len(ws.functions) == 1


def test_explicit_redis_settings(monkeypatch):
    _fake_arq(monkeypatch)
    rs = object()
    ws = worker.build_worker_settings(
        store_factory=object, oplog_factory=object, redis_settings=rs
    )
    assert ws.redis_settings is rs


def test_run_processor_runs_and_closes_resources(monkeypatch):
    _fake_arq(monkeypatch)
    closed = []

    class Res:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    seen = {}

    async def fake_run_async(name, *, store, oplog, **kw):
        seen.update(name=name, store=store, oplog=oplog, kw=kw)
        return "ok"

    import lacing.processors as processors

    monkeypatch.setattr(processors, "run_async", fake_run_async)
    ws = worker.build_worker_settings(
        store_factory=lambda: Res("store"), oplog_factory=lambda: Res("oplog")
    )
    out = asyncio.run(ws.functions[0]({}, "p", threshold=0.4))
    assert out == "ok"
    assert seen["name"] == "p" and seen["kw"] == {"threshold": 0.4}
    assert sorted(closed) == ["oplog", "store"]


def test_run_processor_closes_even_on_error_and_ignores_close_failure(monkeypatch):
    _fake_arq(monkeypatch)

    class Res:
        def close(self):
            raise RuntimeError("close failed")

    async def boom(name, **kw):
        raise ValueError("job failed")

    import lacing.processors as processors

    monkeypatch.setattr(processors, "run_async", boom)
    ws = worker.build_worker_settings(store_factory=Res, oplog_factory=object)
    with pytest.raises(ValueError, match="job failed"):
        asyncio.run(ws.functions[0]({}, "p"))
