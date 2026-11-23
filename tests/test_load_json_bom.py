"""``load_json`` reads what Windows tools write: a BOM, UTF-16 (lacing#174)."""

from __future__ import annotations

import codecs

import pytest

from lacing.adapters._common import load_json

DOC = '{"name": "café", "n": [1, 2]}'
EXPECTED = {"name": "café", "n": [1, 2]}


@pytest.mark.parametrize(
    "data",
    [
        codecs.BOM_UTF8 + DOC.encode("utf-8"),
        codecs.BOM_UTF16_LE + DOC.encode("utf-16-le"),
        codecs.BOM_UTF16_BE + DOC.encode("utf-16-be"),
        DOC.encode("utf-8"),
    ],
)
def test_bytes_and_files_with_or_without_a_bom(tmp_path, data):
    assert load_json(data) == EXPECTED
    path = tmp_path / "f.json"
    path.write_bytes(data)
    assert load_json(path) == EXPECTED
    assert load_json(str(path)) == EXPECTED


def test_inline_text_with_a_bom_char():
    assert load_json("﻿" + DOC) == EXPECTED
    assert load_json("﻿  [1]") == [1]


def test_a_non_utf8_file_says_so_without_offering_a_keyword(tmp_path):
    path = tmp_path / "f.json"
    path.write_bytes('{"a": "é"}'.encode("cp1252"))
    with pytest.raises(UnicodeDecodeError) as error:
        load_json(path)
    assert "not UTF-8" in str(error.value) and "encoding=" not in str(error.value)


import pytest


@pytest.mark.parametrize(
    "codec", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"]
)
def test_the_nul_hint_names_the_right_bomless_codec(codec):
    """The hint for BOM-less bytes with NULs follows where the NULs sit (lacing#210)."""
    from lacing.adapters._common import decode_text

    data = "1\n00:00:01,000 --> 00:00:02,000\nhello\n".encode(codec)
    with pytest.raises(UnicodeDecodeError) as info:
        decode_text(data)
    assert f"encoding='{codec}'" in str(info.value)
