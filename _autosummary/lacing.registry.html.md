# lacing.registry

The replacement rule shared by lacing’s registries (lacing#19).

lacing keys three registries by a published identity: I/O adapters by name
([`lacing.adapters.register_adapter()`](lacing.adapters.html.md#lacing.adapters.register_adapter)), body schemas by URI
([`lacing.schema.register_body_schema()`](lacing.schema.html.md#lacing.schema.register_body_schema), including a schema name’s declared
default version) and body migrations by `(schema_name, from_version)`
([`lacing.schema.register_migration()`](lacing.schema.html.md#lacing.schema.register_migration)). Each calls
[`warn_if_replacing()`](#lacing.registry.warn_if_replacing) before it writes, so all three follow one rule:

- registering the identical object again is a silent no-op;
- registering a *different* object under a key already taken raises
  [`RegistryConflictError`](#lacing.registry.RegistryConflictError) and leaves the registry as it was (lacing#121;
  > it warned, then replaced, while downstream code still collided);
- `force=True` replaces silently, for tests and hot-reload.

Silent replacement is how two modules registering the same key end up with
import order deciding the winner, and nothing saying so.

### Module Attributes

| [`warn_if_replacing`](#lacing.registry.warn_if_replacing)(registry, key, new, \*, what)   | The name the register functions used while a conflict only warned (lacing#19).   |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|

### Functions

| [`refuse_replacing`](#lacing.registry.refuse_replacing)(registry, key, new, \*, what)   | Raise [`RegistryConflictError`](#lacing.registry.RegistryConflictError) when writing `new` under `key` would replace a different object.   |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| [`warn_if_replacing`](#lacing.registry.warn_if_replacing)(registry, key, new, \*, what)  | The name the register functions used while a conflict only warned (lacing#19).                                                                  |

### Exceptions

| [`RegistryConflictError`](#lacing.registry.RegistryConflictError)   | A registration would replace a *different* object already registered under its key.                                                       |
|--------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| [`RegistryConflictWarning`](#lacing.registry.RegistryConflictWarning) | No longer emitted: a conflicting registration raises [`RegistryConflictError`](#lacing.registry.RegistryConflictError) (lacing#121). |

### *exception* lacing.registry.RegistryConflictError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A registration would replace a *different* object already registered under
its key. Pass `force=True` to the register function to replace on purpose.

### *exception* lacing.registry.RegistryConflictWarning

Bases: [`FutureWarning`](https://docs.python.org/3/builtins/exceptions.html#FutureWarning)

No longer emitted: a conflicting registration raises
[`RegistryConflictError`](#lacing.registry.RegistryConflictError) (lacing#121). Kept so a `-W` filter or a
`pytest.warns` naming it still imports.

### lacing.registry.refuse_replacing(registry, key, new, , what, force=False)

Raise [`RegistryConflictError`](#lacing.registry.RegistryConflictError) when writing `new` under `key`
would replace a different object.

Call it just before the write. `what` names the registry in the message
(`"body schema"`). Identical means `is` or `==`: a model class compares
by identity, a migration’s `(to_version, func)` and a frozen
`AdapterSpec` compare field by field, their functions by identity.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.registry.warn_if_replacing(registry, key, new, , what, force=False)

The name the register functions used while a conflict only warned (lacing#19).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
