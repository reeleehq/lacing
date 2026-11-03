# lacing.exhibit

Artifact exhibit — render an annotation graph as a readable document.

Walks a set of [`Annotation`](lacing.html.md#lacing.Annotation)s and lays them out as a
document: each artifact is a card with its body, any generated images,
and **in-document hyperlinks** to the artifacts it was derived from and
the ones it feeds into.

Images are written once as content-addressed sibling files under an
`images/` directory and referenced relatively, so the HTML and
Markdown stay small. The PDF is still self-contained — weasyprint
resolves the relative paths (via `base_url`) and embeds the bytes.

The annotation graph — annotations + `provenance.was_derived_from` +
image references — *is* the “artifacts and links” model (`edges=`
adds other links, such as `AnnotationRef` targets; `label=` sets card
titles), so this runs on **any** lacing graph: a project, a test run’s
artifacts, anything. The renderer is pure (graph → document) and has no knowledge of where the
graph came from.

HTML is the authored format; the PDF and Markdown derive from it so the
three never drift:

- **PDF** via `weasyprint` — chosen over wkhtmltopdf because it is the
  HTML→PDF engine that carries the in-document anchor links through to
  **clickable PDF links** (wkhtmltopdf renders them as broken external
  URIs).
- **Markdown** via `dn.html_to_markdown`.

Both derivations are optional — `pip install lacing[exhibit]`. A
missing converter raises an informative error naming the install
command, rather than silently dropping the format.

Images are resolved through an injected `image_resolver` callback
(image-reference → local file path) so this module needs no knowledge
of how media is stored or downloaded — the caller wires that in.

### Module Attributes

| [`DEFAULT_LABEL_FIELDS`](#lacing.exhibit.DEFAULT_LABEL_FIELDS)   | The body fields [`default_label`](#lacing.exhibit.default_label) tries, in order.                                                                            |
|-------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`default_label`](#lacing.exhibit.default_label)(ann)     | The default `label=`: the first of [`DEFAULT_LABEL_FIELDS`](#lacing.exhibit.DEFAULT_LABEL_FIELDS) set.                                                              |
| [`DERIVED_FROM`](#lacing.exhibit.DERIVED_FROM)           | `provenance.was_derived_from` (the default `edges=`).                                                                                                                      |
| [`ANNOTATES`](#lacing.exhibit.ANNOTATES)              | the annotation an `AnnotationRef` points at (a note on a line, a referent annotating an entity), found as the reference's `target_id` (any reference that has one counts). |

### Functions

| [`default_label`](#lacing.exhibit.default_label)(ann)                                | The default `label=`: the first of [`DEFAULT_LABEL_FIELDS`](#lacing.exhibit.DEFAULT_LABEL_FIELDS) set.                                                                                              |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`label_from_fields`](#lacing.exhibit.label_from_fields)(\*fields)                       | A `label=` for [`render_artifact_exhibit()`](#lacing.exhibit.render_artifact_exhibit): the first of the body `fields` holding a non-blank string, else `None` (the card is then labelled by its kind). |
| [`render_artifact_exhibit`](#lacing.exhibit.render_artifact_exhibit)(annotations, \*, out_dir) | Render an annotation graph as a human-readable artifact exhibit.                                                                                                                                           |

### Classes

| [`ExhibitEdge`](#lacing.exhibit.ExhibitEdge)(targets, forward, backward)   | One kind of link between exhibit cards (an `edges=` strategy).   |
|--------------------------------------------------------------------------------------------|------------------------------------------------------------------|

### lacing.exhibit.ANNOTATES *= ExhibitEdge(targets=<function \_annotation_ref_targets>, forward='annotates', backward='annotated by')*

the annotation an `AnnotationRef` points at (a note on a line,
a referent annotating an entity), found as the reference’s `target_id`
(any reference that has one counts). `edges=(DERIVED_FROM, ANNOTATES)` shows
both, each under its own name, without touching provenance.

* **Type:**
  [*Reference*](lacing.model.html.md#lacing.model.Reference)

### lacing.exhibit.DEFAULT_LABEL_FIELDS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('caption', 'logline', 'description', 'name', 'panel_id', 'beat_id', 'label', 'kind')*

The body fields [`default_label`](#lacing.exhibit.default_label) tries, in order.

### lacing.exhibit.DERIVED_FROM *= ExhibitEdge(targets=<function \_derived_from_targets>, forward='derived from', backward='feeds into')*

`provenance.was_derived_from` (the default `edges=`).

* **Type:**
  [*Provenance*](lacing.html.md#lacing.Provenance)

### *class* lacing.exhibit.ExhibitEdge(targets, forward, backward)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One kind of link between exhibit cards (an `edges=` strategy).

`targets(ann)` gives the ids `ann` links to. Its card lists them
under `↑ <forward>`, and each target’s card lists `ann` under
`↓ <backward>`. An id that is not among the exhibited annotations is
shown as a short id, not a link.

### lacing.exhibit.default_label(ann)

The default `label=`: the first of [`DEFAULT_LABEL_FIELDS`](#lacing.exhibit.DEFAULT_LABEL_FIELDS) set.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### lacing.exhibit.label_from_fields(\*fields)

A `label=` for [`render_artifact_exhibit()`](#lacing.exhibit.render_artifact_exhibit): the first of the body
`fields` holding a non-blank string, else `None` (the card is then
labelled by its kind).

```pycon
>>> from types import SimpleNamespace
>>> label = label_from_fields("title", "text")
>>> label(SimpleNamespace(body={"text": "a line", "title": " "}))
'a line'
>>> label(SimpleNamespace(body={})) is None
True
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### lacing.exhibit.render_artifact_exhibit(annotations, \*, out_dir, formats=('html', 'pdf', 'md'), title='Artifact exhibit', image_resolver=None, label=<function label_from_fields.<locals>.label>, edges=(ExhibitEdge(targets=<function \_derived_from_targets>, forward='derived from', backward='feeds into'), ))

Render an annotation graph as a human-readable artifact exhibit.

Lays every annotation out as a card — body, panel images, and
in-document hyperlinks to the artifacts it derives from / feeds
into. **HTML is authored**; the PDF and Markdown derive from it.

Panel images are written once as content-addressed sibling files
under `<out_dir>/images/` and referenced relatively, so the HTML
and Markdown stay small; the PDF embeds them and stays a single
self-contained file. The `images/` directory is created only when
the graph actually has images.

* **Parameters:**
  * **annotations** ([`Iterable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterable)) – the lacing annotations to exhibit (any iterable).
    Order is preserved — pass them chain-ordered for a document
    that reads top-to-bottom.
  * **out_dir** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)) – directory the `exhibit.{html,pdf,md}` files land in.
  * **formats** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – which of `html` / `pdf` / `md` to write. The HTML
    is always built in memory (the others derive from it).
  * **title** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – document title.
  * **image_resolver** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – `image-reference → local file path` callback.
    Defaults to reading the reference’s own `path` field; a
    caller whose images live behind URLs passes a resolver that
    downloads / caches them (keeping this module media-agnostic).
  * **label** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `annotation → card title` (`None` or blank: the card is
    titled by its kind; long titles are cut). Defaults to the first
    of [`DEFAULT_LABEL_FIELDS`](#lacing.exhibit.DEFAULT_LABEL_FIELDS) in the body; a graph whose text
    lives elsewhere passes `label_from_fields("title", "text")` or
    any function.
  * **edges** ([`Iterable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterable)[[`ExhibitEdge`](#lacing.exhibit.ExhibitEdge)]) – which links to draw, as [`ExhibitEdge`](#lacing.exhibit.ExhibitEdge) strategies, in
    order. Defaults to provenance ([`DERIVED_FROM`](#lacing.exhibit.DERIVED_FROM)); add
    [`ANNOTATES`](#lacing.exhibit.ANNOTATES) for `AnnotationRef` links, or define your own.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]
* **Returns:**
  The written file paths.
* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – when `pdf` / `md` is requested but its optional
      converter (`weasyprint` / `dn`) is not installed — the
      message names the install command.
