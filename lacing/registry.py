"""The replacement rule shared by lacing's registries (lacing#19).

lacing keys three registries by a published identity: I/O adapters by name
(:func:`lacing.adapters.register_adapter`), body schemas by URI
(:func:`lacing.schema.register_body_schema`, including a schema name's declared
default version) and body migrations by ``(schema_name, from_version)``
(:func:`lacing.schema.register_migration`). Each calls
:func:`warn_if_replacing` before it writes, so all three follow one rule:

- registering the identical object again is a silent no-op;
- registering a *different* object under a key already taken raises
  :class:`RegistryConflictError` and leaves the registry as it was (lacing#121;
  it warned, then replaced, while downstream code still collided);
- ``force=True`` replaces silently, for tests and hot-reload.

Silent replacement is how two modules registering the same key end up with
import order deciding the winner, and nothing saying so.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import fields, is_dataclass
from typing import Any

__all__ = [
    "RegistryConflictError",
    "RegistryConflictWarning",
    "refuse_replacing",
    "warn_if_replacing",
]


class RegistryConflictError(ValueError):
    """A registration would replace a *different* object already registered under
    its key. Pass ``force=True`` to the register function to replace on purpose."""


class RegistryConflictWarning(FutureWarning):
    """No longer emitted: a conflicting registration raises
    :class:`RegistryConflictError` (lacing#121). Kept so a ``-W`` filter or a
    ``pytest.warns`` naming it still imports."""


def refuse_replacing(
    registry: Mapping[Hashable, Any],
    key: Hashable,
    new: Any,
    *,
    what: str,
    force: bool = False,
) -> None:
    """Raise :class:`RegistryConflictError` when writing ``new`` under ``key``
    would replace a different object.

    Call it just before the write. ``what`` names the registry in the message
    (``"body schema"``). Identical means ``is`` or ``==``: a model class compares
    by identity, a migration's ``(to_version, func)`` and a frozen
    ``AdapterSpec`` compare field by field, their functions by identity.
    """
    if force or key not in registry:
        return
    old = registry[key]
    if old is new or old == new:
        return
    raise RegistryConflictError(
        f"{what} {key!r} is already registered as a different object "
        f"({_difference(old, new)}). Pass force=True to replace it on purpose."
    )


#: The name the register functions used while a conflict only warned (lacing#19).
warn_if_replacing = refuse_replacing


def _difference(old: Any, new: Any) -> str:
    """What differs, short: the differing fields of two dataclasses of one type,
    else both objects."""
    if is_dataclass(old) and type(old) is type(new):
        names = [
            f.name for f in fields(old) if getattr(old, f.name) != getattr(new, f.name)
        ]
        return "differs in " + ", ".join(names)
    return f"was {old!r}, now {new!r}"
