"""The federation's one id-slug rule (lacing#165)."""

import re

import pytest

import lacing
from lacing.id_slug import (
    ID_SLUG_JSON_PATTERN,
    ID_SLUG_PATTERN,
    MAX_ID_SLUG_LENGTH,
    IdSlugError,
    check_id_slug,
    distinct_id_slug,
    is_id_slug,
    slugify_id,
)

ACCEPTED = ["a", "0", "b03", "p07-copy", "1.a_b", "we_ll.see-2", "a..b", "x" * 255]
REFUSED = [
    "",
    ".",
    "..",
    ".hidden",
    "-x",
    "_x",
    "a/b",
    "a\\b",
    "../etc",
    "a b",
    "a%2Fb",
    "Café",
    "我的项目",
    "abc\n",  # Python's `$` matches before a trailing newline: fullmatch does not
    "abc\r",
    "a\x00b",
    "x" * 256,
]


@pytest.mark.parametrize("value", ACCEPTED)
def test_accepts(value):
    assert is_id_slug(value)
    assert check_id_slug(value) == value


@pytest.mark.parametrize("value", REFUSED)
def test_refuses(value):
    assert not is_id_slug(value)
    with pytest.raises(IdSlugError):
        check_id_slug(value)


@pytest.mark.parametrize("value", [None, 3, b"abc", ["a"]])
def test_non_strings_are_false_and_refused_as_type(value):
    assert not is_id_slug(value)
    with pytest.raises(IdSlugError) as info:
        check_id_slug(value, label="panel id")
    assert info.value.problem == "type"
    assert info.value.suggestion is None
    assert "panel id" in str(info.value)


def test_error_is_a_value_error_with_parts():
    with pytest.raises(ValueError) as info:
        check_id_slug("Café Noir", label="project id", reason="it travels in a header")
    err = info.value
    assert isinstance(err, IdSlugError)
    assert (err.problem, err.suggestion, err.label) == ("charset", "Cafe-Noir", "project id")
    assert "because it travels in a header" in str(err)
    assert "'Cafe-Noir'" in str(err)


def test_length_is_its_own_problem():
    with pytest.raises(IdSlugError) as info:
        check_id_slug("x" * 300, label="project id")
    assert info.value.problem == "length"
    assert "300 characters" in str(info.value)


def test_charset_wins_when_both_are_wrong():
    with pytest.raises(IdSlugError) as info:
        check_id_slug("é" * 300)
    assert info.value.problem == "charset"
    assert len(info.value.suggestion) <= MAX_ID_SLUG_LENGTH


def test_max_length_is_a_seam():
    assert is_id_slug("x" * 100, max_length=100)
    assert not is_id_slug("x" * 101, max_length=100)
    assert len(slugify_id("y" * 500, max_length=100)) == 100
    assert len(distinct_id_slug("é " * 500, max_length=100)) <= 100


@pytest.mark.parametrize(
    "value",
    ["Café Noir", "../../etc/passwd", "我的项目", "", "   ", "...", "a" * 400, "a\nb", "x/../y"],
)
def test_slugify_and_distinct_always_give_a_slug(value):
    assert is_id_slug(slugify_id(value))
    assert is_id_slug(distinct_id_slug(value))


def test_slugify_fallback():
    assert slugify_id("我的项目", fallback="project") == "project"
    assert slugify_id(None) == "id"


def test_distinct_keeps_slugs_and_separates_collisions():
    assert distinct_id_slug("b03") == "b03"
    a, b = distinct_id_slug("Opening scene"), distinct_id_slug("Opening/scene")
    assert slugify_id("Opening scene") == slugify_id("Opening/scene")
    assert a != b


def test_matches_reelee_distinct_slug_output():
    """reelee's `distinct_slug` (the starter) gave these; delegating must not
    rename an id reelee already derived and stored."""
    assert distinct_id_slug("Opening scene") == "Opening-scene-8ba344"


def test_patterns_agree():
    assert ID_SLUG_JSON_PATTERN == f"^{ID_SLUG_PATTERN}$"
    for value in ACCEPTED:
        assert re.fullmatch(ID_SLUG_PATTERN, value)
    for value in REFUSED:
        if isinstance(value, str) and len(value) <= MAX_ID_SLUG_LENGTH:
            assert not re.fullmatch(ID_SLUG_PATTERN, value)


def test_exported_from_lacing():
    for name in ("is_id_slug", "check_id_slug", "slugify_id", "distinct_id_slug", "IdSlugError"):
        assert getattr(lacing, name) is not None
        assert name in lacing.__all__


def test_module_is_stdlib_only():
    """It must not import the rest of lacing, so it stays a leaf a stdlib-only
    caller can depend on."""
    import ast
    import pathlib

    source = pathlib.Path(lacing.id_slug.__file__).read_text()
    imported = {
        (node.module or "").split(".")[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported <= {"__future__", "hashlib", "re", "unicodedata"}
