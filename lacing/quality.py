"""Inter-annotator agreement and boundary metrics.

Phase 0 ships four metrics from ANN-DOC §D, all as pure functions:

- :func:`cohen_kappa` — agreement between two annotators on a categorical label.
- :func:`krippendorff_alpha` — agreement across any number of annotators
  (handles missing data, multiple distance metrics).
- :func:`interval_iou` — Intersection-over-Union for two time intervals.
- :func:`boundary_iou` — Average IoU between two sets of intervals (greedy match).

The doc cites Krippendorff thresholds: α > 0.8 reliable, 0.67–0.8 tentative,
< 0.67 discard. Kappa traditionally: >0.8 almost perfect, 0.6–0.8 substantial,
0.4–0.6 moderate.

Pure functions — no numpy dependency in Phase 0.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable, Sequence
from typing import Callable, TypeVar

from lacing.allen import intersects
from lacing.time import TimeInterval


T = TypeVar("T", bound=Hashable)


# ---------------------------------------------------------------------------
# Cohen's kappa
# ---------------------------------------------------------------------------


def cohen_kappa(a: Sequence[T], b: Sequence[T]) -> float:
    """Cohen's kappa for two annotators on a categorical label.

    Args:
        a: Annotator A's labels.
        b: Annotator B's labels (must be the same length).

    Returns:
        κ ∈ [-1, 1]. 1 = perfect agreement, 0 = chance, negative = worse than chance.

    Raises:
        ValueError: If sequences differ in length or are empty.

    Edge cases:
        If only one category appears across both annotators, both observed
        and expected agreement are 1.0; we return 1.0 by convention.
    """
    if len(a) != len(b):
        raise ValueError(f"length mismatch: {len(a)} vs {len(b)}")
    n = len(a)
    if n == 0:
        raise ValueError("empty sequences")

    p_observed = sum(1 for x, y in zip(a, b) if x == y) / n

    counts_a = Counter(a)
    counts_b = Counter(b)
    categories = set(counts_a) | set(counts_b)
    p_expected = sum((counts_a[c] / n) * (counts_b[c] / n) for c in categories)

    if p_expected == 1.0:
        # Both annotators always agree on a single category — perfect.
        return 1.0
    return (p_observed - p_expected) / (1.0 - p_expected)


# ---------------------------------------------------------------------------
# Krippendorff's alpha
# ---------------------------------------------------------------------------


def _nominal_distance(x: T, y: T) -> float:
    return 0.0 if x == y else 1.0


def krippendorff_alpha(
    annotations: Sequence[Sequence[T | None]],
    *,
    distance: Callable[[T, T], float] = _nominal_distance,
) -> float:
    """Krippendorff's α across any number of annotators.

    Computed by the coincidence-matrix method (Krippendorff 2011, "Computing
    Krippendorff's Alpha-Reliability"): only *pairable* units (two or more
    values present) count, and each ordered pair of values within a unit of
    ``m`` values weighs ``1 / (m - 1)``, so every pairable value contributes
    exactly one to the coincidences, whatever the number of annotators who
    rated its unit.

    Args:
        annotations: A list of annotators, each a sequence of labels (one per
            unit). Use ``None`` for a missing annotation by that annotator on
            that unit.
        distance: Function ``(x, y) -> float`` measuring disagreement between
            two label values, with ``distance(x, x) == 0``. Default is the
            nominal (0/1) distance; ``(x - y) ** 2`` gives the interval metric.
            Metrics that depend on the value frequencies (ordinal) are not
            expressible this way.

    Returns:
        α. 1.0 = perfect agreement, 0.0 = chance. 1.0 also when the pairable
        values show no variation at all (no expected disagreement).

    Raises:
        ValueError: If sequences differ in length, fewer than 2 annotators
            given, or no unit has two values present.

    Krippendorff's 2011 worked example: four annotators, twelve units, with
    missing ratings (canonical nominal α = 0.743):

    >>> A = [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None]
    >>> B = [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3]
    >>> C = [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None]
    >>> D = [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None]
    >>> round(krippendorff_alpha([A, B, C, D]), 3)
    0.743
    """
    if len(annotations) < 2:
        raise ValueError("need at least 2 annotators")
    n_units = len(annotations[0])
    for row in annotations:
        if len(row) != n_units:
            raise ValueError(
                f"all annotator rows must have the same length; got {len(row)} vs {n_units}"
            )

    units = (
        [row[u] for row in annotations if row[u] is not None] for u in range(n_units)
    )
    pairable = [values for values in units if len(values) >= 2]
    if not pairable:
        raise ValueError("not enough paired observations to compute alpha")

    # Observed: sum over the coincidence matrix, o_ck * distance(c, k), built
    # unit by unit with each ordered pair weighted 1 / (m_u - 1).
    observed = sum(
        sum(
            distance(values[i], values[j])  # type: ignore[arg-type]
            for i in range(len(values))
            for j in range(len(values))
            if i != j
        )
        / (len(values) - 1)
        for values in pairable
    )
    # Expected: from the marginals n_c of the coincidence matrix, which are the
    # counts of each value over the pairable units.
    marginals = Counter(v for values in pairable for v in values)
    n = sum(marginals.values())
    expected = sum(
        n_c * (n_k - (c == k)) * distance(c, k)  # type: ignore[arg-type]
        for c, n_c in marginals.items()
        for k, n_k in marginals.items()
    ) / (n - 1)
    if expected == 0:
        return 1.0
    return 1.0 - observed / expected


# ---------------------------------------------------------------------------
# Interval IoU
# ---------------------------------------------------------------------------


def interval_iou(a: TimeInterval, b: TimeInterval) -> float:
    """Intersection-over-Union for two time intervals.

    Returns 1.0 if both are equal point intervals at the same instant; 0.0
    if they don't intersect (including when only one is a point).
    """
    if a.is_point and b.is_point:
        return 1.0 if a.start == b.start else 0.0
    if a.is_point or b.is_point:
        # A point and an interval can't have a meaningful Lebesgue IoU.
        return 0.0
    if not intersects(a, b):
        return 0.0

    a_start = a.start.to_fraction()
    a_end = a.end.to_fraction()
    b_start = b.start.to_fraction()
    b_end = b.end.to_fraction()

    inter_start = max(a_start, b_start)
    inter_end = min(a_end, b_end)
    intersection = inter_end - inter_start

    union_start = min(a_start, b_start)
    union_end = max(a_end, b_end)
    union = union_end - union_start

    if union == 0:
        return 0.0
    return float(intersection / union)


def boundary_iou(a: Iterable[TimeInterval], b: Iterable[TimeInterval]) -> float:
    """Mean IoU between two sets of intervals via greedy best-match.

    For each interval in ``a``, finds its highest-IoU match in ``b`` (without
    replacement — once a ``b`` interval is matched it's removed from the pool).
    Unmatched intervals in either set contribute 0.0 to the mean.

    Returns:
        Mean IoU ∈ [0, 1]. Returns 0.0 if both sets are empty (defensible
        as a "no agreement to measure" baseline).
    """
    a_list = list(a)
    b_list = list(b)
    if not a_list and not b_list:
        return 0.0

    available_b = list(b_list)
    total = 0.0
    matched = 0

    # Greedy: for each `a` find best `b`. (For Phase 0 this is fine; switching
    # to Hungarian assignment would matter only with many-to-many ambiguity.)
    for ai in a_list:
        if not available_b:
            break
        best_score = 0.0
        best_idx = -1
        for j, bj in enumerate(available_b):
            score = interval_iou(ai, bj)
            if score > best_score:
                best_score = score
                best_idx = j
        if best_idx >= 0:
            available_b.pop(best_idx)
            total += best_score
            matched += 1

    # Unmatched intervals on either side count as 0 → divisor is the union count.
    denominator = max(len(a_list), len(b_list))
    return total / denominator
