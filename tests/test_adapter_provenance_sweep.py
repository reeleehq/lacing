"""Every import adapter stamps a *known* generation time (lacing#44).

The adapters used to stamp ``RationalTime.zero(rate)`` — lacing's UNKNOWN
sentinel — as ``generated_at_time`` on every imported annotation, so an
import manufactured exactly the rows that read as unverifiable downstream.
This sweep runs each adapter's import on its own sample input and asserts
that every produced annotation can be placed in time. A guard test keeps
the sweep honest: a new adapter module must be added here or the guard
fails.
"""

from __future__ import annotations

import json
import pkgutil

import pytest

import lacing.adapters


# Adapters whose import *creates* provenance. ``annot`` is lacing's own
# format: it round-trips the provenance it was given, so it is not a
# stamping site.
STAMPING_ADAPTERS = (
    "eaf",
    "textgrid",
    "webvtt",
    "srt",
    "lrc",
    "ass",
    "jams",
    "otio",
    "label_studio",
    "web_annotation",
    "podcast_transcript",
    "podcast_chapters",
)


def _load_eaf(tmp_path):
    from tests.test_adapter_eaf import adapter_module, build_sample_eaf

    return adapter_module.load(build_sample_eaf(tmp_path), rate=1000)


def _load_textgrid(tmp_path):
    from tests.test_adapter_textgrid import adapter_module, build_sample_textgrid

    return adapter_module.load(build_sample_textgrid(tmp_path), rate=1000)


def _load_webvtt(tmp_path):
    from tests.test_adapter_webvtt import SAMPLE_VTT, adapter_module

    return adapter_module.load(SAMPLE_VTT, rate=1000)


def _load_srt(tmp_path):
    from tests.test_adapter_srt import SAMPLE_SRT, adapter_module

    return adapter_module.load(SAMPLE_SRT, rate=1000)


def _load_lrc(tmp_path):
    from tests.test_adapter_lrc import ENHANCED_LRC, adapter_module

    return adapter_module.load(ENHANCED_LRC, rate=1000)


def _load_ass(tmp_path):
    from tests.test_adapter_ass import AEGISUB_ASS, adapter_module

    return adapter_module.load(AEGISUB_ASS, rate=1000)


def _load_jams(tmp_path):
    from tests.test_adapter_jams import adapter_module, build_sample_jams

    return adapter_module.load(build_sample_jams(tmp_path), rate=1000)


def _load_otio(tmp_path):
    from tests.test_adapter_otio import adapter_module, build_sample_otio

    return adapter_module.load(build_sample_otio(tmp_path), rate=1000)


def _load_label_studio(tmp_path):
    from tests.test_adapter_label_studio import SAMPLE_TASK, adapter_module

    return adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)


def _load_web_annotation(tmp_path):
    from tests.test_adapter_web_annotation import COLLECTION, adapter_module

    return adapter_module.load(json.dumps(COLLECTION))


def _load_podcast_transcript(tmp_path):
    from tests.test_adapter_podcast_transcript import SPEC_EXAMPLE, adapter_module

    return adapter_module.load(SPEC_EXAMPLE, rate=1000)


def _load_podcast_chapters(tmp_path):
    from tests.test_adapter_podcast_chapters import COMPLEX_EXAMPLE, adapter_module

    return adapter_module.load(COMPLEX_EXAMPLE, rate=1000)


_LOADERS = {
    "eaf": _load_eaf,
    "textgrid": _load_textgrid,
    "webvtt": _load_webvtt,
    "srt": _load_srt,
    "lrc": _load_lrc,
    "ass": _load_ass,
    "jams": _load_jams,
    "otio": _load_otio,
    "label_studio": _load_label_studio,
    "web_annotation": _load_web_annotation,
    "podcast_transcript": _load_podcast_transcript,
    "podcast_chapters": _load_podcast_chapters,
}


@pytest.mark.parametrize("name", STAMPING_ADAPTERS)
def test_import_stamps_a_known_generation_time(name, tmp_path):
    """Every annotation an import produces has ``generated_at_is_known``.

    The sibling test module's ``importorskip`` fires on import, so an adapter
    whose optional dependency is absent skips here exactly as it does there.
    """
    store = _LOADERS[name](tmp_path)
    produced = list(store.all())
    assert produced, f"{name}: the sample input produced no annotations"
    unknown = [a.id for a in produced if not a.provenance.generated_at_is_known]
    assert unknown == [], f"{name}: tick-0 generated_at_time on {unknown}"


@pytest.mark.parametrize("name", STAMPING_ADAPTERS)
def test_import_stamps_an_import_activity_and_its_own_generator(name, tmp_path):
    """What the shared ``import_provenance`` stamps (lacing#176): an ``import``
    (or, for what an adapter infers, ``infer``) activity, and a generator id of
    the adapter's own or an agent's."""
    import importlib

    module = importlib.import_module(f"lacing.adapters.{name}")
    for a in _LOADERS[name](tmp_path).all():
        prov = a.provenance
        assert prov.activity in {"import", "infer"}, (name, prov.activity)
        assert prov.was_generated_by in {module.GENERATED_BY} or (
            prov.was_generated_by.startswith("agent:")
        ), (name, prov.was_generated_by)


def test_every_adapter_module_is_swept():
    """A new adapter module lands in this sweep or this fails.

    ``_``-prefixed modules are shared helpers, not formats.
    """
    modules = {
        m.name
        for m in pkgutil.iter_modules(lacing.adapters.__path__)
        if not m.name.startswith("_")
    }
    assert modules == {"annot", *STAMPING_ADAPTERS}


def test_helper_modules_register_no_adapter():
    """What lets the sweep above skip ``_``-prefixed modules."""
    import importlib

    for m in pkgutil.iter_modules(lacing.adapters.__path__):
        importlib.import_module(f"lacing.adapters.{m.name}")
    from lacing.adapters import _REGISTRY

    helpers = [
        spec.name
        for spec in _REGISTRY.values()
        if spec.load.__module__.startswith("lacing.adapters._")
    ]
    assert helpers == []
