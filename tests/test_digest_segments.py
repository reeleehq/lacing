"""The mixed-state candidates' canonical text is built from segments (lacing#181):
byte for byte the direct dump, over random bodies and combinations."""

import copy
import json
import random

import pytest

from lacing.digest import _ABSENT, _canonical, _SegmentedCanonical


def _dropped(payload, paths):
    """``(container, key, value, prefill)`` for each ``(container path, key)``."""
    out = []
    for where, key in paths:
        container = payload
        for step in where:
            container = container[step]
        out.append((container, key, container[key], None))
    return out


def _direct(payload, dropped, combo):
    body = copy.deepcopy(payload)
    # resolve every target in the copy before changing any of them
    targets = [(_find(body, payload, dropped[i][0]), dropped[i][1], state) for i, state in combo.items()]
    for target, key, state in targets:
        if state is _ABSENT:
            del target[key]
        else:
            target[key] = state
    return _canonical(body)


def _find(copy_root, root, container):
    """The copy of ``container`` (found by identity in ``root``) inside ``copy_root``."""
    stack = [(root, copy_root)]
    while stack:
        a, b = stack.pop()
        if a is container:
            return b
        if isinstance(a, dict):
            stack.extend((a[k], b[k]) for k in a)
        elif isinstance(a, list):
            stack.extend(zip(a, b))
    raise LookupError


STATES = [_ABSENT, None, "", "h", {"nested": [1, "é", None]}, 0, "  line"]


@pytest.mark.parametrize("seed", range(40))
def test_segments_render_the_direct_dump(seed):
    rng = random.Random(seed)
    n = rng.randint(2, 12)
    images = [
        {"url": f"u{i}", "hash": f"h{i}", "zz": i, "a b": "x", "sha": f"s{i}"}
        for i in range(n)
    ]
    payload = {
        "body": {"images": images, "title": "Ünïcode \"quoted\"", "meta": {"k": 1}},
        "aaa": [1, 2],
        "tier": "t",
    }
    keys = ["hash", "sha", "url", "zz"]
    sites = [((("body", "images", i)), rng.choice(keys)) for i in range(n)]
    sites += [((("body", "images", i)), "a b") for i in range(n) if rng.random() < 0.3]
    sites = list(dict.fromkeys(sites))
    sites.append(((("body",)), "title"))  # a container that also holds containers
    dropped = _dropped(payload, sites)
    render = _SegmentedCanonical.of(payload, dropped)
    assert render is not None
    assert render.text({}) == _canonical(payload)
    for _ in range(60):
        moved = rng.sample(range(len(dropped)), rng.randint(1, len(dropped)))
        combo = {i: rng.choice(STATES) for i in moved}
        assert render.text(combo) == _direct(payload, dropped, combo), combo


def test_every_site_absent_leaves_no_stray_comma():
    payload = {"body": {"a": 1, "b": 2, "c": 3}}
    dropped = _dropped(payload, [(("body",), "a"), (("body",), "b"), (("body",), "c")])
    render = _SegmentedCanonical.of(payload, dropped)
    assert render.text({0: _ABSENT, 1: _ABSENT, 2: _ABSENT}) == '{"body":{}}'
    assert render.text({1: _ABSENT}) == '{"body":{"a":1,"c":3}}'
    assert render.text({0: _ABSENT, 2: _ABSENT}) == '{"body":{"b":2}}'


def test_a_body_holding_a_tokens_text_is_dumped_whole_instead():
    token = json.loads(json.dumps(_SegmentedCanonical._TOKEN.format(0)))
    payload = {"body": {"a": 1, "note": token}}
    assert _SegmentedCanonical.of(payload, _dropped(payload, [(("body",), "a")])) is None
