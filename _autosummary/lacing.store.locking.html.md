# lacing.store.locking

Named exclusive locks for stores: the mechanisms behind `store.lock(key)`.

`IntervalAnnotationStore.lock(key)` is an exclusive context manager scoped to
one store (for `PostgresStore`: one `(owner, project)`). Each backend picks
the narrowest mechanism that excludes every holder that can reach the same
data: a process-local lock for `MemoryStore`, a file lock beside the database
for `SqliteStore` (excludes other processes on the host too), a Postgres
advisory lock for `PostgresStore` (excludes other hosts).

Locks are *not* re-entrant: taking a lock you already hold blocks forever.

### Module Attributes

| [`KEY_DIGEST_BYTES`](#lacing.store.locking.KEY_DIGEST_BYTES)   | Bytes of the blake2b digest used to name a key (file name / advisory id).   |
|---------------------------------------------------------------------|-----------------------------------------------------------------------------|

### Functions

| [`advisory_lock_id`](#lacing.store.locking.advisory_lock_id)(\*parts)       | A signed 64-bit integer for `parts`: the argument of `pg_advisory_lock`.     |
|----------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`file_lock`](#lacing.store.locking.file_lock)(path)                 | Exclusive lock on `path` (created if missing), held for the `with` block.    |
| [`key_digest`](#lacing.store.locking.key_digest)(\*parts)             | Stable digest of `parts` (length-prefixed, so `("a", "bc") != ("ab", "c")`). |
| [`sidecar_lock_path`](#lacing.store.locking.sidecar_lock_path)(db_path, key) | Lock file for `key` beside the database at `db_path`.                        |

### Classes

| [`NamedLocks`](#lacing.store.locking.NamedLocks)()   | Process-local named exclusive locks (a registry of `threading.Lock`).   |
|-----------------------------------------------------------------|-------------------------------------------------------------------------|

### lacing.store.locking.KEY_DIGEST_BYTES *= 8*

Bytes of the blake2b digest used to name a key (file name / advisory id).

### *class* lacing.store.locking.NamedLocks

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Process-local named exclusive locks (a registry of `threading.Lock`).

### lacing.store.locking.advisory_lock_id(\*parts)

A signed 64-bit integer for `parts`: the argument of `pg_advisory_lock`.

```pycon
>>> advisory_lock_id("o", "p", "k") == advisory_lock_id("o", "p", "k")
True
>>> advisory_lock_id("o", "p", "k") != advisory_lock_id("o", "p", "other")
True
>>> -2**63 <= advisory_lock_id("o", "p", "k") < 2**63
True
```

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### lacing.store.locking.file_lock(path)

Exclusive lock on `path` (created if missing), held for the `with` block.

A fresh file descriptor per call, so threads of one process exclude each
other as well as other processes. The kernel drops the lock if the holder
dies. The lock file is left in place (removing it would race a waiter).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`None`](https://docs.python.org/3/builtins/constants.html#None)]

### lacing.store.locking.key_digest(\*parts)

Stable digest of `parts` (length-prefixed, so `("a", "bc") != ("ab", "c")`).

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### lacing.store.locking.sidecar_lock_path(db_path, key)

Lock file for `key` beside the database at `db_path`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
