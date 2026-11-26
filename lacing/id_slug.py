"""The federation's one **id-slug** rule: a traversal-safe path segment.

Many reeleehq packages name things with an id that later becomes a URL path
segment (``/panels/{panel_id}``), a file or folder name (a project's folder is
its id), or an HTTP header value (``X-Reelee-Project``). All of them need the
same guarantee, and before this module each wrote it out again (lacing#165)::

    [A-Za-z0-9][A-Za-z0-9._-]*      at most 255 characters

That is: ASCII letters, digits, ``.``, ``_`` and ``-``, starting with a letter or
digit. The leading-alphanumeric rule excludes ``.``, ``..`` and dotfiles without
a special case; the charset excludes ``/``, ``\\``, ``%``, whitespace, control
characters and anything non-ASCII (which an HTTP header cannot carry). 255 is the
per-component limit of ext4, APFS and NTFS, and an ASCII id is one byte per
character, so it is the OS bound rather than a product choice; pass
``max_length`` for a tighter one.

>>> is_id_slug("b03"), is_id_slug("we_ll.see-2")
(True, True)
>>> is_id_slug("../etc"), is_id_slug("a/b"), is_id_slug("Café"), is_id_slug("ok\\n")
(False, False, False, False)
>>> check_id_slug("Café Noir", label="project id")
Traceback (most recent call last):
    ...
lacing.id_slug.IdSlugError: invalid project id 'Café Noir': ...Try 'Cafe-Noir'.
>>> slugify_id("Café Noir"), slugify_id("我的项目"), slugify_id("  ...my/story...  ")
('Cafe-Noir', 'id', 'my-story')

Match with :func:`re.fullmatch` (as :func:`is_id_slug` does), never with an
``^...$`` pattern and :func:`re.match`: Python's ``$`` also matches just before a
trailing newline, so ``"abc\\n"`` passes that check and reaches the filesystem.
:data:`ID_SLUG_JSON_PATTERN` is the anchored form for JSON Schema and pydantic's
``pattern=``, whose ``$`` is the end of the input.

**What the rule does not cover**, stated so nobody assumes it does: it is
case-sensitive, so ``Foo`` and ``foo`` are two ids that are one folder on a
case-insensitive filesystem (macOS, Windows); and it admits names Windows
treats specially (``CON``, ``NUL``, a trailing ``.``). A package that stores ids
as folders on such a filesystem and needs those cases refused adds that check on
top. The shared rule is the one every existing copy already enforced, with two
differences a caller that delegates should know about: a trailing newline is
refused (see above), and so is an id over 255 characters where the old copy had
no length cap (pass a larger ``max_length`` to keep accepting those).

Each package keeps its own vocabulary (``is_valid_project_id``,
``check_panel_id``) as a one-line delegation, passing its own ``label`` so the
refusal names the thing the caller tried to create. :class:`IdSlugError` carries
the parts (``problem``, ``suggestion``) for a package that phrases its own
message.

Stdlib only, with no import from the rest of :mod:`lacing`. Importing it as
``lacing.id_slug`` still runs ``lacing/__init__`` (pydantic, dol: about a second
on a cold start), so a caller that promises a light import surface imports it
inside the delegating function, where only the first call pays::

    def is_valid_project_id(value) -> bool:
        from lacing.id_slug import is_id_slug

        return is_id_slug(value)
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = [
    "FALLBACK_ID_SLUG",
    "ID_SLUG_JSON_PATTERN",
    "ID_SLUG_PATTERN",
    "ID_SLUG_RE",
    "IdSlugError",
    "MAX_ID_SLUG_LENGTH",
    "check_id_slug",
    "distinct_id_slug",
    "is_id_slug",
    "slugify_id",
]

#: The rule, unanchored. Use it with :func:`re.fullmatch` (or :data:`ID_SLUG_RE`).
ID_SLUG_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]*"

#: The compiled rule; call ``ID_SLUG_RE.fullmatch(value)``.
ID_SLUG_RE = re.compile(ID_SLUG_PATTERN)

#: The anchored form, for JSON Schema ``pattern`` and pydantic ``Field(pattern=)``
#: (both treat ``$`` as end of input). Not for Python's :func:`re.match`.
ID_SLUG_JSON_PATTERN = f"^{ID_SLUG_PATTERN}$"

#: The filesystem's per-path-component limit (255 bytes on ext4, APFS and NTFS;
#: one byte per character for an ASCII id).
MAX_ID_SLUG_LENGTH = 255

#: What :func:`slugify_id` returns when nothing usable survives, by default.
FALLBACK_ID_SLUG = "id"

_NON_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
_EDGE_SEPARATORS_RE = re.compile(r"^[._-]+|[._-]+$")


class IdSlugError(ValueError):
    """An id refused by :func:`check_id_slug`.

    ``problem`` is ``"charset"`` (wrong characters, or empty), ``"length"`` (the
    characters are fine, it is too long) or ``"type"`` (not a string), so a
    caller can phrase its own message; ``suggestion`` is :func:`slugify_id` of the
    value (``None`` for ``"type"``).
    """

    def __init__(
        self,
        message: str,
        *,
        value: object,
        label: str,
        problem: str,
        suggestion: str | None,
    ):
        super().__init__(message)
        self.message = message
        self.value = value
        self.label = label
        self.problem = problem
        self.suggestion = suggestion

    def __reduce__(self):
        # keyword-only arguments: rebuild through a helper so the error survives
        # pickling (multiprocessing, job queues)
        return (
            _rebuild_id_slug_error,
            (self.message, self.value, self.label, self.problem, self.suggestion),
        )


def _rebuild_id_slug_error(message, value, label, problem, suggestion):
    return IdSlugError(
        message, value=value, label=label, problem=problem, suggestion=suggestion
    )


def _checked_fallback(fallback: str, max_length: int) -> str:
    """``fallback`` if it is itself an id slug within ``max_length``, else ``ValueError``.

    The fallback is what comes back when nothing else survives, so a bad one (``"../"``)
    would be the one way these functions return a non-slug.
    """
    if max_length < 1:
        raise ValueError(f"max_length must be at least 1, got {max_length}")
    if not is_id_slug(fallback, max_length=max_length):
        raise ValueError(
            f"fallback {fallback!r} is not an id slug of at most {max_length} characters"
        )
    return fallback


def is_id_slug(value: object, *, max_length: int = MAX_ID_SLUG_LENGTH) -> bool:
    """Whether ``value`` is a string that satisfies the id-slug rule.

    Anything that is not a ``str`` is ``False`` rather than an error, so it can
    guard untrusted input directly.

    >>> is_id_slug("p3f7c1"), is_id_slug("1.a_b"), is_id_slug("x" * 255)
    (True, True, True)
    >>> is_id_slug(""), is_id_slug(".."), is_id_slug(".hidden"), is_id_slug("-x")
    (False, False, False, False)
    >>> is_id_slug(None), is_id_slug(b"abc"), is_id_slug("x" * 256)
    (False, False, False)
    >>> is_id_slug("abcd", max_length=3)
    False
    """
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and ID_SLUG_RE.fullmatch(value) is not None
    )


def slugify_id(
    value: object,
    *,
    max_length: int = MAX_ID_SLUG_LENGTH,
    fallback: str = FALLBACK_ID_SLUG,
) -> str:
    """A best-effort id slug for ``value``: the *suggestion* in a refusal.

    Transliterates through NFKD (``é`` becomes ``e``), drops what will not
    transliterate, turns every other run of characters into one ``-``, trims
    separators from both ends and truncates to ``max_length``. Never raises;
    returns ``fallback`` when nothing usable survives (or ``value`` is not a
    string).

    Two different inputs can give the same slug (``"a b"`` and ``"a/b"``); use
    :func:`distinct_id_slug` when the slug becomes an id that must not collide.
    ``fallback`` must itself be an id slug within ``max_length`` (``ValueError``
    otherwise), so the result always is one.

    >>> slugify_id("Café Noir")
    'Cafe-Noir'
    >>> slugify_id("我的项目", fallback="project")
    'project'
    >>> slugify_id("../../etc/passwd")
    'etc-passwd'
    >>> slugify_id("a" * 300) == "a" * 255
    True
    """
    fallback = _checked_fallback(fallback, max_length)
    if not isinstance(value, str):
        return fallback
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG_RE.sub("-", ascii_only)
    slug = _EDGE_SEPARATORS_RE.sub("", slug)[:max_length]
    slug = _EDGE_SEPARATORS_RE.sub("", slug)
    return slug or fallback


def distinct_id_slug(
    value: object,
    *,
    max_length: int = MAX_ID_SLUG_LENGTH,
    digest_chars: int = 6,
    fallback: str = FALLBACK_ID_SLUG,
) -> str:
    """``value`` itself when it is already an id slug, else its slug plus a short
    digest of ``value``.

    An input that is already a slug comes back unchanged, and any other input
    gets its slug plus a short digest of itself. This is what an id *derived*
    from a caller's text needs (a panel id from a beat id), where
    :func:`slugify_id` alone maps ``"Opening scene"`` and ``"Opening/scene"`` to
    one id.

    It is **not injective**. Two inputs that are not slugs differ in their
    results up to the digest (a hash collision), but a slug-shaped input is
    returned as is, so it can equal another input's *derived* form: an input
    already spelled ``<stem>-<digest>`` collides with the text it was derived
    from. A non-string is digested through its ``repr``, so ``b"a b"`` and the
    string ``"b'a b'"`` share a result. Callers that need a strict one-to-one
    map must refuse slug-shaped inputs of that shape themselves.

    >>> distinct_id_slug("b03")
    'b03'
    >>> distinct_id_slug("Opening scene")
    'Opening-scene-8ba344'
    >>> distinct_id_slug("Opening scene") != distinct_id_slug("Opening/scene")
    True
    >>> distinct_id_slug("Opening-scene-8ba344") == distinct_id_slug("Opening scene")
    True
    >>> distinct_id_slug(b"a b") == distinct_id_slug("b'a b'")
    True
    >>> len(distinct_id_slug("x " * 300)) <= MAX_ID_SLUG_LENGTH
    True
    >>> is_id_slug(distinct_id_slug("我的项目"))
    True

    ``max_length`` must leave room for at least one character, a ``-`` and the
    digest (``ValueError`` otherwise).
    """
    if is_id_slug(value, max_length=max_length):
        return value  # type: ignore[return-value]  # is_id_slug checked str
    if max_length < digest_chars + 2 or digest_chars < 1:
        raise ValueError(
            f"max_length={max_length} leaves no room for a stem, '-' and "
            f"{digest_chars} digest characters (need at least {digest_chars + 2})"
        )
    text = value if isinstance(value, str) else repr(value)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:digest_chars]
    stem_room = max_length - digest_chars - 1
    _checked_fallback(fallback, max_length)
    stem_fallback = fallback[:stem_room].rstrip("._-") or fallback[0]
    stem = slugify_id(text, max_length=stem_room, fallback=stem_fallback)
    return f"{stem}-{digest}"


def check_id_slug(
    value: object,
    *,
    label: str = "id",
    max_length: int = MAX_ID_SLUG_LENGTH,
    reason: str = "",
    hint: str = "",
    fallback: str = FALLBACK_ID_SLUG,
) -> str:
    """Return ``value`` if it is an id slug, else raise :class:`IdSlugError`.

    The refusal names ``label`` (the caller's word for the thing: ``"project
    id"``, ``"panel id"``) and suggests :func:`slugify_id`'s form. It refuses
    rather than silently transliterating, because a caller who asked for one
    name and got another back is a worse surprise than a clear no. ``reason``,
    when given, says why this caller needs the rule (``"it travels in the
    X-Reelee-Project header"``) and is added to the charset message; ``hint``, when
    given, ends every message (``"Keep the original text as the display name."``);
    ``fallback`` is the suggestion when nothing of the value survives slugifying.

    The charset and the length are reported separately, because they have
    different causes and different fixes. When both are wrong the charset
    message wins: its suggestion also fixes the length.

    >>> check_id_slug("bedtime_story", label="project id")
    'bedtime_story'
    >>> check_id_slug("a/b", label="panel id")
    Traceback (most recent call last):
        ...
    lacing.id_slug.IdSlugError: invalid panel id 'a/b': it must be an ASCII slug (letters, digits, '.', '_', '-'; starting with a letter or digit). Try 'a-b'.
    >>> check_id_slug("x" * 300)
    Traceback (most recent call last):
        ...
    lacing.id_slug.IdSlugError: invalid id: 300 characters is over the 255-character limit...
    >>> try:
    ...     check_id_slug("Café", reason="it is a folder name")
    ... except IdSlugError as e:
    ...     (e.problem, e.suggestion)
    ('charset', 'Cafe')
    >>> check_id_slug("我的", label="project id", fallback="project", hint="Keep the text as its name.")
    Traceback (most recent call last):
        ...
    lacing.id_slug.IdSlugError: invalid project id '我的': ... Try 'project'. Keep the text as its name.
    """
    if is_id_slug(value, max_length=max_length):
        return value  # type: ignore[return-value]  # is_id_slug checked str
    tail = f" {hint}" if hint else ""
    if not isinstance(value, str):
        raise IdSlugError(
            f"invalid {label}: expected a string, got {type(value).__name__}.{tail}",
            value=value,
            label=label,
            problem="type",
            suggestion=None,
        )
    suggestion = slugify_id(value, max_length=max_length, fallback=fallback)
    if ID_SLUG_RE.fullmatch(value) is not None:  # only the length is wrong
        raise IdSlugError(
            f"invalid {label}: {len(value)} characters is over the "
            f"{max_length}-character limit for one path component. Shorten it.{tail}",
            value=value,
            label=label,
            problem="length",
            suggestion=suggestion,
        )
    because = f" because {reason}" if reason else ""
    raise IdSlugError(
        f"invalid {label} {value!r}: it must be an ASCII slug "
        f"(letters, digits, '.', '_', '-'; starting with a letter or digit)"
        f"{because}. Try {suggestion!r}.{tail}",
        value=value,
        label=label,
        problem="charset",
        suggestion=suggestion,
    )
