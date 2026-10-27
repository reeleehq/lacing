"""One spelling for a reference to an artifact: ``artifact:[<store>/]<key>[@<sha256>]``.

Consumers of :class:`lacing.ArtifactStore` hand references to artifacts across
process and tool boundaries (an records them in a take's provenance; reelee's
MCP tools return them). :class:`ArtifactRef` is the one parser and formatter for
that text, so the spelling cannot drift between them (lacing#90):

- ``<key>`` is the id the artifact is filed under in its store's catalog.
- ``<store>/``, optional, names the store within a *mall* (a mapping of store
  names to stores). The text alone cannot tell ``takes/a`` (key ``a`` of store
  ``takes``) from a key ``takes/a``, so :meth:`ArtifactRef.parse` keeps the
  whole name as the key and :meth:`ArtifactRef.locate` splits it against a mall.
- ``@<sha256>``, optional, pins the content: a pinned reference names those
  bytes, even after the key is re-saved with other content.

:meth:`lacing.ArtifactStore.resolve` reads what a reference names in one store;
:func:`lacing.resolve_in_mall` locates its store in a mall first.

The syntax has one ambiguity no parser can remove: an unlocated
``artifact:takes/a`` names key ``a`` of store ``takes`` today, but key
``takes/a`` of the default store once that store gains such a key.

Differences from an's ``parse_artifact_ref`` (for its adoption):

- ``artifact:takes/`` (an empty rest) and ``artifact:takes//a`` (a rest that is
  not a key) go to the default store with the whole name as key.
- Text without the ``artifact:`` prefix raises ``ValueError``; an sliced the
  prefix's length off whatever it was given.
- ``artifact: x`` (a space after the prefix) is refused; reelee's lenient strip
  of such text stays in reelee.

>>> ref = ArtifactRef.parse("artifact:takes/a@" + "0" * 64)
>>> ref.key, ref.store, ref.pin == "0" * 64
('takes/a', None, True)
>>> ref.format() == "artifact:takes/a@" + "0" * 64
True
>>> ArtifactRef("a", store="takes").format()
'artifact:takes/a'
>>> mall = {"transcripts": {"takes/a": 1}, "takes": {}}
>>> ArtifactRef.parse("artifact:takes/a").locate(mall, default_store="transcripts")
ArtifactRef(key='takes/a', store='transcripts', pin=None)
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

__all__ = ["ARTIFACT_REF_PREFIX", "ArtifactRef", "is_artifact_ref"]

ARTIFACT_REF_PREFIX = "artifact:"

# The prefix and a name with no whitespace, so a transcript line such as
# ``artifact: some words`` is not taken for a reference.
_REF = re.compile(re.escape(ARTIFACT_REF_PREFIX) + r"(?P<name>[^\s/]\S*)")
_NAME = re.compile(r"[^\s/]\S*")
# Hex digits in either case; a pin is kept lowercase, as ``hash_bytes`` spells it.
_PINNED = re.compile(r"(?P<key>.+)@(?P<pin>[0-9a-fA-F]{64})")
_PIN = re.compile(r"[0-9a-fA-F]{64}")


def is_artifact_ref(text: Any) -> bool:
    """Whether :meth:`ArtifactRef.parse` accepts ``text`` (surrounding space
    ignored); ``False`` for anything that is not a ``str``.

    >>> is_artifact_ref("artifact:transcripts/t"), is_artifact_ref("take.srt")
    (True, False)
    >>> is_artifact_ref("artifact: Hello there.")
    False
    """
    try:
        ArtifactRef.parse(text)
    except (ValueError, TypeError):
        return False
    return True


def _key_problem(key: str) -> str | None:
    """Why ``key`` cannot be an artifact key, or ``None`` when it can."""
    if not key or re.search(r"\s", key) or key.startswith("/"):
        return f"not an artifact key: {key!r}"
    if _PINNED.fullmatch(key):
        return (
            f"artifact key {key!r} ends in `@<sha256>`, which a reference reads "
            "as a content pin"
        )
    return None


@dataclass(frozen=True)
class ArtifactRef:
    """A reference to an artifact: its ``key``, the ``store`` that files it when
    known, and the content ``pin`` when it names one: the store's content hash,
    64 hex digits of SHA-256 (an ``Artifact.asset_id``), kept lowercase.

    Raises ``ValueError`` for a reference that would not read back as itself: an
    empty key or one with whitespace, a key starting with ``/`` or ending in
    ``@<sha256>``, a store with ``/`` in it, or a pin that is not 64 hex digits.
    """

    key: str
    store: str | None = None
    pin: str | None = None

    def __post_init__(self) -> None:
        if (problem := _key_problem(self.key)) is not None:
            raise ValueError(problem)
        if self.store is not None and (
            not self.store or "/" in self.store or re.search(r"\s", self.store)
        ):
            raise ValueError(f"not a store name: {self.store!r}")
        if self.pin is not None:
            if not _PIN.fullmatch(self.pin):
                raise ValueError(f"a pin is a 64-digit hex digest: {self.pin!r}")
            object.__setattr__(self, "pin", self.pin.lower())

    @classmethod
    def parse(cls, text: str, *, require_prefix: bool = True) -> ArtifactRef:
        """The reference ``text`` spells, with the whole name as ``key``
        (``store`` is ``None``; see :meth:`locate`).

        ``require_prefix=False`` also reads a name without ``artifact:``, the
        ``<store>/<key>@<sha256>`` that an records in a take's manifest.

        Anything it refuses raises ``ValueError("not an artifact reference: ...")``,
        chained to the key's own error when that is the reason.

        >>> ArtifactRef.parse("  artifact:k  ")
        ArtifactRef(key='k', store=None, pin=None)
        >>> ArtifactRef.parse("take.srt")
        Traceback (most recent call last):
        ...
        ValueError: not an artifact reference: 'take.srt'
        >>> ArtifactRef.parse("takes/a", require_prefix=False)
        ArtifactRef(key='takes/a', store=None, pin=None)
        """
        if not isinstance(text, str):
            raise TypeError(f"an artifact reference is text, not {type(text).__name__}")
        stripped = text.strip()
        matched = _REF.fullmatch(stripped)
        if matched is None and not require_prefix:
            matched = _NAME.fullmatch(stripped)
        if matched is None:
            raise ValueError(f"not an artifact reference: {text!r}")
        name, pin = matched["name"] if matched.re is _REF else matched[0], None
        if pinned := _PINNED.fullmatch(name):
            name, pin = pinned["key"], pinned["pin"]
        try:
            return cls(name, pin=pin)
        except ValueError as error:
            raise ValueError(f"not an artifact reference: {text!r}") from error

    def format(self) -> str:
        """The reference as text: ``artifact:[<store>/]<key>[@<pin>]``."""
        store = "" if self.store is None else f"{self.store}/"
        pin = "" if self.pin is None else f"@{self.pin}"
        return f"{ARTIFACT_REF_PREFIX}{store}{self.key}{pin}"

    def locate(self, mall: Mapping[str, Any], *, default_store: str) -> ArtifactRef:
        """This reference with its ``store`` decided against ``mall``.

        A ``store`` already set is kept. Otherwise the key's first segment names
        a store of ``mall`` when the rest is itself a key (so ``takes/`` and
        ``takes//a`` stay whole) and that store holds it, or when
        ``default_store`` does not hold the whole key (so a pinned reference
        whose key was since deleted still finds its store); else the whole key
        belongs to ``default_store``.

        >>> mall = {"transcripts": {}, "takes": {"a": 1}}
        >>> ArtifactRef.parse("artifact:takes/a").locate(mall, default_store="transcripts")
        ArtifactRef(key='a', store='takes', pin=None)
        >>> ArtifactRef.parse("artifact:k").locate(mall, default_store="transcripts")
        ArtifactRef(key='k', store='transcripts', pin=None)
        """
        if self.store is not None:
            return self
        head, _, rest = self.key.partition("/")
        if (
            _key_problem(rest) is None
            and head in mall
            and (
                _holds_key(mall[head], rest)
                # ``is None``, not truthiness: ``bool(store)`` lists a catalog
                or (default := mall.get(default_store)) is None
                or not _holds_key(default, self.key)
            )
        ):
            return replace(self, store=head, key=rest)
        return replace(self, store=default_store)


def _holds_key(store: Any, key: str) -> bool:
    """``key in store``, reading a store that cannot answer as not holding it."""
    try:
        return key in store
    except Exception:  # noqa: BLE001 - a store that cannot say does not hold it
        return False
