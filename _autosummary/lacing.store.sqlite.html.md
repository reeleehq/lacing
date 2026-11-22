# lacing.store.sqlite

SQLite-backed annotation store and the `.annot` portable file format.

A `SqliteStore` is both:

1. A persistent backend implementing the `IntervalAnnotationStore`
   protocol over a single SQLite file.
2. The on-disk shape of the `.annot` portable handoff format
   (BACK-DOC §3.1: “SQLite-as-app-format” — Git-trackable,
   email-attachable, single-file).

Design notes:

- The integer pair `(start_value, start_rate)` and `(end_value, end_rate)`
  are the **source of truth** for time. Rational arithmetic stays exact.
- The R\*Tree index uses `REAL` (float seconds) because SQLite’s R\*Tree
  requires it. We treat R\*Tree results as a **pre-filter** and re-check
  boundary cases against the integer-pair columns. Any annotation whose
  rational seconds matches the query’s bounds exactly will still be
  filtered correctly because we widen the R\*Tree query by one ULP.
- Tier hierarchy is enforced via FK; stereotype validation is the
  application’s job (see `lacing.tier.validate_tier_constraint`).
- `schema_version` lives in the `meta` table; migrations register
  upgrade functions keyed on the from-version in
  [`lacing.store.migrations`](lacing.store.migrations.html.md#module-lacing.store.migrations) (the store-level counterpart of the
  > body ladder in [`lacing.schema`](lacing.schema.html.md#module-lacing.schema)). Opening a stale file refuses
  > unless asked to migrate (`SqliteStore(path, migrate=True)` or
  > `lacing migrate <path>`), and refuses *before* touching the file.

See `lacing-architecture` (Phase 1) and BACK-DOC §3.1 for the why.

### Module Attributes

| [`SCHEMA_VERSION`](#lacing.store.sqlite.SCHEMA_VERSION)   | Current `.annot` schema version.   |
|-------------------------------------------------------------------|------------------------------------|

### Functions

| [`from_memory`](#lacing.store.sqlite.from_memory)(memory_store, target)   | Persist an in-memory store to a new `.annot` file.   |
|--------------------------------------------------------------------------------------|------------------------------------------------------|
| [`to_memory`](#lacing.store.sqlite.to_memory)(sqlite_store)             | Load a `.annot` file fully into a `MemoryStore`.     |

### Classes

| [`SqliteStore`](#lacing.store.sqlite.SqliteStore)(path, \*[, check_same_thread, ...])   | SQLite-backed `IntervalAnnotationStore`.   |
|----------------------------------------------------------------------------------------------------|--------------------------------------------|

### Exceptions

| [`SchemaMismatchError`](#lacing.store.sqlite.SchemaMismatchError)   | Raised when opening a `.annot` file with an incompatible schema.   |
|------------------------------------------------------------------------|--------------------------------------------------------------------|

### lacing.store.sqlite.SCHEMA_VERSION *= 2*

Current `.annot` schema version. Increment + register a migration
([`lacing.store.migrations.register_store_migration()`](lacing.store.migrations.html.md#lacing.store.migrations.register_store_migration), with
`store_kind="sqlite"`) when making a breaking change to the table
layout.

v2 (lacing#14, defect D5): `prov_was_derived_from` may contain 64-hex
artifact `asset_id` strings alongside annotation UUIDs. The table layout
and every existing row are unchanged — the bump exists because \*\*pre-v2
builds eagerly `UUID()`-parse the column on read\*\* and crash on the
first asset id, so they must refuse v2 files instead of opening them and
failing row-by-row. The v1→v2 migration step is accordingly stamp-only
(see [`lacing.store.migrations`](lacing.store.migrations.html.md#module-lacing.store.migrations)).

Operational caveat: the version gate runs at **open**. A pre-v2 build’s
already-open connection survives the stamp and keeps reading — safe until
some v2 writer mints an asset-id ref, at which point it fails as a raw
`ValueError` mid-read rather than a refusal. Restart long-lived
pre-v2 services after migrating a file they serve.

### *exception* lacing.store.sqlite.SchemaMismatchError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when opening a `.annot` file with an incompatible schema.

### *class* lacing.store.sqlite.SqliteStore(path, , check_same_thread=True, migrate=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

SQLite-backed `IntervalAnnotationStore`.

* **Parameters:**
  * **path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path to the `.annot` file. Use `":memory:"` for an
    ephemeral in-memory database.
  * **check_same_thread** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Forwarded to `sqlite3.connect`. We hold a
    single connection guarded by a lock; pass `False` when
    sharing across threads.
  * **migrate** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Opt-in to upgrading a file written at an older
    `schema_version` on open, via the ladder in
    [`lacing.store.migrations`](lacing.store.migrations.html.md#module-lacing.store.migrations). Off by default — silently
    rewriting someone’s file on open is worse than refusing.
    Every open-time schema failure — refusal *or* failed migration
    — raises [`SchemaMismatchError`](#lacing.store.sqlite.SchemaMismatchError); a failed migration
    chains the ladder’s `StoreMigrationError` as its cause.

#### add(annotation)

Add an annotation to the store.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### add_tier(tier)

Register a tier.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### all()

Iterate over every annotation in the store.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### at_tier(tier_name, query)

Yield annotations of one tier that intersect the query interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### by_tier(tier_name)

Iterate over the annotations of one tier.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### close()

Release the underlying resources.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### contains(query)

Yield annotations that contain the query interval (Allen `contains`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### during(query)

Yield annotations lying strictly during the query interval (Allen `during`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### equals(query)

Yield annotations whose interval equals the query interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### extend(annotations)

Add several annotations at once.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### finishes(query)

Yield annotations that finish with the query interval but start later (Allen `finishes`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### get_meta(key)

Return the metadata value stored under `key`, or `None`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### get_tier(name)

Return the tier with the given name, or `None`.

* **Return type:**
  [`Tier`](lacing.tier.html.md#lacing.tier.Tier) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### intersects(query)

Yield annotations whose interval intersects the query interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### lock(key)

Exclusive lock named `key`: a file lock beside the database.

Excludes other threads and other processes on this host that open the
same `.annot` file; the kernel frees it if the holder dies. An
in-memory database (`":memory:"`) has no file, so it falls back to a
process-local lock.

* **Return type:**
  [`AbstractContextManager`](https://docs.python.org/3/library/contextlib.html#contextlib.AbstractContextManager)[[`None`](https://docs.python.org/3/builtins/constants.html#None)]

#### meets(query)

Yield annotations that end exactly where the query interval starts (Allen `meets`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### overlaps(query)

Yield annotations that overlap the start of the query interval (Allen `overlaps`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### *property* path *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [PathLike](https://docs.python.org/3/library/os.html#os.PathLike)*

Filesystem path of the backing database file.

#### relate(query, relations)

Yield annotations standing in the given Allen relation to the query interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### remove(annotation_id)

Remove the annotation with the given id; return it, or `None` if absent.

* **Return type:**
  [`Annotation`](lacing.model.html.md#lacing.model.Annotation) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* schema_version *: [int](https://docs.python.org/3/builtins/functions.html#int)*

The schema version recorded in the store.

#### set_meta(key, value)

Store a metadata value under `key`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### starts(query)

Yield annotations that start with the query interval but end earlier (Allen `starts`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### tiers()

Return the registered tiers.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Tier`](lacing.tier.html.md#lacing.tier.Tier)]

#### update(annotation)

Replace the row with this id (and its R\*Tree entry) in one transaction.

Readers take the same lock (`_fetchall()`), so on a connection
shared between threads — where a reader would otherwise see this
transaction’s uncommitted state — they get the old annotation or the
new one, never neither (lacing#66).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.store.sqlite.from_memory(memory_store, target)

Persist an in-memory store to a new `.annot` file.

* **Return type:**
  [`SqliteStore`](#lacing.store.sqlite.SqliteStore)

### lacing.store.sqlite.to_memory(sqlite_store)

Load a `.annot` file fully into a `MemoryStore`.
