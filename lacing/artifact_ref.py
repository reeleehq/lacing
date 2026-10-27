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

:meth:`lacing.ArtifactStore.resolve` reads what a reference names.

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
_PINNED = re.compile(r"(?P<key>.+)@(?P<pin>[0-9a-f]{64})")
_PIN = re.compile(r"[0-9a-f]{64}")


def is_artifact_ref(text: str) -> bool:
    """Whether ``text`` is an ``artifact:`` reference (surrounding space ignored).

    >>> is_artifact_ref("artifact:transcripts/t"), is_artifact_ref("take.srt")
    (True, False)
    >>> is_artifact_ref("artifact: Hello there.")
    False
    """
    return _REF.fullmatch(text.strip()) is not None


@dataclass(frozen=True)
class ArtifactRef:
    """A reference to an artifact: its ``key``, the ``store`` that files it when
    known, and the content ``pin`` (a SHA-256 hex ``asset_id``) when it names one.

    Raises ``ValueError`` for a reference that would not read back as itself: an
    empty key or one with whitespace, a key starting with ``/`` or ending in
    ``@<sha256>``, a store with ``/`` in it, or a pin that is not 64 hex digits.
    """

    key: str
    store: str | None = None
    pin: str | None = None

    def __post_init__(self) -> None:
        if not self.key or re.search(r"\s", self.key) or self.key.startswith("/"):
            raise ValueError(f"not an artifact key: {self.key!r}")
        if _PINNED.fullmatch(self.key):
            raise ValueError(
                f"artifact key {self.key!r} ends in `@<sha256>`, which a "
                "reference reads as a content pin"
            )
        if self.store is not None and (
            not self.store or "/" in self.store or re.search(r"\s", self.store)
        ):
            raise ValueError(f"not a store name: {self.store!r}")
        if self.pin is not None and not _PIN.fullmatch(self.pin):
            raise ValueError(f"a pin is a 64-digit lowercase hex digest: {self.pin!r}")

    @classmethod
    def parse(cls, text: str) -> ArtifactRef:
        """The reference ``text`` spells, with the whole name as ``key``
        (``store`` is ``None``; see :meth:`locate`).

        >>> ArtifactRef.parse("  artifact:k  ")
        ArtifactRef(key='k', store=None, pin=None)
        >>> ArtifactRef.parse("take.srt")
        Traceback (most recent call last):
        ...
        ValueError: not an artifact reference: 'take.srt'
        """
        matched = _REF.fullmatch(text.strip())
        if matched is None:
            raise ValueError(f"not an artifact reference: {text!r}")
        name, pin = matched["name"], None
        if pinned := _PINNED.fullmatch(name):
            name, pin = pinned["key"], pinned["pin"]
        return cls(name, pin=pin)

    def format(self) -> str:
        """The reference as text: ``artifact:[<store>/]<key>[@<pin>]``."""
        store = "" if self.store is None else f"{self.store}/"
        pin = "" if self.pin is None else f"@{self.pin}"
        return f"{ARTIFACT_REF_PREFIX}{store}{self.key}{pin}"

    __str__ = format

    def locate(self, mall: Mapping[str, Any], *, default_store: str) -> ArtifactRef:
        """This reference with its ``store`` decided against ``mall``.

        A ``store`` already set is kept. Otherwise the key's first segment names
        a store of ``mall`` when that store holds the rest of the key, or when
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
            rest
            and head in mall
            and (
                _holds_key(mall[head], rest)
                or not _holds_key(mall.get(default_store) or {}, self.key)
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
