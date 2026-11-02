"""Tests for lacing.quality — IAA and boundary metrics."""

from __future__ import annotations

import math

import random

import pytest

from lacing.quality import (
    boundary_iou,
    cohen_kappa,
    interval_iou,
    krippendorff_alpha,
)
from lacing.time import RationalTime, TimeInterval


# --- Cohen's kappa ----------------------------------------------------------


class TestCohenKappa:
    def test_perfect_agreement(self):
        assert cohen_kappa(["A", "B", "A"], ["A", "B", "A"]) == 1.0

    def test_total_disagreement(self):
        assert cohen_kappa(["A", "B"], ["B", "A"]) == pytest.approx(-1.0)

    def test_chance_level(self):
        # Independent uniform → expected ≈ 0
        a = ["A", "B"] * 50
        b = ["A", "A", "B", "B"] * 25
        # Observed agreement: 50% (A,A) + 0% (B,A) + 0% (A,B) + 50% (B,B)
        k = cohen_kappa(a, b)
        assert -0.1 < k < 0.1

    def test_single_category(self):
        # Both annotators always say "X" — perfect by convention.
        assert cohen_kappa(["X"] * 5, ["X"] * 5) == 1.0

    def test_known_value(self):
        # Sanity check from a well-known textbook example.
        # 50 cases. Both rate "yes" 30 times. They agree on 25 of those.
        # Both rate "no" 20 times. They agree on 15 of those.
        # Disagreements: 5 yes/no + 5 no/yes = 10
        a = ["Y"] * 25 + ["Y"] * 5 + ["N"] * 5 + ["N"] * 15
        b = ["Y"] * 25 + ["N"] * 5 + ["Y"] * 5 + ["N"] * 15
        k = cohen_kappa(a, b)
        # p_o = 40/50 = 0.8
        # p_a = 30/50 = 0.6 (Y rate annotator a), 30/50 = 0.6 Y rate b
        # p_e = 0.6*0.6 + 0.4*0.4 = 0.52
        # k = (0.8 - 0.52) / (1 - 0.52) ≈ 0.583
        assert k == pytest.approx(0.5833333, abs=1e-4)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            cohen_kappa(["A"], ["A", "B"])

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            cohen_kappa([], [])


# --- Krippendorff's alpha ---------------------------------------------------


class TestKrippendorffAlpha:
    def test_perfect_agreement(self):
        rows = [
            ["A", "B", "C", "D"],
            ["A", "B", "C", "D"],
        ]
        assert krippendorff_alpha(rows) == 1.0

    def test_three_annotators_perfect(self):
        rows = [
            ["A", "A", "B", "B"],
            ["A", "A", "B", "B"],
            ["A", "A", "B", "B"],
        ]
        assert krippendorff_alpha(rows) == 1.0

    def test_disagreement_negative(self):
        rows = [
            ["A", "A", "A"],
            ["B", "B", "B"],
        ]
        # All values present and they always disagree → α should be very negative.
        a = krippendorff_alpha(rows)
        assert a < 0

    def test_handles_missing(self):
        rows = [
            ["A", "B", None, "D"],
            ["A", "B", "C", None],
        ]
        # Two paired observations (A,A and B,B) both agree → α = 1.0
        a = krippendorff_alpha(rows)
        assert a == 1.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            krippendorff_alpha([["A"], ["A", "B"]])

    def test_too_few_annotators_raises(self):
        with pytest.raises(ValueError):
            krippendorff_alpha([["A", "B"]])

    def test_no_paired_observations_raises(self):
        rows = [
            ["A", None],
            [None, "B"],
        ]
        with pytest.raises(ValueError):
            krippendorff_alpha(rows)

    def test_custom_distance(self):
        # Absolute-difference distance: closer numbers disagree less.
        def absolute_difference(x, y):
            return abs(x - y)

        rows = [
            [1, 2, 3, 4],
            [1, 2, 3, 5],  # only the last one differs by 1
        ]
        a = krippendorff_alpha(rows, distance=absolute_difference)
        # Strong agreement; α should be close to 1.
        assert 0.7 < a <= 1.0

    def test_nan_is_missing(self):
        nan = float("nan")
        assert krippendorff_alpha([[1, nan, 2], [1, nan, 2]]) == 1.0
        assert krippendorff_alpha([[1, nan, 2], [1, 3, 2]]) == 1.0

    def test_constant_distance_perfect_agreement(self):
        """A value never disagrees with itself, whatever ``distance`` says."""
        rows = [["A", "B", "C"], ["A", "B", "C"]]
        assert krippendorff_alpha(rows, distance=lambda x, y: 1.0) == 1.0


# Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability", section C:
# four observers, twelve units, missing ratings (lacing#108).
_K2011 = [
    [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None],
    [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3],
    [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None],
    [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None],
]


@pytest.mark.parametrize(
    "distance, canonical",
    [
        (None, 0.743),  # nominal, the default
        ("nominal", 0.743),
        ("ordinal", 0.815),  # needs the marginals: only as a level (#114)
        ("interval", 0.849),
        ("ratio", 0.797),
        (lambda x, y: (x - y) ** 2, 0.849),  # interval, as a callable
        (lambda x, y: ((x - y) / (x + y)) ** 2, 0.797),  # ratio, as a callable
    ],
)
def test_krippendorff_2011_worked_example(distance, canonical):
    kw = {} if distance is None else {"distance": distance}
    assert round(krippendorff_alpha(_K2011, **kw), 3) == canonical


def test_krippendorff_2011_nominal_is_not_the_unweighted_pair_mean():
    """The pre-lacing#108 unweighted pair mean gave 0.7196 here."""
    alpha = krippendorff_alpha(_K2011)
    assert alpha == pytest.approx(0.7434, abs=1e-4)
    assert alpha != pytest.approx(0.7196, abs=1e-3)


def _pairwise_alpha(rows, distance):
    """The textbook pairwise form, right only for complete data: the oracle for
    'complete data is unaffected' (lacing#108)."""
    columns = list(zip(*rows))
    pairs = [(x, y) for col in columns for i, x in enumerate(col) for y in col[i + 1 :]]
    values = [v for col in columns for v in col]
    all_pairs = [(x, y) for i, x in enumerate(values) for y in values[i + 1 :]]
    do = sum(distance(x, y) for x, y in pairs) / len(pairs)
    de = sum(distance(x, y) for x, y in all_pairs) / len(all_pairs)
    return 1.0 - do / de


@pytest.mark.parametrize("seed", range(20))
def test_on_complete_data_alpha_is_the_pairwise_form(seed):
    rng = random.Random(seed)
    n_raters, n_units = rng.randint(2, 5), rng.randint(3, 15)
    rows = [[rng.randint(1, 4) for _ in range(n_units)] for _ in range(n_raters)]
    nominal = lambda x, y: float(x != y)
    if len({v for row in rows for v in row}) < 2:
        pytest.skip("no variation in the drawn values: expected disagreement is 0")
    assert krippendorff_alpha(rows) == pytest.approx(_pairwise_alpha(rows, nominal))


def test_single_rated_units_do_not_count():
    """A unit with one value is not pairable: it must not move the expected
    disagreement (the second half of lacing#108)."""
    rows = [["A", "B", "A", "B"], ["A", "B", "B", "A"]]
    lonely = [row + [value] for row, value in zip(rows, ["C", None])]
    assert krippendorff_alpha(lonely) == krippendorff_alpha(rows)


def _random_rows_with_missing(rng):
    """Raters x units of values in 1..4, about a third missing as None or NaN,
    with at least one pairable unit."""
    missing = (None, float("nan"))
    n_raters, n_units = rng.randint(2, 5), rng.randint(3, 15)
    rows = [
        [
            rng.choice(missing) if rng.random() < 0.35 else rng.randint(1, 4)
            for _ in range(n_units)
        ]
        for _ in range(n_raters)
    ]
    rows[0][0], rows[1][0] = 1, 2  # one pairable unit, with variation
    return rows


@pytest.mark.parametrize("seed", range(20))
def test_alpha_with_missing_ignores_an_appended_single_rated_unit(seed):
    rng = random.Random(seed)
    rows = _random_rows_with_missing(rng)
    rater = rng.randrange(len(rows))
    lonely = [
        row + [rng.randint(1, 4) if i == rater else rng.choice([None, float("nan")])]
        for i, row in enumerate(rows)
    ]
    assert krippendorff_alpha(lonely) == pytest.approx(krippendorff_alpha(rows))


