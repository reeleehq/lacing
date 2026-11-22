# lacing.store.memory

In-memory annotation store backed by an interval tree.

Uses `intervaltree` (Apache-2.0). Annotations whose reference is not a
`MediaRef` (i.e., they have no time interval) are kept in a separate
list — they can still be enumerated via `all()` / `by_tier` but
won’t appear in interval queries.

### Classes

| [`MemoryStore`](#lacing.store.memory.MemoryStore)()   | `IntervalAnnotationStore` implementation over `intervaltree`.   |
|------------------------------------------------------------------|-----------------------------------------------------------------|

### *class* lacing.store.memory.MemoryStore

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`IntervalAnnotationStore` implementation over `intervaltree`.

Conforms to the protocol in `lacing.store.base`. We don’t formally
inherit from `IntervalAnnotationStore` because it’s a `Protocol`
with method bodies — structural typing is enough.

#### add(annotation)

Add an annotation to the store.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### add_tier(tier)

Register a tier.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### all()

Iterate over every annotation in the store.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### at_tier(tier_name, query)

Yield annotations of one tier that intersect the query interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### by_tier(tier_name)

Iterate over the annotations of one tier.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### contains(query)

Yield annotations that contain the query interval (Allen `contains`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### during(query)

Yield annotations lying strictly during the query interval (Allen `during`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### equals(query)

Yield annotations whose interval equals the query interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### extend(annotations)

Add several annotations at once.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### finishes(query)

Yield annotations that finish with the query interval but start later (Allen `finishes`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### get_tier(name)

Return the tier with the given name, or `None`.

* **Return type:**
  [`Tier`](lacing.tier.html.md#lacing.tier.Tier) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### intersects(query)

Yield annotations whose interval intersects the query interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### lock(key)

Exclusive lock named `key` among the threads of this process.

* **Return type:**
  [`AbstractContextManager`](https://docs.python.org/3/library/contextlib.html#contextlib.AbstractContextManager)[[`None`](https://docs.python.org/3/builtins/constants.html#None)]

#### meets(query)

Yield annotations that end exactly where the query interval starts (Allen `meets`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### overlaps(query)

Yield annotations that overlap the start of the query interval (Allen `overlaps`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### relate(query, relations)

Yield annotations standing in the given Allen relation to the query interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### remove(annotation_id)

Remove the annotation with the given id; return it, or `None` if absent.

* **Return type:**
  [`Annotation`](lacing.model.html.md#lacing.model.Annotation) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### starts(query)

Yield annotations that start with the query interval but end earlier (Allen `starts`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### tiers()

Return the registered tiers.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Tier`](lacing.tier.html.md#lacing.tier.Tier)]

#### update(annotation)

Replace the stored annotation that has the same id.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
