"""The replacement rule shared by lacing's registries (lacing#19).

lacing keys three registries by a published identity: I/O adapters by name
(:func:`lacing.adapters.register_adapter`), body schemas by URI
(:func:`lacing.schema.register_body_schema`, including a schema name's declared
default version) and body migrations by ``(schema_name, from_version)``
(:func:`lacing.schema.register_migration`). Each calls
:func:`warn_if_replacing` before it writes, so all three follow one rule:

- registering the identical object again is a silent no-op;
- registering a *different* object under a key already taken emits a
  :class:`RegistryConflictWarning`, then replaces;
- ``force=True`` replaces silently, for tests and hot-reload.

Silent replacement is how two modules registering the same key end up with
import order deciding the winner, and nothing saying so.
"""

from __future__ import annotations

import warnings
from collections.abc import Hashable, Mapping
from typing import Any

__all__ = ["RegistryConflictWarning", "warn_if_replacing"]


class RegistryConflictWarning(FutureWarning):
    """A registration replaced a *different* object already registered under its key.

    It will become an error; pass ``force=True`` to the register function to
    replace on purpose.
    """


def warn_if_replacing(
    registry: Mapping[Hashable, Any],
    key: Hashable,
    new: Any,
    *,
    what: str,
    force: bool = False,
    stacklevel: int = 2,
) -> None:
    """Warn when writing ``new`` under ``key`` would replace a different object.

    Call it just before the write. ``what`` names the registry in the message
    (``"body schema"``). ``stacklevel`` is counted from *this function's caller*,
    as in :func:`warnings.warn`: the default ``2`` points the warning at whoever
    called the register function, or, for a decorator, at the decorated
    definition.

    Identical means ``is`` or ``==``: a model class compares by identity, a
    migration's ``(to_version, func)`` and a frozen ``AdapterSpec`` compare
    field by field, their functions by identity.

    The issue (lacing#19) asks for an error. This warns instead, because
    downstream test suites re-register different models under one URI today
    (a new local class per test), and raising would turn their CI red on the
    next lacing release. Warn first, raise later.
    """
    if force or key not in registry:
        return
    old = registry[key]
    if old is new or old == new:
        return
    warnings.warn(
        f"{what} {key!r} is already registered as {old!r}; replacing it with "
        f"{new!r}. Replacing a registered {what} with a different object will "
        "become an error: pass force=True to replace on purpose.",
        RegistryConflictWarning,
        stacklevel=stacklevel + 1,
    )
