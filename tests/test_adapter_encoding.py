"""The text adapters' ``encoding=`` seam: BOM sniffing, a named encoding, a clear error."""

from __future__ import annotations

import codecs

import pytest

from lacing.adapters import lrc, srt, webvtt
from lacing.adapters._common import decode_text

SRT = "1\n00:00:01,000 --> 00:00:02,000\ncafé — ünï\n"
VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\ncafé ünï\n"
LRC = "[00:01.00]café ünï\n"
CASES = [(srt, SRT, ".srt"), (webvtt, VTT, ".vtt"), (lrc, LRC, ".lrc")]
TEXT = "café"


def _texts(store):
    return [a.body["text"] for a in store.all()]


@pytest.mark.parametrize(
    "codec, bom",
    [
        ("utf-16-le", codecs.BOM_UTF16_LE),
        ("utf-16-be", codecs.BOM_UTF16_BE),
        ("utf-32-le", codecs.BOM_UTF32_LE),
        ("utf-32-be", codecs.BOM_UTF32_BE),
        ("utf-8", codecs.BOM_UTF8),
    ],
)
@pytest.mark.parametrize("module, text, ext", CASES)
def test_a_bom_file_loads_with_no_argument(tmp_path, module, text, ext, codec, bom):
    path = tmp_path / f"f{ext}"
    path.write_bytes(bom + text.encode(codec))
    assert any("café" in t for t in _texts(module.load(path)))
    # and the same bytes, not through a path
    assert any("café" in t for t in _texts(module.load(path.read_bytes())))


@pytest.mark.parametrize("module, text, ext", CASES)
def test_cp1252_loads_with_the_keyword(tmp_path, module, text, ext):
    text = text.replace("—", "-")
    path = tmp_path / f"f{ext}"
    path.write_bytes(text.encode("cp1252"))
    assert any("café" in t for t in _texts(module.load(path, encoding="cp1252")))


@pytest.mark.parametrize("module, text, ext", CASES)
def test_cp1252_without_the_keyword_names_it(tmp_path, module, text, ext):
    path = tmp_path / f"f{ext}"
    path.write_bytes(text.replace("—", "-").encode("cp1252"))
    with pytest.raises(UnicodeDecodeError, match="encoding="):
        module.load(path)


def test_a_wrong_named_encoding_is_reported_as_such():
    with pytest.raises(UnicodeDecodeError, match="wrong encoding="):
        decode_text("é".encode("utf-16"), encoding="ascii")


def test_named_utf8_still_drops_the_bom():
    assert decode_text(codecs.BOM_UTF8 + b"hi", encoding="utf-8") == "hi"
    assert decode_text(codecs.BOM_UTF8 + b"hi", encoding="UTF8") == "hi"


def test_a_utf32_le_bom_is_not_mistaken_for_utf16():
    assert decode_text("hé".encode("utf-32")) == "hé"


def test_inline_text_ignores_encoding():
    assert _texts(srt.load(SRT, encoding="cp1252"))[0].startswith("café")
