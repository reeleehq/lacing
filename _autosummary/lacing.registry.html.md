# lacing.registry

The replacement rule shared by lacing’s registries (lacing#19).

lacing keys three registries by a published identity: I/O adapters by name
([`lacing.adapters.register_adapter()`](lacing.adapters.html.md#lacing.adapters.register_adapter)), body schemas by URI
([`lacing.schema.register_body_schema()`](lacing.schema.html.md#lacing.schema.register_body_schema), including a schema name’s declared
default version) and body migrations by `(schema_name, from_version)`
([`lacing.schema.register_migration()`](lacing.schema.html.md#lacing.schema.register_migration)). Each calls
[`warn_if_replacing()`](#lacing.registry.warn_if_replacing) before it writes, so all three follow one rule:

- registering the identical object again is a silent no-op;
- registering a *different* object under a key already taken emits a
  [`RegistryConflictWarning`](#lacing.registry.RegistryConflictWarning), then replaces;
- `force=True` replaces silently, for tests and hot-reload.

Silent replacement is how two modules registering the same key end up with
import order deciding the winner, and nothing saying so.

### Functions

| [`warn_if_replacing`](#lacing.registry.warn_if_replacing)(registry, key, new, \*, what)   | Warn when writing `new` under `key` would replace a different object.   |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|

### Exceptions

| [`RegistryConflictWarning`](#lacing.registry.RegistryConflictWarning)   | A registration replaced a *different* object already registered under its key.   |
|----------------------------------------------------------------------------|----------------------------------------------------------------------------------|

### *exception* lacing.registry.RegistryConflictWarning

Bases: [`FutureWarning`](https://docs.python.org/3/builtins/exceptions.html#FutureWarning)

A registration replaced a *different* object already registered under its key.

It will become an error; pass `force=True` to the register function to
replace on purpose.

### lacing.registry.warn_if_replacing(registry, key, new, , what, force=False)

Warn when writing `new` under `key` would replace a different object.

Call it just before the write. `what` names the registry in the message
(`"body schema"`). The warning points at whoever called the register
function, or, for a decorator, at the decorated definition.

Identical means `is` or `==`: a model class compares by identity, a
migration’s `(to_version, func)` and a frozen `AdapterSpec` compare
field by field, their functions by identity.

The issue (lacing#19) asks for an error. This warns instead, because
downstream test suites re-register different models under one URI today
(a new local class per test), and raising would turn their CI red on the
next lacing release. Warn first, raise later.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
