# lacing.adapters

I/O adapter registry.

The core never imports a format module. Each adapter registers itself by
calling [`register_adapter()`](#lacing.adapters.register_adapter) at import time. Users opt in by importing
the adapter module:

> from lacing.adapters import textgrid  # noqa: F401  — registers itself

Or by using the convenience top-level loaders that look up by extension or
`media_type`.

### Functions

| [`adapter_generator_id`](#lacing.adapters.adapter_generator_id)(name[, version])         | The `was_generated_by` of what adapter `name` at `version` imports.                                         |
|------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| [`dump`](#lacing.adapters.dump)(store[, target])                         | Convenience: serialize `store` via the named adapter.                                                       |
| [`find_adapter`](#lacing.adapters.find_adapter)(\*[, extension, media_type])     | Find an adapter by extension (case-insensitive) or media type.                                              |
| [`find_adapter_for_path`](#lacing.adapters.find_adapter_for_path)(path)                   | Find an adapter by the extension of `path`, longest suffix first.                                           |
| [`get_adapter`](#lacing.adapters.get_adapter)(name)                             | Look up an adapter by name.                                                                                 |
| [`load`](#lacing.adapters.load)(source, \*[, format])                    | Convenience: dispatch `source` to the right adapter.                                                        |
| [`register_adapter`](#lacing.adapters.register_adapter)(\*, name, load, dump[, ...]) | Register an adapter under `name`; returns its [`AdapterSpec`](#lacing.adapters.AdapterSpec). |
| [`registered`](#lacing.adapters.registered)()                                  | All currently registered adapters (in registration order).                                                  |

### Classes

| [`AdapterSpec`](#lacing.adapters.AdapterSpec)(name, extensions, media_types, ...)   | Registered adapter for one format.   |
|----------------------------------------------------------------------------------------------------|--------------------------------------|

### *class* lacing.adapters.AdapterSpec(name, extensions, media_types, load, dump, body_schema_uris=tuple(), description='', version=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Registered adapter for one format.

`version` (semver) is the vintage of the adapter’s output shape: bump it
when what the adapter produces changes, so provenance can tell which
vintage produced an annotation.

#### *property* generator_id *: [GeneratorId](lacing.generator_id.html.md#lacing.generator_id.GeneratorId)*

`adapter:<name>[@<version>]`.

* **Type:**
  The provenance id of this adapter

### lacing.adapters.adapter_generator_id(name, version=None)

The `was_generated_by` of what adapter `name` at `version` imports.

```pycon
>>> str(adapter_generator_id("textgrid", "1.0.0"))
'adapter:textgrid@1.0.0'
>>> str(adapter_generator_id("textgrid"))
'adapter:textgrid'
```

* **Return type:**
  [`GeneratorId`](lacing.generator_id.html.md#lacing.generator_id.GeneratorId)

### lacing.adapters.dump(store, target=None, , format, \*\*kwargs)

Convenience: serialize `store` via the named adapter.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.find_adapter(, extension=None, media_type=None)

Find an adapter by extension (case-insensitive) or media type.

* **Return type:**
  [`AdapterSpec`](#lacing.adapters.AdapterSpec) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.find_adapter_for_path(path)

Find an adapter by the extension of `path`, longest suffix first.

A compound extension (`ep.chapters.json`, `task.labelstudio.json`)
is tried before its last part (`.json`), so a format registered under
`.chapters.json` wins over one registered under `.json`.

```pycon
>>> find_adapter_for_path("no_extension") is None
True
```

* **Return type:**
  [`AdapterSpec`](#lacing.adapters.AdapterSpec) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.get_adapter(name)

Look up an adapter by name. Raises `KeyError` if missing.

* **Return type:**
  [`AdapterSpec`](#lacing.adapters.AdapterSpec)

### lacing.adapters.load(source, , format=None, \*\*kwargs)

Convenience: dispatch `source` to the right adapter.

If `format` is given, looks up by name. Otherwise, if `source` is a
path, infers from extension. Raises `ValueError` if it can’t pick.

* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)

### lacing.adapters.register_adapter(, name, load, dump, extensions=(), media_types=(), body_schema_uris=(), description='', version=None, force=False)

Register an adapter under `name`; returns its [`AdapterSpec`](#lacing.adapters.AdapterSpec).

Re-registering an equal spec is a no-op. A different spec under a taken
name warns ([`lacing.RegistryConflictWarning`](lacing.html.md#lacing.RegistryConflictWarning)) and replaces, unless
`force` (see [`lacing.registry`](lacing.registry.html.md#module-lacing.registry)).

* **Return type:**
  [`AdapterSpec`](#lacing.adapters.AdapterSpec)

### lacing.adapters.registered()

All currently registered adapters (in registration order).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`AdapterSpec`](#lacing.adapters.AdapterSpec)]

### Modules

| [`annot`](lacing.adapters.annot.html.md#module-lacing.adapters.annot)                           | `.annot` portable file format adapter.                                    |
|---------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`eaf`](lacing.adapters.eaf.html.md#module-lacing.adapters.eaf)                               | ELAN EAF adapter (Max Planck Institute's annotation tool format).         |
| [`jams`](lacing.adapters.jams.html.md#module-lacing.adapters.jams)                             | JAMS (JSON Annotated Music Specification) adapter.                        |
| [`label_studio`](lacing.adapters.label_studio.html.md#module-lacing.adapters.label_studio)             | Label Studio JSON adapter.                                                |
| [`lrc`](lacing.adapters.lrc.html.md#module-lacing.adapters.lrc)                               | LRC (`.lrc`) lyrics adapter: plain LRC and enhanced LRC with word timing. |
| [`otio`](lacing.adapters.otio.html.md#module-lacing.adapters.otio)                             | OpenTimelineIO (OTIO) adapter — NLE / video editing interchange.          |
| [`podcast_chapters`](lacing.adapters.podcast_chapters.html.md#module-lacing.adapters.podcast_chapters)     | Podcasting 2.0 `podcast:chapters` JSON adapter.                           |
| [`podcast_transcript`](lacing.adapters.podcast_transcript.html.md#module-lacing.adapters.podcast_transcript) | Podcasting 2.0 `podcast:transcript` JSON adapter.                         |
| [`srt`](lacing.adapters.srt.html.md#module-lacing.adapters.srt)                               | SubRip (`.srt`) adapter.                                                  |
| [`textgrid`](lacing.adapters.textgrid.html.md#module-lacing.adapters.textgrid)                     | Praat TextGrid adapter.                                                   |
| [`web_annotation`](lacing.adapters.web_annotation.html.md#module-lacing.adapters.web_annotation)         | W3C Web Annotation Data Model adapter (JSON-LD).                          |
| [`webvtt`](lacing.adapters.webvtt.html.md#module-lacing.adapters.webvtt)                         | WebVTT (W3C TimedText) adapter.                                           |
