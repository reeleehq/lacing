"""Tests for lacing.time."""

import numbers
from fractions import Fraction

import pytest

from lacing.time import (
    DEFAULT_RATE,
    LossyTimeConversionError,
    RationalTime,
    TimeInterval,
)


class TestRationalTime:
    def test_construction(self):
        t = RationalTime(48000, 24000)
        assert t.value == 48000
        assert t.rate == 24000

    def test_default_rate(self):
        t = RationalTime(0)
        assert t.rate == DEFAULT_RATE

    def test_negative_rate_rejected(self):
        with pytest.raises(ValueError):
            RationalTime(0, -1)

    def test_zero_rate_rejected(self):
        with pytest.raises(ValueError):
            RationalTime(0, 0)

    def test_float_value_rejected(self):
        with pytest.raises(TypeError):
            RationalTime(1.5)  # type: ignore[arg-type]

    def test_bool_rejected(self):
        # bool is a subclass of int, but it's a smell to allow it.
        with pytest.raises(TypeError):
            RationalTime(True)  # type: ignore[arg-type]

    def test_equality_across_rates(self):
        assert RationalTime(24, 24) == RationalTime(1, 1)
        assert RationalTime(48000, 24000) == RationalTime(2, 1)

    def test_ordering(self):
        a = RationalTime(1, 2)  # 0.5s
        b = RationalTime(1, 1)  # 1s
        assert a < b
        assert b > a
        assert a <= b
        assert a != b

    def test_hash_matches_equality(self):
        s = {RationalTime(2, 4), RationalTime(1, 2), RationalTime(4, 8)}
        assert len(s) == 1

    def test_from_seconds_string(self):
        t = RationalTime.from_seconds("1.5", rate=2)
        assert t.value == 3
        assert t.rate == 2

    def test_from_seconds_int(self):
        t = RationalTime.from_seconds(2, rate=10)
        assert t.value == 20

    def test_from_seconds_lossy_raises(self):
        with pytest.raises(LossyTimeConversionError):
            RationalTime.from_seconds("0.1", rate=3)

    def test_from_seconds_fraction(self):
        t = RationalTime.from_seconds(Fraction(1, 3), rate=3)
        assert t.value == 1
        assert t.rate == 3

    def test_to_fraction(self):
        assert RationalTime(3, 4).to_fraction() == Fraction(3, 4)

    def test_to_seconds_is_float(self):
        s = RationalTime(1, 2).to_seconds()
        assert isinstance(s, float)
        assert s == 0.5

    def test_to_rate_exact(self):
        t = RationalTime(1, 2).to_rate(48000)
        assert t.value == 24000
        assert t.rate == 48000

    def test_to_rate_lossy_raises(self):
        with pytest.raises(LossyTimeConversionError):
            RationalTime(1, 3).to_rate(2)

    def test_addition(self):
        a = RationalTime(1, 4)
        b = RationalTime(1, 4)
        c = a + b
        assert c.to_fraction() == Fraction(1, 2)
        assert c.rate == 4

    def test_subtraction(self):
        a = RationalTime(3, 4)
        b = RationalTime(1, 4)
        assert (a - b).to_fraction() == Fraction(1, 2)

    def test_addition_lossy_raises(self):
        # rate=2 can't represent (1/2 + 1/3) = 5/6
        with pytest.raises(LossyTimeConversionError):
            RationalTime(1, 2) + Fraction(1, 3)

    def test_wire_round_trip(self):
        t = RationalTime(123, 456)
        assert RationalTime.from_wire(t.to_wire()) == t

    def test_wire_format(self):
        assert RationalTime(7, 8).to_wire() == {"v": 7, "r": 8}

    def test_zero(self):
        z = RationalTime.zero()
        assert z.value == 0
        assert z.rate == DEFAULT_RATE

    def test_from_seconds_lossy_quantizes_instead_of_raising(self):
        # "0.1" at rate=3 is lossy; from_seconds raises, from_seconds_lossy quantizes.
        t = RationalTime.from_seconds_lossy("0.1", rate=3)
        assert t.rate == 3
        assert t.value == 0  # 0.3 samples rounds to 0

    def test_from_seconds_lossy_modes(self):
        # 0.1s * 3 = 0.3 samples
        assert RationalTime.from_seconds_lossy("0.1", rate=3, mode="round").value == 0
        assert RationalTime.from_seconds_lossy("0.1", rate=3, mode="floor").value == 0
        assert RationalTime.from_seconds_lossy("0.1", rate=3, mode="ceil").value == 1
        # 0.9s * 3 = 2.7 samples
        assert RationalTime.from_seconds_lossy("0.9", rate=3, mode="round").value == 3
        assert RationalTime.from_seconds_lossy("0.9", rate=3, mode="floor").value == 2
        assert RationalTime.from_seconds_lossy("0.9", rate=3, mode="ceil").value == 3

    def test_from_seconds_lossy_exact_is_exact(self):
        # When the value IS representable, lossy conversion matches from_seconds.
        assert RationalTime.from_seconds_lossy("1.5", rate=2).value == 3
        assert RationalTime.from_seconds_lossy(2, rate=10).value == 20

    def test_from_seconds_lossy_handles_float(self):
        # The float landmine: 8.021333 doesn't quantize cleanly at 24000.
        t = RationalTime.from_seconds_lossy(8.021333, rate=DEFAULT_RATE)
        assert t.rate == DEFAULT_RATE
        assert isinstance(t.value, int)

    def test_from_seconds_lossy_bad_mode_rejected(self):
        with pytest.raises(ValueError):
            RationalTime.from_seconds_lossy("1.0", rate=2, mode="truncate")

    def test_from_seconds_lossy_bool_rejected(self):
        with pytest.raises(TypeError):
            RationalTime.from_seconds_lossy(True)  # type: ignore[arg-type]

    def test_now_returns_rational_time(self):
        t = RationalTime.now()
        assert isinstance(t, RationalTime)
        assert t.rate == DEFAULT_RATE
        assert t.value > 0

    def test_now_respects_rate(self):
        t = RationalTime.now(rate=48000)
        assert t.rate == 48000

    def test_now_is_monotonic_nondecreasing(self):
        a = RationalTime.now()
        b = RationalTime.now()
        assert b >= a

    def test_repr(self):
        assert repr(RationalTime(1, 2)) == "RationalTime(1, 2)"


