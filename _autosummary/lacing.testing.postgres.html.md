# lacing.testing.postgres

The shared part of a per-test Postgres harness (lacing#166).

lacing’s store tests and downstream packages (nw, reelee) all need the same two
things around pytest-postgresql: a reason to skip when a local Postgres cannot
start here, and a libpq connection string for its `postgresql` fixture:

```default
from lacing.testing.postgres import conninfo, postgres_unavailable

if (why := postgres_unavailable()) is not None: ...  # skip
dsn = conninfo(postgresql)
```

Nothing here imports pytest, psycopg or pytest-postgresql at module import.

### Module Attributes

| [`POSTGRES_BINARIES`](#lacing.testing.postgres.POSTGRES_BINARIES)   | Executables all of which must be on `PATH` for a local Postgres to start: pytest-postgresql runs `pg_ctl`, so a bare `postgres` binary is not enough.   |
|----------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`conninfo`](#lacing.testing.postgres.conninfo)(postgresql)                          | A libpq connection string for pytest-postgresql's `postgresql` fixture.   |
|------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`postgres_unavailable`](#lacing.testing.postgres.postgres_unavailable)(\*[, modules, binaries]) | Why a per-test Postgres cannot run here, or `None` when it can.           |

### lacing.testing.postgres.POSTGRES_BINARIES *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('pg_ctl',)*

Executables all of which must be on `PATH` for a local Postgres to start:
pytest-postgresql runs `pg_ctl`, so a bare `postgres` binary is not enough.

### lacing.testing.postgres.conninfo(postgresql)

A libpq connection string for pytest-postgresql’s `postgresql` fixture.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### lacing.testing.postgres.postgres_unavailable(, modules=('pytest_postgresql', 'psycopg'), binaries=('pg_ctl',))

Why a per-test Postgres cannot run here, or `None` when it can.

```pycon
>>> postgres_unavailable(modules=("no_such_module_xyz",))
'needs no_such_module_xyz (pip install pytest-postgresql "psycopg[binary]")'
>>> postgres_unavailable(modules=(), binaries=())
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
