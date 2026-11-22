# lacing.store.locking

Named exclusive locks for stores: the mechanisms behind `store.lock(key)`.

`IntervalAnnotationStore.lock(key)` is an exclusive context manager scoped to
one store (for `PostgresStore`: one `(owner, project)`). Each backend picks
the narrowest mechanism that excludes every holder that can reach the same
data: a process-local lock for `MemoryStore`, a file lock beside the database
for `SqliteStore` (excludes other processes on the host too), a Postgres
advisory lock for `PostgresStore` (excludes other hosts).

Locks are *not* re-entrant: taking a lock you already hold blocks forever.

[`KeyedTurn`](#lacing.store.locking.KeyedTurn) is the same exclusion as a *turn* a caller takes and gives
back: a per-key turn across threads and processes, with a blocking acquire for
worker threads, a non-blocking one, and an `async` acquire an event loop polls
without holding a thread (lacing#194).

### Module Attributes

| [`KEY_DIGEST_BYTES`](#lacing.store.locking.KEY_DIGEST_BYTES)   | Bytes of the blake2b digest used to name a key (file name / advisory id).   |
|---------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`DFLT_TURN_POLL_S`](#lacing.store.locking.DFLT_TURN_POLL_S)   | Seconds between tries of another process's hold on a turn.                  |

### Functions

| [`advisory_lock_id`](#lacing.store.locking.advisory_lock_id)(\*parts)                 | A signed 64-bit integer for `parts`: the argument of `pg_advisory_lock`.                                                                                                                                    |
|--------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`file_lock`](#lacing.store.locking.file_lock)(path)                           | Exclusive lock on `path` (created if missing), held for the `with` block.                                                                                                                                   |
| [`key_digest`](#lacing.store.locking.key_digest)(\*parts)                       | Stable digest of `parts` (length-prefixed, so `("a", "bc") != ("ab", "c")`).                                                                                                                                |
| [`keyed_turn`](#lacing.store.locking.keyed_turn)(directory, key, \*[, name_of]) | The one [`KeyedTurn`](#lacing.store.locking.KeyedTurn) per `(directory, key)` in this process: every caller that takes a key's turn must share one, or their thread locks would not order them. |
| [`sidecar_lock_path`](#lacing.store.locking.sidecar_lock_path)(db_path, key)           | Lock file for `key` beside the database at `db_path`.                                                                                                                                                       |
| [`turn_file_name`](#lacing.store.locking.turn_file_name)(key)                       | The lock file a [`KeyedTurn`](#lacing.store.locking.KeyedTurn) of `key` holds: its digest, so a key may hold any character (an email, a path) and never names a file itself.                    |

### Classes

| [`KeyedTurn`](#lacing.store.locking.KeyedTurn)(directory, key, \*[, name_of, poll_s])   | One key's turn, ordered across this process's threads and every process that shares `directory`.   |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| [`NamedLocks`](#lacing.store.locking.NamedLocks)()                                       | Process-local named exclusive locks (a registry of `threading.Lock`).                              |

### lacing.store.locking.DFLT_TURN_POLL_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.05*

Seconds between tries of another process’s hold on a turn.

### lacing.store.locking.KEY_DIGEST_BYTES *= 8*

Bytes of the blake2b digest used to name a key (file name / advisory id).

### *class* lacing.store.locking.KeyedTurn(directory, key, \*, name_of=<function turn_file_name>, poll_s=0.05)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One key’s turn, ordered across this process’s threads and every process
that shares `directory`.

A thread lock orders this process’s callers; an exclusive `flock` on
`directory/<name_of(key)>` orders them against other processes. The kernel
releases an `flock` when its holder dies, so a crashed process never leaves a
turn held. Without `fcntl` (not POSIX) the turn is the thread lock alone.

**It fails closed**: when the lock file cannot be made (an unwritable
directory), taking the turn raises `OSError` rather than running unordered.

Three ways to take it: [`acquire()`](#lacing.store.locking.KeyedTurn.acquire) (blocking, with a `timeout`),
[`try_acquire()`](#lacing.store.locking.KeyedTurn.try_acquire) (never blocks) and [`acquire_async()`](#lacing.store.locking.KeyedTurn.acquire_async) (polls
[`try_acquire()`](#lacing.store.locking.KeyedTurn.try_acquire) from an event loop, so a cancelled waiter holds nothing).
Not re-entrant; [`release()`](#lacing.store.locking.KeyedTurn.release) gives it back. As a context manager it is the
blocking acquire.

```pycon
>>> import tempfile
>>> turn = KeyedTurn(tempfile.mkdtemp(), "alice@example.com")
>>> turn.try_acquire(), turn.try_acquire()
(True, False)
>>> turn.release(); turn.try_acquire()
True
>>> turn.release()
```

#### acquire(timeout=-1)

Take the turn within `timeout` seconds (negative: as long as it takes);
`False` when it is still held.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### *async* acquire_async(, poll_s=None, deadline_s=None)

Take the turn from an event loop: [`try_acquire()`](#lacing.store.locking.KeyedTurn.try_acquire) every `poll_s`
(default the turn’s), for at most `deadline_s` seconds (`None`: until
taken). Nothing is held across an `await`, so a cancelled waiter holds
nothing.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### *property* path *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The lock file this turn holds.

#### release()

Give the turn back, to this process’s next caller and to other processes.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### try_acquire()

Take the turn now, or `False` when it is held; never blocks.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

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

### lacing.store.locking.keyed_turn(directory, key, \*, name_of=<function turn_file_name>)

The one [`KeyedTurn`](#lacing.store.locking.KeyedTurn) per `(directory, key)` in this process: every
caller that takes a key’s turn must share one, or their thread locks would not
order them. Kept for the process’s life, so the map is bounded by the number
of distinct keys.

* **Return type:**
  [`KeyedTurn`](#lacing.store.locking.KeyedTurn)

### lacing.store.locking.sidecar_lock_path(db_path, key)

Lock file for `key` beside the database at `db_path`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### lacing.store.locking.turn_file_name(key)

The lock file a [`KeyedTurn`](#lacing.store.locking.KeyedTurn) of `key` holds: its digest, so a key may
hold any character (an email, a path) and never names a file itself.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
