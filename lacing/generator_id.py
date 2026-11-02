"""The grammar of ``Provenance.was_generated_by``, and an advisory check of it.

A generator identifier names the activity that produced an annotation or
artifact::

    <prefix>:<name>[@<version>]

``prefix`` is lower-case kebab (``user``, ``agent``, ``adapter`` ...), ``name``
is anything without whitespace or ``@`` (model names carry ``/`` and ``.``), and
``version``, after the one ``@``, is what pins the generator: a weights or
version digest, a dated snapshot, or a probe digest. For ``agent:`` it is the
slot a model-drift defence depends on (lacing#17), so the convention asks for it.

``@`` is reserved: it is the version separator under every prefix, so a name
never contains one. ``user:a@b.com`` parses as name ``a``, version ``b.com``;
a handle that is an e-mail address has to be written without its ``@``.

The check is **advisory** (lacing#17): writers already in production disagree
with the documented convention (``agent:`` with no ``@``, an application slug in
the ``@`` slot, prefixes nobody documented), and real data has to show the
census before anything starts rejecting. So:

- a value that is not of the ``<prefix>:<name>[@<version>]`` shape at all makes
  :class:`lacing.Provenance` emit a :class:`GeneratorIdWarning` at construction.
  Escalate it to an error with the warnings filter
  (``-W error::lacing.GeneratorIdWarning``), silence it the same way. Escalating
  also rejects *reads* of legacy rows, since the stores rebuild a ``Provenance``
  on every read: it is a census tool, not a write gate;
- the convention-level findings (an undocumented prefix, an ``agent:`` without a
  version) are only reported by :func:`generator_id_findings`, for a census::

      Counter(f for a in annotations
              for f in generator_id_findings(a.provenance.was_generated_by))

Whether the ``@`` slot holds a digest or a slug cannot be told from the string
(a dated snapshot is neither hex nor a slug), so it is not checked here.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass

import pydantic

__all__ = [
    "GENERATOR_ID_SHAPE",
    "GENERATOR_PREFIXES",
    "VERSIONED_PREFIXES",
    "GeneratorId",
    "GeneratorIdWarning",
    "parse_generator_id",
    "generator_id_findings",
]

GENERATOR_ID_SHAPE = "<prefix>:<name>[@<version>]"
"""The shape every ``was_generated_by`` is checked against."""

GENERATOR_PREFIXES: Mapping[str, str] = {
    "user": "a person acting through a UI or API: ``user:<handle>``",
    "agent": "a model or service: ``agent:<model>@<version digest or snapshot>``",
    "adapter": "an import/export format adapter: ``adapter:<format>``",
    "processor": "a lacing processor: ``processor:<name>``",
    "transform": "a pipeline transform: ``transform:<name>@<version>``",
    "server": "a server-side operation: ``server:<service>``",
    "fetch": "a retrieval from an external source: ``fetch:<source>``",
}
"""The documented prefixes, each with what follows it. ``transform``, ``server``
and ``fetch`` were in production before they were documented (lacing#17)."""

VERSIONED_PREFIXES: frozenset[str] = frozenset({"agent"})
"""Prefixes whose convention asks for an ``@<version>``."""

_SHAPE = re.compile(
    r"(?P<prefix>[a-z][a-z0-9-]*):(?P<name>[^@\s]+)(?:@(?P<version>[^@\s]+))?"
)


_INTERNAL_DIRS = tuple(
    os.path.dirname(path) + os.sep for path in (pydantic.__file__, __file__)
)
"""pydantic's and lacing's package directories: frames a warning should not point at."""


def _external_stacklevel() -> int:
    """The ``stacklevel`` that points a warning at the first frame outside pydantic
    and lacing, for a ``warnings.warn`` made by this function's caller."""
    frame, level = sys._getframe(1), 1
    while frame is not None and frame.f_code.co_filename.startswith(_INTERNAL_DIRS):
        frame, level = frame.f_back, level + 1
    return level


class GeneratorIdWarning(UserWarning):
    """A ``was_generated_by`` that is not of the ``<prefix>:<name>[@<version>]`` shape."""


@dataclass(frozen=True)
class GeneratorId:
    """A parsed ``was_generated_by``: ``<prefix>:<name>[@<version>]``."""

    prefix: str
    name: str
    version: str | None = None

    def __str__(self) -> str:
        return f"{self.prefix}:{self.name}" + (
            f"@{self.version}" if self.version else ""
        )


def parse_generator_id(value: str) -> GeneratorId | None:
    """Parse ``value``, or return ``None`` when it is not of the generator-id shape.

    >>> parse_generator_id("agent:fal-ai/flux@sha256:9f2c")
    GeneratorId(prefix='agent', name='fal-ai/flux', version='sha256:9f2c')
    >>> parse_generator_id("adapter:textgrid")
    GeneratorId(prefix='adapter', name='textgrid', version=None)
    >>> parse_generator_id("thor") is None
    True
    """
    match = _SHAPE.fullmatch(value)
    return GeneratorId(**match.groupdict()) if match else None


def generator_id_findings(
    value: str,
    *,
    prefixes: Collection[str] = GENERATOR_PREFIXES,
    versioned: Collection[str] = VERSIONED_PREFIXES,
) -> list[str]:
    """What ``value`` does differently from the documented convention; empty if nothing.

    Advisory: nothing here rejects. ``prefixes`` is the set of known prefixes and
    ``versioned`` the ones that ask for an ``@<version>``; pass your own to check
    against a wider or stricter convention.

    >>> generator_id_findings("agent:flux@sha256:9f2c")
    []
    >>> generator_id_findings("agent:nw.graph")
    ["prefix 'agent' expects an @<version>"]
    >>> generator_id_findings("test:doctest")
    ["undocumented prefix 'test'"]
    >>> generator_id_findings("t")
    ["not of the shape '<prefix>:<name>[@<version>]'"]
    """
    parsed = parse_generator_id(value)
    if parsed is None:
        return [f"not of the shape {GENERATOR_ID_SHAPE!r}"]
    findings = []
    if parsed.prefix not in prefixes:
        findings.append(f"undocumented prefix {parsed.prefix!r}")
    if parsed.prefix in versioned and parsed.version is None:
        findings.append(f"prefix {parsed.prefix!r} expects an @<version>")
    return findings