# --- interval_iou -----------------------------------------------------------


def _ti(s: int, e: int) -> TimeInterval:
    return TimeInterval(RationalTime(s), RationalTime(e))


class TestIntervalIoU:
    def test_identical(self):
        a = _ti(0, 100)
        assert interval_iou(a, a) == 1.0

    def test_disjoint(self):
        assert interval_iou(_ti(0, 10), _ti(20, 30)) == 0.0

    def test_half_overlap(self):
        # [0, 100) vs [50, 150): intersection 50, union 150
        score = interval_iou(_ti(0, 100), _ti(50, 150))
        assert score == pytest.approx(50 / 150)

    def test_contained(self):
        # [0, 100) contains [25, 75): intersection 50, union 100
        score = interval_iou(_ti(0, 100), _ti(25, 75))
        assert score == pytest.approx(0.5)

    def test_touching_is_zero(self):
        # Half-open: [0, 10) and [10, 20) share zero measure
        assert interval_iou(_ti(0, 10), _ti(10, 20)) == 0.0

    def test_two_points_equal(self):
        a = TimeInterval.point(RationalTime(5))
        b = TimeInterval.point(RationalTime(5))
        assert interval_iou(a, b) == 1.0

    def test_two_points_different(self):
        a = TimeInterval.point(RationalTime(5))
        b = TimeInterval.point(RationalTime(6))
        assert interval_iou(a, b) == 0.0

    def test_point_vs_interval(self):
        p = TimeInterval.point(RationalTime(5))
        i = _ti(0, 10)
        assert interval_iou(p, i) == 0.0


# --- boundary_iou ----------------------------------------------------------


class TestBoundaryIoU:
    def test_both_empty(self):
        assert boundary_iou([], []) == 0.0

    def test_identical_sets(self):
        ivs = [_ti(0, 10), _ti(20, 30), _ti(40, 50)]
        assert boundary_iou(ivs, ivs) == 1.0

    def test_one_off(self):
        a = [_ti(0, 100), _ti(200, 300)]
        b = [_ti(0, 100), _ti(200, 300), _ti(400, 500)]
        # Two perfect matches; one extra in b unmatched.
        # denominator = max(2, 3) = 3; total = 2.0
        score = boundary_iou(a, b)
        assert score == pytest.approx(2 / 3)

    def test_all_disjoint(self):
        a = [_ti(0, 10)]
        b = [_ti(100, 200)]
        assert boundary_iou(a, b) == 0.0

    def test_partial_overlap(self):
        a = [_ti(0, 100)]
        b = [_ti(50, 150)]
        score = boundary_iou(a, b)
        assert score == pytest.approx(50 / 150)


def test_the_ratio_level_survives_a_zero_label():
    """Raised ZeroDivisionError as a hand-written lambda (lacing#114). By hand:
    observed 2 (one 0/1 unit), expected 3 * 3 * 2 / 5 = 3.6."""
    alpha = krippendorff_alpha([[0, 0, 1], [0, 1, 1]], distance="ratio")
    assert alpha == pytest.approx(1 - 2 / 3.6)


def test_an_unknown_level_is_refused():
    with pytest.raises(ValueError, match="unknown distance level 'ordinl'"):
        krippendorff_alpha([[1, 2], [1, 2]], distance="ordinl")


@pytest.mark.parametrize("seed", range(20))
def test_ordinal_alpha_only_sees_the_order_of_the_labels(seed):
    """The ordinal metric reads ranks and counts, never numeric gaps: any
    order-preserving relabelling gives the same alpha."""
    rng = random.Random(seed)
    rows = _random_rows_with_missing(rng)
    relabel = {1: -7, 2: 0.5, 3: 40, 4: 1000}
    relabelled = [[relabel.get(v, v) for v in row] for row in rows]
    assert krippendorff_alpha(relabelled, distance="ordinal") == pytest.approx(
        krippendorff_alpha(rows, distance="ordinal")
    )