class TestTimeInterval:
    def test_from_seconds_lossy_quantizes_what_from_seconds_refuses(self):
        with pytest.raises(LossyTimeConversionError):
            TimeInterval.from_seconds(3.48, 4.0, rate=1000)
        i = TimeInterval.from_seconds_lossy(3.48, 4.0, rate=1000)
        assert (i.start, i.end) == (RationalTime(3480, 1000), RationalTime(4000, 1000))

    @pytest.mark.parametrize("x, tick", [(0.0005, 1), (0.0025, 3), (0.0055, 5)])
    def test_from_seconds_lossy_uses_the_exact_rule(self, x, tick):
        """The float's own value decides, not the rounded float product
        (``round(0.0005 * 1000) == 0``): lacing#145."""
        i = TimeInterval.from_seconds_lossy(x, x, rate=1000)
        assert i.start == RationalTime(tick, 1000) == i.end
        assert i.start == RationalTime.from_seconds_lossy(x, rate=1000)

    @pytest.mark.parametrize(
        "mode, ticks", [("round", (0, 2)), ("floor", (0, 1)), ("ceil", (1, 2))]
    )
    def test_from_seconds_lossy_mode_applies_to_both_ends(self, mode, ticks):
        i = TimeInterval.from_seconds_lossy("0.1", "0.5", rate=3, mode=mode)
        assert (i.start.value, i.end.value) == ticks

    @pytest.mark.parametrize("x", [float("inf"), float("-inf"), float("nan")])
    def test_from_seconds_lossy_refuses_non_finite(self, x):
        with pytest.raises(ValueError):
            TimeInterval.from_seconds_lossy(0, x)

    def test_from_seconds_lossy_reversed_and_bad_mode(self):
        with pytest.raises(ValueError):
            TimeInterval.from_seconds_lossy(2.0, 1.0)
        with pytest.raises(ValueError):
            TimeInterval.from_seconds_lossy(0, 1, mode="nearest")

    def test_construction(self):
        i = TimeInterval(RationalTime(0), RationalTime(24000))
        assert i.start == RationalTime(0)
        assert i.end == RationalTime(24000)

    def test_end_before_start_rejected(self):
        with pytest.raises(ValueError):
            TimeInterval(RationalTime(2), RationalTime(1))

    def test_point_interval_allowed(self):
        i = TimeInterval(RationalTime(5), RationalTime(5))
        assert i.is_point
        assert i.duration == RationalTime(0, DEFAULT_RATE)

    def test_point_classmethod(self):
        t = RationalTime(7)
        i = TimeInterval.point(t)
        assert i.start == t == i.end
        assert i.is_point

    def test_duration(self):
        i = TimeInterval(RationalTime(10), RationalTime(30))
        assert i.duration == RationalTime(20, DEFAULT_RATE)

    def test_from_seconds(self):
        i = TimeInterval.from_seconds("0.5", "1.5", rate=2)
        assert i.start.value == 1
        assert i.end.value == 3

    def test_shift(self):
        i = TimeInterval(RationalTime(10), RationalTime(20))
        shifted = i.shift(RationalTime(5))
        assert shifted.start == RationalTime(15)
        assert shifted.end == RationalTime(25)

    def test_equality(self):
        a = TimeInterval(RationalTime(0), RationalTime(24000))
        b = TimeInterval(RationalTime(0, DEFAULT_RATE), RationalTime(1, 1))
        assert a == b

    def test_hash(self):
        a = TimeInterval(RationalTime(0), RationalTime(10))
        b = TimeInterval(RationalTime(0), RationalTime(10))
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_wire_round_trip(self):
        i = TimeInterval(RationalTime(0), RationalTime(24000))
        assert TimeInterval.from_wire(i.to_wire()) == i

    def test_repr(self):
        s = repr(TimeInterval(RationalTime(0), RationalTime(1)))
        assert "TimeInterval" in s


