"""Artifact store — a metadata catalog and a blob store behind one facade.

An :class:`~lacing.artifact.Artifact` describes a generated file; this module
*persists* artifacts. It is the storage layer that ``reelee`` (and any other
producer) builds on so artifacts survive a process restart and are reachable
from another machine — not just from the browser tab that generated them.

Design
------

The store keeps **three concerns separate** (see
``misc/docs/Artifact Store Architecture — design notes.md``):

- **Data organization** — artifacts are *physically flat*: a **catalog**
  (``id -> record``) holds metadata, a **blob store** (``content_hash ->
  bytes``) holds the heavy bytes. Neither key encodes ownership or grouping.
- **Infrastructure mapping** — :class:`ArtifactStore` is a thin *facade* that
  composes two **injected** key-value stores. The backing stores are ordinary
  ``MutableMapping`` objects, so the backend swaps (in-memory -> filesystem ->
  object store) by dependency injection, with no change to callers.
- **Access calculus** — deliberately *absent here*. :class:`ArtifactStore` is
  an unprivileged primitive that checks nothing; a caller that needs access
  control wraps it in a permission-enforcing facade of its own.

Identity is an **explicit string key**, not assumed to be the content hash:
artifacts often get a stable id *before* their bytes exist (and hence before
they can be hashed). The catalog is therefore generic over the record type and
keyed by whatever id the caller chooses; the content hash, when known, is just
a field on the record and the key of the blob store.

Consistency: there is no transaction spanning the two stores, so :meth:`save`
writes the **blob first, then the catalog row**. Because blobs are
content-addressed the blob write is idempotent; a crash in between leaves at
worst an unreferenced (orphan) blob — never a catalog row pointing at missing
bytes.

Examples
--------

>>> from lacing import Artifact
>>> store = ArtifactStore.in_memory()
>>> art = Artifact.from_bytes(
...     b"fake-png-bytes", kind="image",
...     was_generated_by="agent:flux", was_attributed_to="user:thor",
... )
>>> _ = store.save(art.asset_id, art)
>>> store[art.asset_id].kind
'image'
>>> art.asset_id in store
True
>>> len(store)
1
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import BaseModel

from dol import Files, filt_iter, wrap_kvs

from lacing.artifact import Artifact, hash_bytes
from lacing.artifact_ref import ArtifactRef


#: Pre-v1 ``s3dol.store.S3Store`` kwarg names -> their ``s3dol.s3_store``
#: equivalents. Kept so callers of :meth:`ArtifactStore.from_s3` that still
#: spell credentials the old way keep working (with a DeprecationWarning)
#: rather than getting an opaque TypeError from a signature they never saw.
_S3DOL_LEGACY_KWARGS = {
    "profile_name": "profile",
    "path": "prefix",
}


def _s3_kwargs_to_v1(s3_kwargs: dict) -> dict:
    """Translate pre-v1 s3dol kwargs to the v1 ``s3_store`` signature.

    s3dol v1 takes credentials as one ``credentials=`` value (normalised to a
    picklable spec, so the store survives a process hop) rather than three
    loose ``aws_*`` kwargs, and replaces the ``make_bucket`` tri-state with
    ``on_missing_bucket``.

    >>> _s3_kwargs_to_v1({'endpoint_url': 'https://x', 'region_name': 'eu-west-1'})
    {'endpoint_url': 'https://x', 'region_name': 'eu-west-1'}
    """
    import warnings

    kwargs = dict(s3_kwargs)
    deprecated = []

    access = kwargs.pop("aws_access_key_id", None)
    secret = kwargs.pop("aws_secret_access_key", None)
    token = kwargs.pop("aws_session_token", None)
    if access or secret or token:
        deprecated.append("aws_access_key_id/aws_secret_access_key/aws_session_token")
        if not (access and secret):
            raise TypeError(
                "from_s3 needs both aws_access_key_id and aws_secret_access_key "
                "(a token alone is not a credential). Better: pass s3dol v1's "
                "credentials=(key, secret) or credentials='<profile-name>'."
            )
        kwargs["credentials"] = (access, secret, token) if token else (access, secret)

    if "make_bucket" in kwargs:
        deprecated.append("make_bucket")
        # v0 tri-state -> v1 policy. Note v1's default never probes and never
        # creates, so a missing bucket surfaces on first use rather than being
        # silently minted from a typo.
        kwargs["on_missing_bucket"] = {
            True: "create",
            False: "raise",
            None: "assume",
        }[kwargs.pop("make_bucket")]

    for old, new in _S3DOL_LEGACY_KWARGS.items():
        if old in kwargs:
            deprecated.append(old)
            kwargs[new] = kwargs.pop(old)

    if deprecated:
        warnings.warn(
            f"from_s3 received pre-v1 s3dol kwarg(s): {', '.join(deprecated)}. "
            f"They were translated to the s3dol>=1 signature "
            f"(credentials=/profile=/prefix=/on_missing_bucket=); pass those "
            f"directly instead. Translation will be removed in a future lacing.",
            DeprecationWarning,
            stacklevel=3,
        )
    return kwargs


__all__ = [
    "ArtifactStore",
    "ResolvedArtifact",
    "content_hash_of",
    "WritePolicy",
    "keep_rights",
    "resolve_in_mall",
]

logger = logging.getLogger(__name__)

#: ``on_write(record, previous) -> record``: see :class:`ArtifactStore`.
WritePolicy = Callable[[BaseModel, Callable[[], BaseModel | None]], BaseModel]


def _mk_sql_refcount(sql_store) -> Callable[[str], int]:
    """Build a ``content_hash -> row count`` query over a ``sqldol`` store.

    Reaches through the ``sqldol.SQLAlchemyStore`` to its persister's ORM
    session and counts rows whose indexed ``content_hash`` column matches —
    one query, not a scan. Used by :meth:`ArtifactStore.from_sql` to wire the
    GC reference-count capability that :meth:`ArtifactStore.count_refs` probes
    for. Works identically on SQLite and Postgres (plain SQLAlchemy).
    """
    from sqlalchemy import func

    persister = sql_store.store  # the SQLAlchemyPersister behind the dol Store
    table = persister.table.__table__

    def refcount(content_hash: str) -> int:
        return (
            persister.session.query(func.count())
            .filter(table.c.content_hash == content_hash)
            .scalar()
        )

    return refcount


def content_hash_of(record: Any) -> str | None:
    """The content hash naming ``record``'s bytes in the blob store, if it has one.

    Its ``asset_id`` (a :class:`lacing.Artifact`) when that is a string, else its
    ``content_hash`` (reelee's records) when that is, else ``None`` (a record
    filed before its bytes exist).

    >>> from types import SimpleNamespace as Record
    >>> content_hash_of(Record(asset_id="a1", content_hash="c1"))
    'a1'
    >>> content_hash_of(Record(content_hash="c1")), content_hash_of(Record())
    ('c1', None)
    """
    for name in ("asset_id", "content_hash"):
        value = getattr(record, name, None)
        if isinstance(value, str):
            return value
    return None


# ``from_sql`` takes a ``content_hash_of`` argument, which shadows the function.
_default_content_hash_of = content_hash_of


def keep_rights(
    record: BaseModel, previous: Callable[[], BaseModel | None]
) -> BaseModel:
    """``record``, carrying forward the ``rights`` of the record it replaces when
    it states none for the same bytes (lacing#60; the choice is in lacing#94).

    :class:`ArtifactStore`'s default ``on_write`` policy. Identical bytes carry
    the same third-party obligations whoever records them again, and
    ``rights is None`` reads as "we made this", so a rights-less re-record must
    not erase them. An explicit ``rights`` replaces the old one; other bytes
    (another :func:`content_hash_of`) do not inherit; to clear rights on
    purpose, delete the record first.

    ``previous`` is called only when a carry is possible: ``record`` is a
    pydantic model with a ``rights`` field set to ``None`` and a content hash.
    Anything else (a dict, a record without ``rights``, a record filed before
    its bytes exist) is returned as given, without reading the catalog.

    Raises:
        ValueError: the carried ``rights`` do not validate on ``record``'s
            type. Refusing the write beats silently erasing obligations.

    >>> from lacing import Artifact, Rights
    >>> def made(rights=None):
    ...     return Artifact.from_bytes(b"x", kind="image", was_generated_by="t",
    ...                                was_attributed_to="u", rights=rights)
    >>> acquired = made(Rights(provider="openverse"))
    >>> keep_rights(made(), lambda: acquired).rights.provider
    'openverse'
    >>> keep_rights(made(), lambda: None).rights is None  # a new key
    True
    """
    if not isinstance(record, BaseModel):
        return record
    if "rights" not in type(record).model_fields or record.rights is not None:
        return record  # nothing to keep: no field, or a statement of its own
    content_hash = content_hash_of(record)
    if content_hash is None:
        return record  # no bytes yet, so nothing to be "the same bytes" as
    replaced = previous()
    kept = getattr(replaced, "rights", None)
    if kept is None or content_hash_of(replaced) != content_hash:
        return record
    if isinstance(kept, BaseModel):
        kept = kept.model_dump()
    try:
        return type(record).model_validate({**record.model_dump(), "rights": kept})
    except ValueError as error:
        raise ValueError(
            f"A rights-less {type(record).__name__} for content {content_hash} "
            f"replaces a record with rights, and those rights cannot be carried "
            f"forward onto it ({error}). Refusing the write rather than erasing "
            f"the obligations: state the rights explicitly, or delete the old "
            f"record first."
        ) from error


class ResolvedArtifact(NamedTuple):
    """What :meth:`ArtifactStore.resolve` found.

    - ``key``: the catalog key whose ``record`` was used; ``None``, as is
      ``record``, for pinned bytes no record holds any more.
    - ``content_hash``: the blob's key (the pin, when the reference had one).
    - ``data``: the bytes, or ``None`` when resolved with ``read=False``.
    """

    key: str | None
    record: BaseModel | None
    content_hash: str
    data: bytes | None


def resolve_in_mall(
    ref: ArtifactRef | str,
    mall: Mapping[str, Any],
    *,
    default_store: str,
    read: bool = True,
) -> ResolvedArtifact:
    """What ``ref`` names in ``mall`` (store names -> :class:`ArtifactStore`).

    The store is the one :meth:`ArtifactRef.locate` picks; the rest is that
    store's :meth:`ArtifactStore.resolve`.

    Raises:
        LookupError: the store is not in ``mall`` (the message names those
            that are); a plain ``LookupError``, so ``except KeyError`` still
            tells "no such key" from "no such store".
        TypeError: the store has no ``resolve`` method.
        KeyError, ValueError: what :meth:`ArtifactStore.resolve` raises.

    >>> from lacing import Artifact
    >>> takes = ArtifactStore.in_memory()
    >>> art = Artifact.from_bytes(b"x", kind="text", was_generated_by="t",
    ...                           was_attributed_to="u")
    >>> _ = takes.save("a", art, data=b"x")
    >>> mall = {"transcripts": ArtifactStore.in_memory(), "takes": takes}
    >>> resolve_in_mall("artifact:takes/a", mall, default_store="transcripts").data
    b'x'
    """
    if isinstance(ref, str):
        ref = ArtifactRef.parse(ref)
    located = ref.locate(mall, default_store=default_store)
    if located.store not in mall:
        raise LookupError(
            f"{ref}: no store {located.store!r} in the mall, whose stores are "
            f"{', '.join(map(repr, mall))}"
        )
    store = mall[located.store]
    resolve = getattr(store, "resolve", None)
    if not callable(resolve):
        raise TypeError(
            f"{ref}: the mall's store {located.store!r} is a "
            f"{type(store).__name__}, which has no resolve method"
        )
    return resolve(located, read=read)


@dataclass(eq=False)
class ArtifactStore(MutableMapping):
    """Facade over an artifact ``catalog`` and an optional ``blobs`` store.

    The object *is* a ``MutableMapping[str, record]`` over the catalog —
    ``store[artifact_id]``, iteration, ``len``, ``get``, ``clear`` and the
    rest of the mapping surface all act on artifact **metadata records**. The
    heavier byte operations (:meth:`put_blob`, :meth:`get_blob`,
    :meth:`has_blob`) are rich methods that are deliberately *not* squeezed
    into the mapping protocol.

    Args:
        catalog: Injected ``id -> record`` store. Records are pydantic models
            (``lacing.Artifact`` by default, but any ``BaseModel`` works). The
            store itself does not inspect the record's shape; the default
            ``on_write`` policy reads a ``rights`` field when there is one.
        blobs: Injected ``content_hash -> bytes`` store, or ``None`` for a
            catalog-only store (Stage-1 metadata persistence). Blob methods
            raise / no-op when it is ``None``. This is the *raw* backend:
            on a filesystem backend its own ``del`` and iteration do no
            containment check, so go through :meth:`delete_blob` and
            :meth:`iter_blobs` (and the read methods) rather than touching
            ``store.blobs`` directly (lacing#55).
        on_write: Keyword-only. ``on_write(record, previous) -> record``, the
            policy every catalog write through the facade (``store[k] = r``,
            :meth:`save`, ``update``) passes through. ``previous()`` reads the
            record being replaced: ``None`` for a new key, and ``None`` (with
            a logged warning) when that record cannot be read. The default,
            :func:`keep_rights`, keeps the ``rights`` of a record replaced by a
            rights-less one for the same bytes (lacing#60); ``None`` writes
            records as given (last write wins). Writes straight to
            ``catalog`` bypass it.

    Construct one with :meth:`in_memory` or :meth:`from_directory` rather than
    wiring the backing stores by hand, unless you are injecting a custom
    backend.
    """

    catalog: MutableMapping[str, BaseModel]
    blobs: MutableMapping[str, bytes] | None = None
    on_write: WritePolicy | None = field(default=keep_rights, kw_only=True)

    # -- catalog: the MutableMapping surface (artifact_id -> record) --------

    def __getitem__(self, artifact_id: str) -> BaseModel:
        return self.catalog[artifact_id]

    def __setitem__(self, artifact_id: str, record: BaseModel) -> None:
        if self.on_write is not None:
            record = self.on_write(record, lambda: self._replaced(artifact_id))
        self.catalog[artifact_id] = record

    def __delitem__(self, artifact_id: str) -> None:
        del self.catalog[artifact_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self.catalog)

    def __len__(self) -> int:
        return len(self.catalog)

    # -- domain verbs ------------------------------------------------------

    def save(
        self, artifact_id: str, record: BaseModel, *, data: bytes | None = None
    ) -> str | None:
        """Persist one artifact, optionally with its bytes.

        Writes the blob (if ``data`` is given) **before** the catalog row, so a
        crash never leaves the catalog pointing at missing bytes. Idempotent on
        ``artifact_id`` — and, for the blob, on content — so retries are safe.

        Args:
            artifact_id: The stable string id this artifact is filed under.
            record: The metadata record to store in the catalog.
            data: Optional raw bytes. When given, they are stored
                content-addressed and the content hash is returned; the caller
                is responsible for also recording that hash on ``record``.

        Returns:
            The blob's content hash if ``data`` was written, else ``None``.

        Raises:
            RuntimeError: ``data`` was given but no blob store is configured.
        """
        content_hash: str | None = None
        if data is not None:
            if self.blobs is None:
                raise RuntimeError(
                    "ArtifactStore.save received blob bytes but has no blob "
                    "store configured. Construct it with .in_memory() or "
                    ".from_directory(), or inject a `blobs` store."
                )
            content_hash = hash_bytes(data)
            self.blobs[content_hash] = data  # content-addressed -> idempotent
        self[artifact_id] = record
        return content_hash

    def _replaced(self, artifact_id: str) -> BaseModel | None:
        """The record at ``artifact_id`` that a write is about to replace;
        ``None`` for a new key, or (with a warning) for a damaged record."""
        try:
            return self.catalog[artifact_id]
        except KeyError:
            return None
        except ValueError as error:
            logger.warning(
                "The record at %r cannot be read, so the write replacing it "
                "goes through as given: %s",
                artifact_id,
                error,
            )
            return None

    def index(self) -> dict[str, BaseModel]:
        """Return the whole catalog as a plain dict (e.g. for UI hydration)."""
        return dict(self.catalog)

    # -- references ----------------------------------------------------------

    def resolve(self, ref: ArtifactRef | str, *, read: bool = True) -> ResolvedArtifact:
        """The record and bytes ``ref`` names in this store.

        ``ref`` is an :class:`lacing.ArtifactRef` or its text. Its ``store`` is not
        consulted: this store is the one it names. References spanning a mall go
        through :func:`resolve_in_mall`, which picks the store first.

        Unpinned, it reads the record at ``ref.key`` and the bytes its content
        hash names (:func:`content_hash_of`). Pinned, it reads the pinned bytes
        even when the key has since been saved with other content or removed. A
        pin is the store's content hash: the SHA-256 hex digest of the bytes, as
        :meth:`save` and :meth:`put_blob` compute it. The record is the one at
        the key if it still holds those bytes, else the first a scan of
        catalog scan finds, else ``None``; only that fallback scans.

        With ``read=False`` it only checks that the bytes exist
        (:meth:`has_blob`) and leaves ``data`` as ``None``, so a caller that
        streams (a video, say) can use :meth:`iter_blob` or :meth:`blob_path`
        on ``content_hash``. That mode does **not** check the bytes against the
        pin; with ``read=True`` a pinned read does.

        Raises:
            KeyError: no record at the key (unpinned), a record with no content
                yet, no blob store (``blobs=None``), or no bytes for the content.
            ValueError: ``ref`` text is not a reference, the record at the key
                is damaged (unpinned; pydantic's error), or the bytes read do
                not hash to the pin.

        >>> from lacing import Artifact, ArtifactRef
        >>> st = ArtifactStore.in_memory()
        >>> first = Artifact.from_bytes(b"v1", kind="text", was_generated_by="t",
        ...                             was_attributed_to="u")
        >>> _ = st.save("k", first, data=b"v1")
        >>> pinned = ArtifactRef("k", pin=first.asset_id)
        >>> second = Artifact.from_bytes(b"v2", kind="text", was_generated_by="t",
        ...                              was_attributed_to="u")
        >>> _ = st.save("k", second, data=b"v2")
        >>> st.resolve("artifact:k").data, st.resolve(pinned).data
        (b'v2', b'v1')
        >>> st.resolve(pinned).key is None  # no record holds v1 any more
        True
        """
        if isinstance(ref, str):
            ref = ArtifactRef.parse(ref)
        if ref.pin is None:
            record = self[ref.key]
            content_hash = content_hash_of(record)
            if content_hash is None:
                raise KeyError(f"{ref}: the record at {ref.key!r} has no content yet")
            data = self._content(ref, content_hash, read=read)
            return ResolvedArtifact(ref.key, record, content_hash, data)
        data = self._content(ref, ref.pin, read=read)
        if data is not None and hash_bytes(data) != ref.pin:
            raise ValueError(f"{ref}: the stored bytes do not hash to the pin")
        holder = next(self._records_with_content(ref.pin, [ref.key]), None)
        if holder is None:
            keys = self._keys_with_content(ref.pin)
            holder = next(self._records_with_content(ref.pin, keys), None)
        key, record = holder or (None, None)
        return ResolvedArtifact(key, record, ref.pin, data)

    def _keys_with_content(self, content_hash: str) -> Iterator[str]:
        """Yield, lazily, the catalog keys whose record names ``content_hash``,
        skipping records that cannot be read. Iterates the live catalog: do not
        delete while it runs."""
        # A full catalog scan: a store with a content-hash index can override this.
        for key, _ in self._records_with_content(content_hash, self):
            yield key

    def _records_with_content(
        self, content_hash: str, keys: Iterable[str]
    ) -> Iterator[tuple[str, BaseModel]]:
        """``(key, record)`` for each of ``keys`` whose record names ``content_hash``;
        unreadable records are skipped."""
        for key in keys:
            try:
                record = self[key]
            except (KeyError, ValueError):  # a racing delete, or a damaged record
                continue
            if content_hash_of(record) == content_hash:
                yield key, record

    def _content(
        self, ref: ArtifactRef, content_hash: str, *, read: bool
    ) -> bytes | None:
        """The bytes for ``content_hash`` (``None`` unless ``read``); ``KeyError``
        when there are none."""
        if self.blobs is None:
            raise KeyError(f"{ref}: this store has no blob store, so no bytes")
        if not read:
            if not self.has_blob(content_hash):
                raise KeyError(f"{ref}: no bytes for content {content_hash}")
            return None
        data = self.get_blob(content_hash)
        if data is None:
            raise KeyError(f"{ref}: no bytes for content {content_hash}")
        return data

    # -- blobs: rich byte methods ------------------------------------------

    def put_blob(self, data: bytes) -> str:
        """Store ``data`` content-addressed; return its content hash.

        Idempotent: identical bytes always map to the same hash and overwrite
        an identical blob. Delegates to :meth:`put_blob_stream` so there is
        exactly one write path — and therefore one atomicity story
        (lacing#25).

        Raises:
            RuntimeError: no blob store is configured.
        """
        return self.put_blob_stream((data,))

    def put_blob_stream(self, chunks: Iterable[bytes]) -> str:
        """Stream ``chunks`` content-addressed; return their SHA-256 hash.

        The streaming-friendly counterpart to :meth:`put_blob` — callers hand
        in an iterable (e.g. ``requests.Response.iter_content``) instead of
        materializing the whole bytestring upfront. The hash is computed on
        the fly.

        When the blob store is filesystem-backed (exposes ``rootdir``, as the
        default directory store does), the bytes spool straight to a
        same-directory tempfile and are renamed into place with
        ``os.replace`` once the hash is known (lacing#25). Consequences a
        caller may rely on:

        - **peak memory is one chunk**, not 2× the payload — 100 MB videos
          flow through without a 200 MB spike;
        - **a partial blob is never observable under its content address** —
          the name a reader could find only exists after the rename, which is
          atomic on POSIX and on Windows for same-directory renames — so
          ``has_blob(h) == True`` really does mean the full bytes are there;
        - a failed or abandoned stream leaves nothing behind (the tempfile is
          unlinked).

        Backends without a ``rootdir`` (plain ``dict``, object-store
        mappings) fall back to buffering the payload and assigning it whole —
        their ``__setitem__`` is the atomicity story there.

        Raises:
            RuntimeError: no blob store is configured.
        """
        if self.blobs is None:
            raise RuntimeError("ArtifactStore has no blob store configured.")
        rootdir = getattr(self.blobs, "rootdir", None)
        if rootdir is not None:
            return _spool_chunks_to_dir(chunks, Path(rootdir))
        hasher = hashlib.sha256()
        buf = bytearray()
        for chunk in chunks:
            hasher.update(chunk)
            buf.extend(chunk)
        content_hash = hasher.hexdigest()
        self.blobs[content_hash] = bytes(buf)
        return content_hash

    def get_blob(self, content_hash: str) -> bytes | None:
        """Return the bytes for ``content_hash``, or ``None`` if absent.

        On a filesystem-backed store (one exposing ``rootdir``) the bytes are
        read through :func:`_open_within`, never by re-opening the path by
        name, so a key that would land outside ``rootdir`` — by ``..``, an
        absolute path, or a symlink, including one swapped in *after* the
        containment check (lacing#50) — reads as absent.
        """
        if self.blobs is None:
            return None
        rootdir = getattr(self.blobs, "rootdir", None)
        if rootdir is not None:
            opened = _open_within(rootdir, content_hash)
            if opened is None:
                return None
            with os.fdopen(opened[1], "rb") as blob_file:
                return blob_file.read()
        try:
            return self.blobs[content_hash]
        except KeyError:
            return None

    def iter_blob(
        self, content_hash: str, *, chunk_size: int = 1 << 16
    ) -> Iterator[bytes]:
        """Yield the blob's bytes in ``chunk_size`` chunks.

        The streaming counterpart to :meth:`get_blob` — what an HTTP response
        body iterates over when serving a large blob without holding it all
        in process memory. The default implementation reads the whole blob
        via :meth:`get_blob` and re-chunks it; a filesystem-backed store can
        be swapped for a true streaming reader without changing this API.

        Raises:
            KeyError: no blob exists for ``content_hash``.
        """
        data = self.get_blob(content_hash)
        if data is None:
            raise KeyError(content_hash)
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]

    def blob_path(self, content_hash: str) -> Path | None:
        """Return the local filesystem path of the blob, or ``None``.

        The store's blob backend is opaque (any ``MutableMapping``), but some
        backends — notably the filesystem-backed ``dol.Files`` produced by
        :meth:`from_directory` — store each blob as one file under a known
        root directory. This method exposes that path *when available*, so a
        caller (e.g. a FastAPI route serving video) can hand the OS the file
        descriptor and let it answer HTTP ``Range`` requests directly. It
        returns ``None`` for:

        - blob stores without a ``rootdir`` attribute (e.g. plain ``dict``,
          object-store backends — callers should fall back to
          :meth:`iter_blob`);
        - blobs that are not present.
        - a ``content_hash`` that does not resolve to a path *inside*
          ``rootdir`` (path traversal, e.g. ``"../../etc/passwd"`` or an
          absolute path, or a same-named symlink pointing outside the
          store) — refused rather than served (lacing#50).

        Callers must treat ``None`` as the cue to use the streaming read
        path, not as an error. Deleting and listing blobs have contained
        counterparts too (:meth:`delete_blob`, :meth:`iter_blobs`), and the
        :meth:`from_directory` catalog confines artifact ids the same way
        (lacing#55).

        The containment check is *point-in-time*: the returned path is the
        fully resolved, symlink-free location of a regular file that was
        inside ``rootdir`` when checked. The caller opens it later, by name,
        so if untrusted parties can write into ``rootdir`` itself, open it
        with ``O_NOFOLLOW`` — or serve via :meth:`iter_blob`, which reads
        through a descriptor and has no such window.
        """
        if self.blobs is None:
            return None
        rootdir = getattr(self.blobs, "rootdir", None)
        if rootdir is None:
            return None
        opened = _open_within(rootdir, content_hash)
        if opened is None:
            return None
        path, fd = opened
        os.close(fd)
        return path

    def has_blob(self, content_hash: str) -> bool:
        """Whether the blob store holds ``content_hash``.

        On a filesystem-backed store this is exactly "would :meth:`get_blob`
        return bytes": ``False`` for a key that resolves outside ``rootdir``
        or names anything but a regular file — see :func:`_open_within`.
        Backends without a ``rootdir`` (``dict``, object stores) have no
        filesystem to escape, so their keys pass through unfiltered.
        """
        if self.blobs is None:
            return False
        rootdir = getattr(self.blobs, "rootdir", None)
        if rootdir is None:
            return content_hash in self.blobs
        opened = _open_within(rootdir, content_hash)
        if opened is None:
            return False
        os.close(opened[1])
        return True

    def delete_blob(self, content_hash: str) -> None:
        """Delete the blob ``content_hash``; ``KeyError`` if there is none.

        The contained counterpart of ``del store.blobs[content_hash]``
        (lacing#55). On a filesystem-backed store (one exposing ``rootdir``)
        a key is deleted only if :meth:`has_blob` would say it exists — a
        regular file that resolves inside ``rootdir`` (see
        :class:`_ContainedDirStore`, the same gate the catalog of
        :meth:`from_directory` uses). A key that escapes (``..``, an absolute path, a
        NUL, a symlink pointing outside) raises ``KeyError`` exactly like a
        missing blob, as does any key with a ``..`` segment, and nothing
        outside the root is touched. The deletion itself is delegated to the
        backend's own ``__delitem__`` on the key as given (normalised), so the
        backend's delete policy (e.g. ``dol.Files`` moving files to the
        trash) is unchanged, and deleting an in-root symlink removes the
        link, never the blob it points at.

        The check is point-in-time, like :meth:`blob_path`: a party that can
        write into ``rootdir`` and swap a *directory* component of a nested
        key for a symlink between the check and the delete can still redirect
        it. Flat content-hash keys, which is all this store writes, have no
        such component.

        Backends without a ``rootdir`` (``dict``, object stores) have no
        filesystem to escape; the key passes through to their ``del``.

        Raises:
            KeyError: no such blob, the key escapes the root, or no blob store
                is configured.
        """
        if self.blobs is None:
            raise KeyError(content_hash)
        if getattr(self.blobs, "rootdir", None) is None:
            del self.blobs[content_hash]
            return
        del _ContainedDirStore(self.blobs)[content_hash]

    def iter_blobs(self) -> Iterator[str]:
        """Yield the content hash (key) of every blob in the blob store.

        The contained counterpart of ``iter(store.blobs)`` (lacing#55). On a
        filesystem-backed store it yields exactly the keys :meth:`has_blob`
        accepts — regular files inside ``rootdir`` — and never descends into
        a symlinked directory (``dol.Files`` does, so its listing can yield
        files that live outside the root, or loop on a symlink cycle).
        Hidden entries are skipped, as ``dol.Files`` skips them, which also
        keeps the in-flight ``.blob-*.part`` spool files of
        :meth:`put_blob_stream` out of the listing.

        Yields nothing when no blob store is configured; other backends are
        iterated as they are.
        """
        if self.blobs is None:
            return
        if getattr(self.blobs, "rootdir", None) is None:
            yield from self.blobs
            return
        yield from _ContainedDirStore(self.blobs)

    def blob_location(self, content_hash: str) -> "str | Path | None":
        """Resolve the cheapest *servable* location for a blob — without
        reading its bytes. The capability the HTTP layer probes to serve a
        blob the most efficient way, generalizing :meth:`blob_path` so
        filesystem / S3 / R2 backends all answer one probe:

        - **object-store** backends (S3/R2) that expose a presigned-URL
          capability — a ``url_for(content_hash)`` callable — return a **URL
          string**, so the caller can 302-redirect and let the object store
          serve the bytes (and HTTP ``Range``) directly, off the app process;
        - **filesystem** backends return a local **Path** (see
          :meth:`blob_path`) so the caller hands the OS the file (Range free);
        - everything else (plain ``dict``, or a missing blob) returns
          ``None`` — the cue to fall back to :meth:`iter_blob` streaming.

        Callers treat ``None`` as "stream it", not as an error.
        """
        if not self.has_blob(content_hash):
            return None
        url_for = getattr(self.blobs, "url_for", None)
        if callable(url_for):
            try:
                url = url_for(content_hash)
            except Exception as error:
                # A backend may *refuse* to sign rather than sign wrongly —
                # s3dol>=1 does exactly that when its store has been wrapped
                # by a key codec, because the URL could then address a
                # different object. "No safe URL" is not an error here, it is
                # the documented cue to stream; but it should not pass in
                # silence, since streaming through the app is the expensive
                # path this method exists to avoid.
                import warnings

                warnings.warn(
                    f"{type(self.blobs).__name__}.url_for refused to sign "
                    f"({type(error).__name__}: {error}); falling back to "
                    f"streaming. Serving stays correct, just slower.",
                    stacklevel=2,
                )
                url = None
            if url:
                return url
        return self.blob_path(content_hash)

    # -- constructors ------------------------------------------------------

    @classmethod
    def in_memory(cls, *, on_write: WritePolicy | None = keep_rights) -> ArtifactStore:
        """An ArtifactStore backed entirely by in-memory dicts.

        For tests, scratch work, and as the trivial reference backend. Nothing
        persists across processes. ``on_write`` is the write policy (see
        :class:`ArtifactStore`).
        """
        return cls(catalog={}, blobs={}, on_write=on_write)

    @classmethod
    def from_directory(
        cls,
        root: Path | str,
        *,
        record_type: type[BaseModel] = Artifact,
        blob_delete_func: Callable[[str], Any] | None = None,
        catalog_delete_func: Callable[[str], Any] | None = None,
        on_write: WritePolicy | None = keep_rights,
    ) -> ArtifactStore:
        """An ArtifactStore persisted under ``root``.

        Lays out two subdirectories: ``catalog/`` (one ``<id>.json`` file per
        record) and ``blobs/`` (one file per content hash). Both are ``dol``
        filesystem stores, so the same facade works unchanged over any other
        ``dol`` backend (object storage, etc.) when injected directly.

        Artifact ids are confined to ``catalog/`` (lacing#55): an id whose
        ``<id>.json`` would resolve outside it — ``..`` segments, an absolute
        path, a NUL, or a symlink pointing out — is refused with ``KeyError``
        on get, save and delete, and is simply not ``in`` the store. Nested
        ids (``"a/b"``) that stay inside keep working (``save`` creates the
        missing parent directory), and listing never
        follows a symlinked directory out of ``catalog/``. See
        :class:`_ContainedDirStore`.

        Args:
            root: Directory to hold the store. Created if missing.
            record_type: The pydantic model the catalog deserializes JSON into.
                Defaults to :class:`~lacing.artifact.Artifact`; callers with
                their own record schema pass their model here.
            blob_delete_func: How the blob store deletes a file, given its
                path. ``None`` keeps ``dol.Files``' default (move to the OS
                trash); pass ``os.remove`` when blobs are derived data and a
                delete should free the disk.
            catalog_delete_func: The same for the catalog's record files.
                ``None`` keeps ``dol.Files``' default (move to the OS trash,
                a sensible default for records); pass ``os.remove`` for a
                delete that is final.
            on_write: The write policy (see :class:`ArtifactStore`).
        """
        root = Path(root)
        catalog_dir = root / "catalog"
        blob_dir = root / "blobs"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        blob_dir.mkdir(parents=True, exist_ok=True)

        catalog = wrap_kvs(
            filt_iter(
                _ContainedDirStore(
                    Files(str(catalog_dir), delete_func=catalog_delete_func)
                ),
                filt=lambda k: k.endswith(".json"),
            ),
            id_of_key=_catalog_filename,
            key_of_id=lambda filename: (
                filename[:-5] if filename.endswith(".json") else filename
            ),
            data_of_obj=lambda record: record.model_dump_json(indent=2).encode("utf-8"),
            obj_of_data=lambda raw: record_type.model_validate_json(raw),
        )
        blobs = Files(str(blob_dir), delete_func=blob_delete_func)
        return cls(catalog=catalog, blobs=blobs, on_write=on_write)

    def count_refs(self, content_hash: str) -> int:
        """How many catalog records point at ``content_hash`` (a blob).

        The reference count that a garbage collector needs: a blob is safe to
        delete only when **no** catalog record still names its content hash.
        Content-addressed blobs are deduplicated, so two artifacts can share
        one blob — deleting the blob the moment one of them goes away would
        orphan the other.

        This is the *probe* half of a capability pair (mirroring
        :meth:`blob_location` probing a blob store for ``url_for``): a catalog
        backend that can answer the count cheaply — the SQL catalog from
        :meth:`from_sql`, via an indexed ``content_hash`` column — exposes a
        ``refcount_by_content_hash`` callable, and this method uses it so the
        count is **one indexed query, not a full catalog scan**. Any other
        catalog (dict, ``Files``) falls back to scanning every record. The
        facade is unchanged either way; only the speed differs.

        Args:
            content_hash: The blob's content hash (``Artifact.asset_id``).

        Returns:
            The number of catalog records whose content hash equals
            ``content_hash``.
        """
        fast = getattr(self.catalog, "refcount_by_content_hash", None)
        if callable(fast):
            return fast(content_hash)
        # Fallback: scan every record (see ``content_hash_of`` for the fields).
        return sum(
            1
            for record in self.catalog.values()
            if content_hash_of(record) == content_hash
        )

    @classmethod
    def from_s3(
        cls,
        bucket_name: str,
        *,
        catalog: "MutableMapping[str, BaseModel] | None" = None,
        prefix: str | None = None,
        on_write: WritePolicy | None = keep_rights,
        **s3_kwargs,
    ) -> ArtifactStore:
        """An ArtifactStore with **blobs in an S3-compatible object store**
        (AWS S3 / Cloudflare R2 / MinIO / Supabase) via ``s3dol``.

        Content-addressed blobs are a natural fit for object storage: flat,
        immutable, dedup-friendly, forever-cacheable keys. :meth:`blob_location`
        returns a presigned GET URL (via s3dol's ``url_for``) so a serving layer
        can 302-redirect and let the store deliver the bytes (and HTTP ``Range``)
        directly, off the app process.

        The blob and catalog backends are independent by design: the catalog
        defaults to an in-memory dict here — swap in a durable catalog (e.g. a
        Postgres-backed ``MutableMapping``) for production.

        Args:
            bucket_name: The object-store bucket.
            catalog: The ``id -> record`` catalog ``MutableMapping``. Defaults
                to ``{}`` (in-memory).
            prefix: Optional key prefix within the bucket (e.g. ``"blobs"``).
            on_write: The write policy (see :class:`ArtifactStore`).
            **s3_kwargs: Forwarded to ``s3dol.s3_store`` — ``endpoint_url``
                (set for R2 / MinIO / Supabase), ``region_name``, ``profile``,
                ``credentials``, ``preset``, ``anon``, ``on_missing_bucket``.
                The pre-v1 spellings (``aws_access_key_id`` /
                ``aws_secret_access_key`` / ``aws_session_token`` /
                ``profile_name`` / ``make_bucket``) are still accepted and
                translated, with a ``DeprecationWarning``.

        Requires ``s3dol>=1`` (and ``boto3``) — imported lazily so the
        dependency is only needed when this constructor is used.
        """
        from s3dol import s3_store

        blobs = s3_store(
            bucket_name, prefix=prefix or "", **_s3_kwargs_to_v1(s3_kwargs)
        )
        return cls(
            catalog={} if catalog is None else catalog, blobs=blobs, on_write=on_write
        )

    @classmethod
    def from_sql(
        cls,
        uri: str,
        *,
        blobs: "MutableMapping[str, bytes] | None" = None,
        record_type: type[BaseModel] = Artifact,
        collection_name: str = "artifact_catalog",
        content_hash_of: "Callable[[BaseModel], str | None] | None" = None,
        on_write: WritePolicy | None = keep_rights,
        **db_kwargs,
    ) -> ArtifactStore:
        """An ArtifactStore with a **SQL-backed catalog** (durable, queryable)
        via ``sqldol`` — the SQL counterpart of :meth:`from_s3`'s object store.

        The catalog row schema is deliberately minimal and **vendor-neutral**:
        one ``TEXT`` column holds the record serialized exactly as
        :meth:`from_directory` serializes it (``record.model_dump_json`` out,
        ``record_type.model_validate_json`` in), and one indexed ``content_hash``
        column carries the record's blob hash so the GC reference count
        (:meth:`count_refs`) is a single indexed query rather than a full scan.

        Because the connection is just a SQLAlchemy URI, the *same* code runs
        on SQLite for tests and on Postgres in production — that is the whole
        point of the facade. Pick the backend with the ``uri`` alone::

            ArtifactStore.from_sql("sqlite:///artifacts.db")          # local / tests
            ArtifactStore.from_sql("postgresql://u:p@host:5432/db")   # production

        The catalog and blob backends are independent: pass ``blobs`` to pair a
        SQL catalog with any blob store (e.g. ``from_s3``'s ``S3Store``), or
        leave it ``None`` for a catalog-only store (Stage-1 metadata
        persistence; see :meth:`from_aws` for the common S3 + SQL pairing).

        Args:
            uri: SQLAlchemy connection URI (``sqlite:///…`` or
                ``postgresql://…``). The single knob that selects the vendor.
            blobs: Optional ``content_hash -> bytes`` blob store. ``None`` for a
                catalog-only store.
            record_type: The pydantic model the catalog deserializes JSON into.
                Defaults to :class:`~lacing.artifact.Artifact`; callers with
                their own record schema pass their model here.
            collection_name: The SQL table name for the catalog.
            content_hash_of: How to read a record's blob hash for the indexed
                ``content_hash`` column. Defaults to ``asset_id`` (the canonical
                Artifact field), then ``content_hash``. Pass a callable for a
                record whose hash lives elsewhere; records without a hash store
                an empty string.
            on_write: The write policy (see :class:`ArtifactStore`).
            **db_kwargs: Forwarded to ``sqldol.SQLAlchemyStore`` /
                SQLAlchemy's ``create_engine`` (e.g. ``connect_args``,
                ``pool_size``).

        Requires ``sqldol`` (and ``SQLAlchemy``) — imported lazily so the
        dependency is only needed when this constructor is used.
        """
        from sqldol import SQLAlchemyStore
        from sqldol.sql_base import SQLAlchemyPersister

        if content_hash_of is None:
            content_hash_of = _default_content_hash_of

        raw = SQLAlchemyStore(
            uri=uri,
            collection_name=collection_name,
            key_fields={"artifact_id": SQLAlchemyPersister.TYPE_STRING},
            data_fields={
                "record_json": SQLAlchemyPersister.TYPE_TEXT,
                "content_hash": SQLAlchemyPersister.TYPE_STRING,
            },
            **db_kwargs,
        )

        def _key_of_id(row_or_key):
            # ``wrap_kvs`` hands this a key dict on writes and a ``RowKey`` on
            # iteration (sqldol's ``__iter__`` yields ``RowKey``s, which are
            # dicts that also read as attributes). The attribute branch is only
            # for older sqldol releases that iterated ORM rows.
            if isinstance(row_or_key, dict):
                return row_or_key["artifact_id"]
            return row_or_key.artifact_id

        catalog = wrap_kvs(
            raw,
            id_of_key=lambda artifact_id: {"artifact_id": artifact_id},
            key_of_id=_key_of_id,
            data_of_obj=lambda record: {
                "record_json": record.model_dump_json(),
                "content_hash": content_hash_of(record) or "",
            },
            obj_of_data=lambda row: record_type.model_validate_json(row.record_json),
        )
        # Attach the GC reference-count capability so ``count_refs`` resolves it
        # to a single indexed query (the probe pattern; see ``count_refs``).
        catalog.refcount_by_content_hash = _mk_sql_refcount(raw)
        return cls(catalog=catalog, blobs=blobs, on_write=on_write)

    @classmethod
    def from_aws(
        cls,
        bucket_name: str,
        uri: str,
        *,
        record_type: type[BaseModel] = Artifact,
        collection_name: str = "artifact_catalog",
        prefix: str | None = None,
        s3_kwargs: "dict | None" = None,
        sql_kwargs: "dict | None" = None,
        on_write: WritePolicy | None = keep_rights,
    ) -> ArtifactStore:
        """The production pairing: **S3-compatible blobs + SQL catalog**.

        A thin convenience over :meth:`from_s3` (blobs) and :meth:`from_sql`
        (catalog) so the common cloud deployment is one call. The blob store is
        an ``S3Store`` (AWS S3 / Cloudflare R2 / MinIO / Supabase); the catalog
        is the durable, queryable SQL table — Postgres in production, SQLite for
        a smoke test. Vendor specifics live only in the two kwargs dicts.

        Args:
            bucket_name: Object-store bucket for the content-addressed blobs.
            uri: SQLAlchemy URI for the catalog (``postgresql://…`` in prod).
            record_type: Pydantic model the catalog (de)serializes.
            collection_name: SQL table name for the catalog.
            prefix: Optional key prefix within the bucket.
            s3_kwargs: Extra kwargs forwarded to :meth:`from_s3` (credentials,
                ``endpoint_url`` for R2/MinIO/Supabase, ``region_name``, …).
            sql_kwargs: Extra kwargs forwarded to :meth:`from_sql`
                (``content_hash_of``, SQLAlchemy engine kwargs, …).
            on_write: The write policy (see :class:`ArtifactStore`).
        """
        s3_store = cls.from_s3(bucket_name, prefix=prefix, **(s3_kwargs or {}))
        return cls.from_sql(
            uri,
            blobs=s3_store.blobs,
            record_type=record_type,
            collection_name=collection_name,
            on_write=on_write,
            **(sql_kwargs or {}),
        )


def _resolve_within(rootdir: "Path | str", key: str) -> Path | None:
    """Resolve ``rootdir / key``; return it only if it stays inside ``rootdir``.

    Both sides are fully resolved (``..`` segments collapsed, symlinks
    followed), then compared by path *components* via ``Path.parents`` — never
    by string prefix, so a sibling ``<root>-evil`` is not mistaken for being
    inside ``<root>``. An absolute ``key`` (or, on Windows, one with another
    drive) replaces ``rootdir`` in the join and so resolves outside it. The
    root itself is not a blob, so ``key`` resolving *to* ``rootdir`` is
    refused too.

    Returns ``None`` — never raises — for a key the OS cannot even represent
    (an embedded NUL byte) or cannot resolve (a symlink loop): such a key is
    simply not a blob in this store.

    >>> import tempfile
    >>> root = tempfile.mkdtemp()
    >>> _resolve_within(root, "ab" * 32) == Path(root).resolve() / ("ab" * 32)
    True
    >>> _resolve_within(root, "../outside") is None
    True
    >>> _resolve_within(root, "a\\x00b") is None
    True
    """
    try:
        root = Path(rootdir).resolve()
        path = (root / key).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    return path if root in path.parents else None


def _open_within(rootdir: "Path | str", key: str) -> tuple[Path, int] | None:
    """Open blob ``key`` under ``rootdir`` read-only: ``(path, fd)`` or ``None``.

    The one containment gate every filesystem blob read goes through
    (:meth:`ArtifactStore.get_blob`, hence ``iter_blob``; ``has_blob``;
    ``blob_path``, hence ``blob_location``) — lacing#50. It must guard all
    of them, not just ``blob_path``: ``blob_path`` returning ``None`` is the
    documented cue to fall back to ``iter_blob``, and ``dol.Files`` itself
    follows ``..`` segments and symlinks.

    :func:`_resolve_within` alone is a *check*; re-opening the path by name
    afterwards leaves a window in which an entry inside ``rootdir`` can be
    swapped for a symlink to a file outside it (check-then-use race). So the
    resolved, symlink-free path is opened component by component from a
    descriptor on the root, with ``O_NOFOLLOW`` on every step: a component
    swapped for a symlink after the check fails to open instead of being
    followed. The descriptor is then required to be a regular file —
    opened ``O_NONBLOCK`` so a FIFO planted under a blob's name cannot
    hang the reader. Symlinks that stay inside ``rootdir`` still work,
    because they were already resolved away by the check.

    Where the OS lacks ``openat``/``O_NOFOLLOW`` (Windows) the resolved path
    is opened directly: the check still holds, the race window does not
    close. Not addressed, by design: hard links (indistinguishable from the
    blob's own name; creating one needs write access to ``rootdir`` and, on
    Linux with ``fs.protected_hardlinks``, to the target) and bind mounts.
    """
    path = _resolve_within(rootdir, key)
    if path is None:
        return None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)

    def openat_nofollow(root: Path, parts: tuple[str, ...]) -> int:
        dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parts[:-1]:
                next_fd = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=dir_fd
                )
                os.close(dir_fd)
                dir_fd = next_fd
            return os.open(parts[-1], flags | nofollow, dir_fd=dir_fd)
        finally:
            os.close(dir_fd)

    try:
        if nofollow and os.open in os.supports_dir_fd:
            root = Path(rootdir).resolve()
            fd = openat_nofollow(root, path.relative_to(root).parts)
        else:
            fd = os.open(path, flags)
    except (OSError, ValueError):
        return None
    try:
        if stat.S_ISREG(os.fstat(fd).st_mode):
            return path, fd
    except OSError:
        pass
    os.close(fd)
    return None


def _iter_within(rootdir: "Path | str") -> Iterator[str]:
    """Yield the relative key of every file :func:`_open_within` would open.

    Walks ``rootdir`` without following symlinked directories and skips
    hidden entries (as ``dol.Files`` does). A plain regular file met on that
    walk is physically inside the root and is yielded as is; a symlink is
    yielded only if it passes the same gate every read goes through, so a
    listing never names a file the store would then refuse to read, and a
    symlink cycle cannot loop it. Keys use the OS separator, like
    ``dol.Files``' relative keys, and come out sorted per directory.
    """
    root = Path(rootdir)

    def walk(relative_dir: str) -> Iterator[str]:
        try:
            with os.scandir(root / relative_dir) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            key = os.path.join(relative_dir, entry.name) if relative_dir else entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    yield from walk(key)
                elif entry.is_file(follow_symlinks=False):
                    yield key
                elif entry.is_symlink():
                    opened = _open_within(root, key)
                    if opened is not None:
                        os.close(opened[1])
                        yield key
            except OSError:
                continue

    return walk("")


class _ContainedDirStore(MutableMapping):
    """A ``dol.Files``-like store whose keys cannot leave its ``rootdir``.

    ``dol.Files`` joins keys onto its root by string and follows ``..`` and
    symlinks, so a key is a path anywhere on disk. This wrapper routes every
    key through the containment seam of the blob reads (lacing#50/#55).
    A key is accepted only if (see :meth:`_contained_key`):

    - it has no ``..`` segment — refused outright rather than normalised, so
      ``"x/../b"`` can never alias record ``b``;
    - it is relative (no absolute path, no drive) and :func:`_resolve_within`
      keeps it inside ``rootdir`` — which refuses NUL bytes and symlinks
      pointing out; and
    - its parent directory resolves inside ``rootdir`` too, so acting on the
      final *name* (a delete never follows it) cannot land outside.

    Reads go through :func:`_open_within`, the same descriptor-based,
    ``O_NOFOLLOW`` read as :meth:`ArtifactStore.get_blob`. Writes and
    deletes are delegated to the wrapped store on the (normalised) key the
    caller gave, so its write and delete policy (e.g. trash on delete) is
    unchanged, and deleting an in-root symlink removes the link, not its
    target. Writing over something that is not a regular file (a FIFO would
    hang the writer) is refused. Listing is :func:`_iter_within`: no
    symlinked directories followed.

    A refused key raises ``KeyError`` on get/set/del and is not ``in`` the
    store. Writes are checked by name, then opened by name by the wrapped
    store: a party that can already write inside ``rootdir`` could race a
    symlink in between. That is the same point-in-time caveat as
    :meth:`ArtifactStore.blob_path`; keys from outside the store cannot open
    it.

    >>> import tempfile
    >>> store = _ContainedDirStore(Files(tempfile.mkdtemp()))
    >>> store["a.json"] = b"{}"
    >>> list(store), "a.json" in store, "../a.json" in store
    (['a.json'], True, False)
    >>> store["../../escaped.json"] = b"{}"
    Traceback (most recent call last):
    ...
    KeyError: "'../../escaped.json' does not resolve inside the store root"
    """

    def __init__(self, store: MutableMapping) -> None:
        self.store = store
        self.rootdir = store.rootdir

    def _contained_key(self, key: object) -> str | None:
        """``key`` normalised, if it names an entry inside ``rootdir``; else None."""
        if not isinstance(key, str) or os.path.isabs(key) or os.path.splitdrive(key)[0]:
            return None
        separators = {"/", os.sep, os.altsep} - {None}
        if key.endswith(tuple(separators)):
            return None  # names a directory, never an entry
        segments = [key]
        for separator in separators:
            segments = [part for seg in segments for part in seg.split(separator)]
        if ".." in segments or _resolve_within(self.rootdir, key) is None:
            return None
        normalised = os.path.normpath(key)
        parent = os.path.dirname(normalised)
        if parent and _resolve_within(self.rootdir, parent) is None:
            return None
        return normalised

    def _refuse(
        self, key: object, reason: str = "does not resolve inside the store root"
    ) -> KeyError:
        return KeyError(f"{key!r} {reason}")

    def __getitem__(self, key: str) -> bytes:
        contained = self._contained_key(key)
        opened = None if contained is None else _open_within(self.rootdir, contained)
        if opened is None:
            raise KeyError(key)
        with os.fdopen(opened[1], "rb") as file:
            return file.read()

    def __setitem__(self, key: str, value: bytes) -> None:
        contained = self._contained_key(key)
        if contained is None:
            raise self._refuse(key)
        target = _resolve_within(self.rootdir, contained)
        if target is None:
            raise self._refuse(key)
        try:
            is_regular = stat.S_ISREG(os.stat(target).st_mode)
        except FileNotFoundError:
            is_regular = True  # nothing there yet: a plain create
        except OSError as error:  # e.g. a name too long for the filesystem
            raise self._refuse(key, f"cannot be written ({error})") from error
        if not is_regular:
            raise self._refuse(key, "names something that is not a regular file")
        # dol's Files does not create parent directories; ``target`` is already
        # resolved inside rootdir, so creating its parents cannot escape.
        created = _missing_parents(Path(target))
        try:
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            self.store[contained] = value
        except (OSError, KeyError) as error:  # dol re-raises I/O errors as KeyError
            for directory in created:  # deepest first; only what this call made
                try:
                    directory.rmdir()
                except OSError:
                    continue  # never made (e.g. name too long), or not empty
            raise self._refuse(key, f"cannot be written ({error})") from error

    def __delitem__(self, key: str) -> None:
        if key not in self:
            raise KeyError(key)
        del self.store[self._contained_key(key)]

    def __contains__(self, key: object) -> bool:
        contained = self._contained_key(key)
        if contained is None:
            return False
        opened = _open_within(self.rootdir, contained)
        if opened is None:
            return False
        os.close(opened[1])
        return True

    def __iter__(self) -> Iterator[str]:
        return _iter_within(self.rootdir)

    def __len__(self) -> int:
        return sum(1 for _ in self)


def _catalog_filename(artifact_id: str) -> str:
    """``<id>.json``; an id ending in a separator names a directory: ``KeyError``."""
    if artifact_id.endswith(("/", os.sep)):
        raise KeyError(f"{artifact_id!r} names a directory, not an artifact")
    return f"{artifact_id}.json"


def _missing_parents(path: Path) -> list[Path]:
    """The ancestors of ``path`` that do not exist yet, deepest first."""
    missing = []
    for parent in path.parents:
        if parent.exists():
            break
        missing.append(parent)
    return missing


def _spool_chunks_to_dir(chunks: Iterable[bytes], rootdir: Path) -> str:
    """Hash-while-spooling to a same-directory tempfile, then atomic rename.

    The same-directory part is load-bearing twice: ``os.replace`` is only
    atomic within a filesystem, and a content-addressed name must not exist
    until the content behind it is complete — a reader that finds the hash
    finds the whole blob, never a prefix of it (lacing#25).
    """
    import tempfile

    rootdir.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    fd, tmp_path = tempfile.mkstemp(dir=rootdir, prefix=".blob-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as spool:
            for chunk in chunks:
                hasher.update(chunk)
                spool.write(chunk)
        content_hash = hasher.hexdigest()
        os.replace(tmp_path, rootdir / content_hash)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return content_hash
