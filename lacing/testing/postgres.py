"""The shared part of a per-test Postgres harness (lacing#166).

lacing's store tests and downstream packages (nw, reelee) all need the same two
things around pytest-postgresql: a reason to skip when a local Postgres cannot
start here, and a libpq connection string for its ``postgresql`` fixture::

    from lacing.testing.postgres import conninfo, postgres_unavailable

    if (why := postgres_unavailable()) is not None: ...  # skip
    dsn = conninfo(postgresql)

Nothing here imports pytest, psycopg or pytest-postgresql at module import.
"""

from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Sequence

__all__ = ["POSTGRES_BINARIES", "conninfo", "postgres_unavailable"]

POSTGRES_BINARIES: tuple[str, ...] = ("pg_ctl",)
"""Executables all of which must be on ``PATH`` for a local Postgres to start:
pytest-postgresql runs ``pg_ctl``, so a bare ``postgres`` binary is not enough."""

_REQUIRED_MODULES: tuple[str, ...] = ("pytest_postgresql", "psycopg")


def postgres_unavailable(
    *,
    modules: Sequence[str] = _REQUIRED_MODULES,
    binaries: Sequence[str] = POSTGRES_BINARIES,
) -> str | None:
    """Why a per-test Postgres cannot run here, or ``None`` when it can.

    >>> postgres_unavailable(modules=("no_such_module_xyz",))
    'needs no_such_module_xyz (pip install pytest-postgresql "psycopg[binary]")'
    >>> postgres_unavailable(modules=(), binaries=())
    """
    for module in modules:
        if importlib.util.find_spec(module) is None:
            return (
                f"needs {module} "
                '(pip install pytest-postgresql "psycopg[binary]")'
            )
    missing = [name for name in binaries if shutil.which(name) is None]
    if missing:
        return f"needs a Postgres binary ({', '.join(missing)}) on PATH"
    return None


def conninfo(postgresql) -> str:
    """A libpq connection string for pytest-postgresql's ``postgresql`` fixture."""
    from psycopg.conninfo import make_conninfo

    info = postgresql.info
    return make_conninfo(
        host=info.host,
        port=info.port,
        user=info.user,
        password=info.password or "",
        dbname=info.dbname,
    )