# -- from_seconds_lossy takes any real number, numpy scalars included (lacing#164) --


class _Real(numbers.Real):
    """A minimal non-float real, as a numpy scalar is: no float subclass."""

    def __init__(self, x: float):
        self._x = x

    __float__ = lambda self: float(self._x)  # noqa: E731
    __trunc__ = __floor__ = __ceil__ = __round__ = lambda self, *a: NotImplemented
    __add__ = __radd__ = __mul__ = __rmul__ = __neg__ = __pos__ = __abs__ = lambda *a: (
        NotImplemented
    )
    __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = lambda *a: (
        NotImplemented
    )
    __mod__ = __rmod__ = __pow__ = __rpow__ = lambda *a: NotImplemented
    __lt__ = __le__ = __eq__ = lambda *a: NotImplemented
    __hash__ = lambda self: 0


def test_lossy_accepts_a_real_that_is_not_a_float():
    t = RationalTime.from_seconds_lossy(_Real(3.48), rate=1000)
    assert t == RationalTime.from_seconds_lossy(3.48, rate=1000)
    iv = TimeInterval.from_seconds_lossy(_Real(3.48), _Real(4.0), rate=1000)
    assert iv == TimeInterval.from_seconds_lossy(3.48, 4.0, rate=1000)


@pytest.mark.parametrize("name", ["float32", "float64", "int64", "int32", "float16"])
def test_lossy_accepts_numpy_scalars(name):
    np = pytest.importorskip("numpy")
    x = getattr(np, name)(3)
    assert RationalTime.from_seconds_lossy(x, rate=1000).value == 3000


def test_lossy_numpy_float64_matches_the_python_float():
    np = pytest.importorskip("numpy")
    assert RationalTime.from_seconds_lossy(
        np.float64(3.48), rate=1000
    ) == RationalTime.from_seconds_lossy(3.48, rate=1000)
    assert (
        RationalTime.from_seconds_lossy(np.float32(0.5), rate=4, mode="ceil").value == 2
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_lossy_refuses_non_finite_reals(bad):
    with pytest.raises(ValueError):
        RationalTime.from_seconds_lossy(bad)
    np = pytest.importorskip("numpy")
    with pytest.raises(ValueError):
        RationalTime.from_seconds_lossy(np.float32(bad))


@pytest.mark.parametrize("bad", [None, [1.0], b"1", 1j])
def test_lossy_still_refuses_non_numbers(bad):
    with pytest.raises(TypeError):
        RationalTime.from_seconds_lossy(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name, seconds",
    [
        ("int8", 100),
        ("uint8", 200),
        ("int32", 100_000),
        ("int64", 10**15),
        ("uint64", 2**64 - 1),
    ],
)
def test_numpy_integers_do_not_wrap_around(name, seconds):
    np = pytest.importorskip("numpy")
    rate = 24000
    got = RationalTime.from_seconds_lossy(getattr(np, name)(seconds), rate=rate)
    assert got.value == seconds * rate


def test_numpy_longdouble_keeps_its_value():
    np = pytest.importorskip("numpy")
    x = np.longdouble(1) / np.longdouble(3)
    t = RationalTime.from_seconds_lossy(x, rate=3)
    assert t.value == 1


def test_from_seconds_takes_the_same_inputs_as_the_lossy_one():
    np = pytest.importorskip("numpy")
    assert RationalTime.from_seconds(np.float32(0.5), rate=2).value == 1
    assert RationalTime.from_seconds(np.int64(3), rate=2).value == 6
    with pytest.raises(LossyTimeConversionError):
        RationalTime.from_seconds(np.float32(0.1), rate=2)
