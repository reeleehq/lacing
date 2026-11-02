# lacing.generator_id

The grammar of `Provenance.was_generated_by`, and an advisory check of it.

A generator identifier names the activity that produced an annotation or
artifact:

```default
<prefix>:<name>[@<version>]
```

`prefix` is lower-case kebab (`user`, `agent`, `adapter` …), `name`
is anything without whitespace or `@` (model names carry `/` and `.`), and
`version`, after the one `@`, is what pins the generator: a weights or
version digest, a dated snapshot, or a probe digest. For `agent:` it is the
slot a model-drift defence depends on (lacing#17), so the convention asks for it.

`@` is reserved: it is the version separator under every prefix, so a name
never contains one. `user:a@b.com` parses as name `a`, version `b.com`;
a handle that is an e-mail address has to be written without its `@`.

The check is **advisory** (lacing#17): writers already in production disagree
with the documented convention (`agent:` with no `@`, an application slug in
the `@` slot, prefixes nobody documented), and real data has to show the
census before anything starts rejecting. So:

- a value that is not of the `<prefix>:<name>[@<version>]` shape at all makes
  [`lacing.Provenance`](lacing.html.md#lacing.Provenance) emit a [`GeneratorIdWarning`](#lacing.generator_id.GeneratorIdWarning) at construction.

  Escalate it to an error with the warnings filter
  (`-W error::lacing.GeneratorIdWarning`), silence it the same way. Escalating
  also rejects *reads* of legacy rows, since the stores rebuild a `Provenance`
  on every read: it is a census tool, not a write gate;
- the convention-level findings (an undocumented prefix, an `agent:` without a
  version) are only reported by [`generator_id_findings()`](#lacing.generator_id.generator_id_findings), for a census:
  ```default
  Counter(f for a in annotations
          for f in generator_id_findings(a.provenance.was_generated_by))
  ```

Whether the `@` slot holds a digest or a slug cannot be told from the string
(a dated snapshot is neither hex nor a slug), so it is not checked here.

### Module Attributes

| [`GENERATOR_ID_SHAPE`](#lacing.generator_id.GENERATOR_ID_SHAPE)   | The shape every `was_generated_by` is checked against.   |
|-----------------------------------------------------------------------|----------------------------------------------------------|
| [`GENERATOR_PREFIXES`](#lacing.generator_id.GENERATOR_PREFIXES)   | The documented prefixes, each with what follows it.      |
| [`VERSIONED_PREFIXES`](#lacing.generator_id.VERSIONED_PREFIXES)   | Prefixes whose convention asks for an `@<version>`.      |

### Functions

| [`parse_generator_id`](#lacing.generator_id.parse_generator_id)(value)                         | Parse `value`, or return `None` when it is not of the generator-id shape.                                                                                                        |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`generator_id_findings`](#lacing.generator_id.generator_id_findings)(value, \*[, prefixes, ...]) | What `value` does differently from the documented convention; empty if nothing.                                                                                                  |
| [`warn_if_malformed`](#lacing.generator_id.warn_if_malformed)(value)                          | Emit a [`GeneratorIdWarning`](#lacing.generator_id.GeneratorIdWarning), pointed at the caller outside lacing, when `value` is not of the generator-id shape; return `value`. |

### Classes

| [`GeneratorId`](#lacing.generator_id.GeneratorId)(prefix, name[, version])   | A parsed `was_generated_by`: `<prefix>:<name>[@<version>]`.   |
|-----------------------------------------------------------------------------------------|---------------------------------------------------------------|

### Exceptions

| [`GeneratorIdWarning`](#lacing.generator_id.GeneratorIdWarning)   | A `was_generated_by` that is not of the `<prefix>:<name>[@<version>]` shape.   |
|-----------------------------------------------------------------------|--------------------------------------------------------------------------------|

### lacing.generator_id.GENERATOR_ID_SHAPE *= '<prefix>:<name>[@<version>]'*

The shape every `was_generated_by` is checked against.

### lacing.generator_id.GENERATOR_PREFIXES *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {'adapter': 'an import/export format adapter: \`\`adapter:<format>@<version>\`\`', 'agent': 'a model or service: \`\`agent:<model>@<version digest or snapshot>\`\`', 'fetch': 'a retrieval from an external source: \`\`fetch:<source>\`\`', 'processor': 'a lacing processor: \`\`processor:<name>\`\`', 'server': 'a server-side operation: \`\`server:<service>\`\`', 'transform': 'a pipeline transform: \`\`transform:<name>@<version>\`\`', 'user': 'a person acting through a UI or API: \`\`user:<handle>\`\`'}*

The documented prefixes, each with what follows it. `transform`, `server`
and `fetch` were in production before they were documented (lacing#17).

### *class* lacing.generator_id.GeneratorId(prefix, name, version=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A parsed `was_generated_by`: `<prefix>:<name>[@<version>]`.

### *exception* lacing.generator_id.GeneratorIdWarning

Bases: [`UserWarning`](https://docs.python.org/3/builtins/exceptions.html#UserWarning)

A `was_generated_by` that is not of the `<prefix>:<name>[@<version>]` shape.

### lacing.generator_id.VERSIONED_PREFIXES *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= frozenset({'agent'})*

Prefixes whose convention asks for an `@<version>`.

### lacing.generator_id.generator_id_findings(value, , prefixes={'adapter': 'an import/export format adapter: \`\`adapter:<format>@<version>\`\`', 'agent': 'a model or service: \`\`agent:<model>@<version digest or snapshot>\`\`', 'fetch': 'a retrieval from an external source: \`\`fetch:<source>\`\`', 'processor': 'a lacing processor: \`\`processor:<name>\`\`', 'server': 'a server-side operation: \`\`server:<service>\`\`', 'transform': 'a pipeline transform: \`\`transform:<name>@<version>\`\`', 'user': 'a person acting through a UI or API: \`\`user:<handle>\`\`'}, versioned=frozenset({'agent'}))

What `value` does differently from the documented convention; empty if nothing.

Advisory: nothing here rejects. `prefixes` is the set of known prefixes and
`versioned` the ones that ask for an `@<version>`; pass your own to check
against a wider or stricter convention.

```pycon
>>> generator_id_findings("agent:flux@sha256:9f2c")
[]
>>> generator_id_findings("agent:nw.graph")
["prefix 'agent' expects an @<version>"]
>>> generator_id_findings("test:doctest")
["undocumented prefix 'test'"]
>>> generator_id_findings("t")
["not of the shape '<prefix>:<name>[@<version>]'"]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### lacing.generator_id.parse_generator_id(value)

Parse `value`, or return `None` when it is not of the generator-id shape.

```pycon
>>> parse_generator_id("agent:fal-ai/flux@sha256:9f2c")
GeneratorId(prefix='agent', name='fal-ai/flux', version='sha256:9f2c')
>>> parse_generator_id("adapter:textgrid")
GeneratorId(prefix='adapter', name='textgrid', version=None)
>>> parse_generator_id("thor") is None
True
```

* **Return type:**
  [`GeneratorId`](#lacing.generator_id.GeneratorId) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.generator_id.warn_if_malformed(value)

Emit a [`GeneratorIdWarning`](#lacing.generator_id.GeneratorIdWarning), pointed at the caller outside lacing,
when `value` is not of the generator-id shape; return `value`.

The advisory check [`lacing.Provenance`](lacing.html.md#lacing.Provenance) runs on `was_generated_by`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
