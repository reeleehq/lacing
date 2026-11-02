# lacing.quality

Inter-annotator agreement and boundary metrics.

Phase 0 ships four metrics from ANN-DOC §D, all as pure functions:

- [`cohen_kappa()`](#lacing.quality.cohen_kappa) — agreement between two annotators on a categorical label.
- [`krippendorff_alpha()`](#lacing.quality.krippendorff_alpha) — agreement across any number of annotators
  (handles missing data, multiple distance metrics).
- [`interval_iou()`](#lacing.quality.interval_iou) — Intersection-over-Union for two time intervals.
- [`boundary_iou()`](#lacing.quality.boundary_iou) — Average IoU between two sets of intervals (greedy match).

The doc cites Krippendorff thresholds: α > 0.8 reliable, 0.67–0.8 tentative,
< 0.67 discard. Kappa traditionally: >0.8 almost perfect, 0.6–0.8 substantial,
0.4–0.6 moderate.

Pure functions — no numpy dependency in Phase 0.

### Functions

| [`boundary_iou`](#lacing.quality.boundary_iou)(a, b)                              | Mean IoU between two sets of intervals via greedy best-match.   |
|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| [`cohen_kappa`](#lacing.quality.cohen_kappa)(a, b)                               | Cohen's kappa for two annotators on a categorical label.        |
| [`interval_iou`](#lacing.quality.interval_iou)(a, b)                              | Intersection-over-Union for two time intervals.                 |
| [`krippendorff_alpha`](#lacing.quality.krippendorff_alpha)(annotations, \*[, distance]) | Krippendorff's α across any number of annotators.               |

### lacing.quality.boundary_iou(a, b)

Mean IoU between two sets of intervals via greedy best-match.

For each interval in `a`, finds its highest-IoU match in `b` (without
replacement — once a `b` interval is matched it’s removed from the pool).
Unmatched intervals in either set contribute 0.0 to the mean.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  Mean IoU ∈ [0, 1]. Returns 0.0 if both sets are empty (defensible
  as a “no agreement to measure” baseline).

### lacing.quality.cohen_kappa(a, b)

Cohen’s kappa for two annotators on a categorical label.

* **Parameters:**
  * **a** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[`T`]) – Annotator A’s labels.
  * **b** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[`T`]) – Annotator B’s labels (must be the same length).
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  κ ∈ [-1, 1]. 1 = perfect agreement, 0 = chance, negative = worse than chance.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If sequences differ in length or are empty.

Edge cases:
: If only one category appears across both annotators, both observed
  and expected agreement are 1.0; we return 1.0 by convention.

### lacing.quality.interval_iou(a, b)

Intersection-over-Union for two time intervals.

Returns 1.0 if both are equal point intervals at the same instant; 0.0
if they don’t intersect (including when only one is a point).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### lacing.quality.krippendorff_alpha(annotations, , distance='nominal')

Krippendorff’s α across any number of annotators.

Computed by the coincidence-matrix method (Krippendorff 2011, “Computing
Krippendorff’s Alpha-Reliability”): only *pairable* units (two or more
non-missing values) count, and each ordered pair of values within a unit of
`m` values weighs `1 / (m - 1)`, so every pairable value contributes
exactly one to the coincidences, whatever the number of annotators who
rated its unit. The observed disagreement sums, unit by unit, the distance
over ordered pairs of distinct values (weighted by their counts in the
unit) divided by `m - 1`; the expected disagreement does the same over
the marginal value counts `n_c` of all pairable values, divided by
`n - 1`. Pairs of equal values never contribute.

* **Parameters:**
  * **annotations** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`T`]]]) – A list of annotators, each a sequence of labels (one per
    unit). Use `None` (or a float NaN, as pandas gives) for a missing
    annotation by that annotator on that unit. Labels are hashed and
    compared with `==`, so `1`, `1.0` and `True` are one value.
  * **distance** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'nominal'`, `'ordinal'`, `'interval'`, `'ratio'`], [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`T`, `T`], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – Krippendorff’s metric level, `"nominal"` (the default,
    0/1), `"ordinal"` (ranks, scaled by how the values are spread;
    labels must be orderable), `"interval"` (`(x - y) ** 2`) or
    `"ratio"` (`((x - y) / (x + y)) ** 2`); or any function
    `(x, y) -> float` measuring disagreement between two distinct
    label values.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  α. 1.0 = perfect agreement, 0.0 = chance. 1.0 also when the pairable
  values show no variation at all (no expected disagreement).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If sequences differ in length, fewer than 2 annotators
      given, or no unit has two or more non-missing values.

Krippendorff’s 2011 worked example: four annotators, twelve units, with
missing ratings (canonical nominal α = 0.743):

```pycon
>>> A = [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None]
>>> B = [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3]
>>> C = [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None]
>>> D = [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None]
>>> round(krippendorff_alpha([A, B, C, D]), 3)
0.743
>>> [round(krippendorff_alpha([A, B, C, D], distance=level), 3)
...  for level in ("ordinal", "interval", "ratio")]
[0.815, 0.849, 0.797]
```
