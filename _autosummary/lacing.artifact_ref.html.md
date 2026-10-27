# lacing.artifact_ref

One spelling for a reference to an artifact: `artifact:[<store>/]<key>[@<sha256>]`.

Consumers of [`lacing.ArtifactStore`](lacing.html.md#lacing.ArtifactStore) hand references to artifacts across
process and tool boundaries (an records them in a take’s provenance; reelee’s
MCP tools return them). [`ArtifactRef`](#lacing.artifact_ref.ArtifactRef) is the one parser and formatter for
that text, so the spelling cannot drift between them (lacing#90):

- `<key>` is the id the artifact is filed under in its store’s catalog.
- `<store>/`, optional, names the store within a *mall* (a mapping of store
  names to stores). The text alone cannot tell `takes/a` (key `a` of store
  `takes`) from a key `takes/a`, so [`ArtifactRef.parse()`](#lacing.artifact_ref.ArtifactRef.parse) keeps the
  whole name as the key and [`ArtifactRef.locate()`](#lacing.artifact_ref.ArtifactRef.locate) splits it against a mall.
- `@<sha256>`, optional, pins the content: a pinned reference names those
  bytes, even after the key is re-saved with other content.

[`lacing.ArtifactStore.resolve()`](lacing.html.md#lacing.ArtifactStore.resolve) reads what a reference names in one store;
[`lacing.resolve_in_mall()`](lacing.html.md#lacing.resolve_in_mall) locates its store in a mall first.

The syntax has one ambiguity no parser can remove: an unlocated
`artifact:takes/a` names key `a` of store `takes` today, but key
`takes/a` of the default store once that store gains such a key.

Differences from an’s `parse_artifact_ref` (for its adoption):

- `artifact:takes/` (an empty rest) and `artifact:takes//a` (a rest that is
  not a key) go to the default store with the whole name as key.
- Text without the `artifact:` prefix raises `ValueError`; an sliced the
  prefix’s length off whatever it was given.
- `artifact: x` (a space after the prefix) is refused; reelee’s lenient strip
  of such text stays in reelee.

```pycon
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
```

### Functions

| [`is_artifact_ref`](#lacing.artifact_ref.is_artifact_ref)(text)   | Whether [`ArtifactRef.parse()`](#lacing.artifact_ref.ArtifactRef.parse) accepts `text` (surrounding space ignored); `False` for anything that is not a `str`.   |
|--------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### Classes

| [`ArtifactRef`](#lacing.artifact_ref.ArtifactRef)(key[, store, pin])   | A reference to an artifact: its `key`, the `store` that files it when known, and the content `pin` when it names one: the store's content hash, 64 hex digits of SHA-256 (an `Artifact.asset_id`), kept lowercase.   |
|-----------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### *class* lacing.artifact_ref.ArtifactRef(key, store=None, pin=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A reference to an artifact: its `key`, the `store` that files it when
known, and the content `pin` when it names one: the store’s content hash,
64 hex digits of SHA-256 (an `Artifact.asset_id`), kept lowercase.

Raises `ValueError` for a reference that would not read back as itself: an
empty key or one with whitespace, a key starting with `/` or ending in
`@<sha256>`, a store with `/` in it, or a pin that is not 64 hex digits.

#### format()

The reference as text: `artifact:[<store>/]<key>[@<pin>]`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### locate(mall, , default_store)

This reference with its `store` decided against `mall`.

A `store` already set is kept. Otherwise the key’s first segment names
a store of `mall` when the rest is itself a key (so `takes/` and
`takes//a` stay whole) and that store holds it, or when
`default_store` does not hold the whole key (so a pinned reference
whose key was since deleted still finds its store); else the whole key
belongs to `default_store`.

```pycon
>>> mall = {"transcripts": {}, "takes": {"a": 1}}
>>> ArtifactRef.parse("artifact:takes/a").locate(mall, default_store="transcripts")
ArtifactRef(key='a', store='takes', pin=None)
>>> ArtifactRef.parse("artifact:k").locate(mall, default_store="transcripts")
ArtifactRef(key='k', store='transcripts', pin=None)
```

* **Return type:**
  [`ArtifactRef`](#lacing.artifact_ref.ArtifactRef)

#### *classmethod* parse(text, , require_prefix=True)

The reference `text` spells, with the whole name as `key`
(`store` is `None`; see [`locate()`](#lacing.artifact_ref.ArtifactRef.locate)).

`require_prefix=False` also reads a name without `artifact:`, the
`<store>/<key>@<sha256>` that an records in a take’s manifest.

Anything it refuses raises `ValueError("not an artifact reference: ...")`,
chained to the key’s own error when that is the reason.

```pycon
>>> ArtifactRef.parse("  artifact:k  ")
ArtifactRef(key='k', store=None, pin=None)
>>> ArtifactRef.parse("take.srt")
Traceback (most recent call last):
...
ValueError: not an artifact reference: 'take.srt'
>>> ArtifactRef.parse("takes/a", require_prefix=False)
ArtifactRef(key='takes/a', store=None, pin=None)
```

* **Return type:**
  [`ArtifactRef`](#lacing.artifact_ref.ArtifactRef)

### lacing.artifact_ref.is_artifact_ref(text)

Whether [`ArtifactRef.parse()`](#lacing.artifact_ref.ArtifactRef.parse) accepts `text` (surrounding space
ignored); `False` for anything that is not a `str`.

```pycon
>>> is_artifact_ref("artifact:transcripts/t"), is_artifact_ref("take.srt")
(True, False)
>>> is_artifact_ref("artifact: Hello there.")
False
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
