# lacing.id_slug

The federation’s one **id-slug** rule: a traversal-safe path segment.

Many reeleehq packages name things with an id that later becomes a URL path
segment (`/panels/{panel_id}`), a file or folder name (a project’s folder is
its id), or an HTTP header value (`X-Reelee-Project`). All of them need the
same guarantee, and before this module each wrote it out again (lacing#165):

```default
[A-Za-z0-9][A-Za-z0-9._-]*      at most 255 characters
```

That is: ASCII letters, digits, `.`, `_` and `-`, starting with a letter or
digit. The leading-alphanumeric rule excludes `.`, `..` and dotfiles without
a special case; the charset excludes `/`, `\`, `%`, whitespace, control
characters and anything non-ASCII (which an HTTP header cannot carry). 255 is the
per-component limit of ext4, APFS and NTFS, and an ASCII id is one byte per
character, so it is the OS bound rather than a product choice; pass
`max_length` for a tighter one.

```pycon
>>> is_id_slug("b03"), is_id_slug("we_ll.see-2")
(True, True)
>>> is_id_slug("../etc"), is_id_slug("a/b"), is_id_slug("Café"), is_id_slug("ok\n")
(False, False, False, False)
>>> check_id_slug("Café Noir", label="project id")
Traceback (most recent call last):
    ...
lacing.id_slug.IdSlugError: invalid project id 'Café Noir': ...Try 'Cafe-Noir'.
>>> slugify_id("Café Noir"), slugify_id("我的项目"), slugify_id("  ...my/story...  ")
('Cafe-Noir', 'id', 'my-story')
```

Match with [`re.fullmatch()`](https://docs.python.org/3/library/re.html#re.fullmatch) (as [`is_id_slug()`](#lacing.id_slug.is_id_slug) does), never with an
`^...$` pattern and [`re.match()`](https://docs.python.org/3/library/re.html#re.match): Python’s `$` also matches just before a
trailing newline, so `"abc\n"` passes that check and reaches the filesystem.
[`ID_SLUG_JSON_PATTERN`](#lacing.id_slug.ID_SLUG_JSON_PATTERN) is the anchored form for JSON Schema and pydantic’s
`pattern=`, whose `$` is the end of the input.

**What the rule does not cover**, stated so nobody assumes it does: it is
case-sensitive, so `Foo` and `foo` are two ids that are one folder on a
case-insensitive filesystem (macOS, Windows); and it admits names Windows
treats specially (`CON`, `NUL`, a trailing `.`). A package that stores ids
as folders on such a filesystem and needs those cases refused adds that check on
top. The shared rule is the one every existing copy already enforced, with two
differences a caller that delegates should know about: a trailing newline is
refused (see above), and so is an id over 255 characters where the old copy had
no length cap (pass a larger `max_length` to keep accepting those).

Each package keeps its own vocabulary (`is_valid_project_id`,
`check_panel_id`) as a one-line delegation, passing its own `label` so the
refusal names the thing the caller tried to create. [`IdSlugError`](#lacing.id_slug.IdSlugError) carries
the parts (`problem`, `suggestion`) for a package that phrases its own
message.

Stdlib only, with no import from the rest of [`lacing`](lacing.html.md#module-lacing). Importing it as
`lacing.id_slug` still runs `lacing/__init__` (pydantic, dol: about a second
on a cold start), so a caller that promises a light import surface imports it
inside the delegating function, where only the first call pays:

```default
def is_valid_project_id(value) -> bool:
    from lacing.id_slug import is_id_slug

    return is_id_slug(value)
```

### Module Attributes

| [`ID_SLUG_PATTERN`](#lacing.id_slug.ID_SLUG_PATTERN)      | The rule, unanchored.                                                                                                 |
|-----------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`ID_SLUG_RE`](#lacing.id_slug.ID_SLUG_RE)           | The compiled rule; call `ID_SLUG_RE.fullmatch(value)`.                                                                |
| [`ID_SLUG_JSON_PATTERN`](#lacing.id_slug.ID_SLUG_JSON_PATTERN) | The anchored form, for JSON Schema `pattern` and pydantic `Field(pattern=)` (both treat `$` as end of input).         |
| [`MAX_ID_SLUG_LENGTH`](#lacing.id_slug.MAX_ID_SLUG_LENGTH)   | The filesystem's per-path-component limit (255 bytes on ext4, APFS and NTFS; one byte per character for an ASCII id). |
| [`FALLBACK_ID_SLUG`](#lacing.id_slug.FALLBACK_ID_SLUG)     | What [`slugify_id()`](#lacing.id_slug.slugify_id) returns when nothing usable survives, by default.  |

### Functions

| [`check_id_slug`](#lacing.id_slug.check_id_slug)(value, \*[, label, max_length, ...])   | Return `value` if it is an id slug, else raise [`IdSlugError`](#lacing.id_slug.IdSlugError).   |
|-------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| [`distinct_id_slug`](#lacing.id_slug.distinct_id_slug)(value, \*[, max_length, ...])       | `value` itself when it is already an id slug, else its slug plus a short digest of `value`.                    |
| [`is_id_slug`](#lacing.id_slug.is_id_slug)(value, \*[, max_length])                  | Whether `value` is a string that satisfies the id-slug rule.                                                   |
| [`slugify_id`](#lacing.id_slug.slugify_id)(value, \*[, max_length, fallback])        | A best-effort id slug for `value`: the *suggestion* in a refusal.                                              |

### Exceptions

| [`IdSlugError`](#lacing.id_slug.IdSlugError)(message, \*, value, label, ...)   | An id refused by [`check_id_slug()`](#lacing.id_slug.check_id_slug).   |
|------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|

### lacing.id_slug.FALLBACK_ID_SLUG *= 'id'*

What [`slugify_id()`](#lacing.id_slug.slugify_id) returns when nothing usable survives, by default.

### lacing.id_slug.ID_SLUG_JSON_PATTERN *= '^[A-Za-z0-9][A-Za-z0-9._-]\*$'*

The anchored form, for JSON Schema `pattern` and pydantic `Field(pattern=)`
(both treat `$` as end of input). Not for Python’s [`re.match()`](https://docs.python.org/3/library/re.html#re.match).

### lacing.id_slug.ID_SLUG_PATTERN *= '[A-Za-z0-9][A-Za-z0-9._-]\*'*

The rule, unanchored. Use it with [`re.fullmatch()`](https://docs.python.org/3/library/re.html#re.fullmatch) (or [`ID_SLUG_RE`](#lacing.id_slug.ID_SLUG_RE)).

### lacing.id_slug.ID_SLUG_RE *= re.compile('[A-Za-z0-9][A-Za-z0-9._-]\*')*

The compiled rule; call `ID_SLUG_RE.fullmatch(value)`.

### *exception* lacing.id_slug.IdSlugError(message, , value, label, problem, suggestion)

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

An id refused by [`check_id_slug()`](#lacing.id_slug.check_id_slug).

`problem` is `"charset"` (wrong characters, or empty), `"length"` (the
characters are fine, it is too long) or `"type"` (not a string), so a
caller can phrase its own message; `suggestion` is [`slugify_id()`](#lacing.id_slug.slugify_id) of the
value (`None` for `"type"`).

### lacing.id_slug.MAX_ID_SLUG_LENGTH *= 255*

The filesystem’s per-path-component limit (255 bytes on ext4, APFS and NTFS;
one byte per character for an ASCII id).

### lacing.id_slug.check_id_slug(value, , label='id', max_length=255, reason='', hint='', fallback='id')

Return `value` if it is an id slug, else raise [`IdSlugError`](#lacing.id_slug.IdSlugError).

The refusal names `label` (the caller’s word for the thing: `"project
id"`, `"panel id"`) and suggests [`slugify_id()`](#lacing.id_slug.slugify_id)’s form. It refuses
rather than silently transliterating, because a caller who asked for one
name and got another back is a worse surprise than a clear no. `reason`,
when given, says why this caller needs the rule (`"it travels in the
X-Reelee-Project header"`) and is added to the charset message; `hint`, when
given, ends every message (`"Keep the original text as the display name."`);
`fallback` is the suggestion when nothing of the value survives slugifying.

The charset and the length are reported separately, because they have
different causes and different fixes. When both are wrong the charset
message wins: its suggestion also fixes the length.

```pycon
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
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### lacing.id_slug.distinct_id_slug(value, , max_length=255, digest_chars=6, fallback='id')

`value` itself when it is already an id slug, else its slug plus a short
digest of `value`.

So two different inputs never share a result (up to the digest), and an
input that is already a slug comes back unchanged. This is what an id
*derived* from a caller’s text needs (a panel id from a beat id), where
[`slugify_id()`](#lacing.id_slug.slugify_id) alone maps `"Opening scene"` and `"Opening/scene"` to
one id.

```pycon
>>> distinct_id_slug("b03")
'b03'
>>> distinct_id_slug("Opening scene")
'Opening-scene-8ba344'
>>> distinct_id_slug("Opening scene") != distinct_id_slug("Opening/scene")
True
>>> len(distinct_id_slug("x " * 300)) <= MAX_ID_SLUG_LENGTH
True
>>> is_id_slug(distinct_id_slug("我的项目"))
True
```

`max_length` must leave room for at least one character, a `-` and the
digest (`ValueError` otherwise).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### lacing.id_slug.is_id_slug(value, , max_length=255)

Whether `value` is a string that satisfies the id-slug rule.

Anything that is not a `str` is `False` rather than an error, so it can
guard untrusted input directly.

```pycon
>>> is_id_slug("p3f7c1"), is_id_slug("1.a_b"), is_id_slug("x" * 255)
(True, True, True)
>>> is_id_slug(""), is_id_slug(".."), is_id_slug(".hidden"), is_id_slug("-x")
(False, False, False, False)
>>> is_id_slug(None), is_id_slug(b"abc"), is_id_slug("x" * 256)
(False, False, False)
>>> is_id_slug("abcd", max_length=3)
False
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.id_slug.slugify_id(value, , max_length=255, fallback='id')

A best-effort id slug for `value`: the *suggestion* in a refusal.

Transliterates through NFKD (`é` becomes `e`), drops what will not
transliterate, turns every other run of characters into one `-`, trims
separators from both ends and truncates to `max_length`. Never raises;
returns `fallback` when nothing usable survives (or `value` is not a
string).

Two different inputs can give the same slug (`"a b"` and `"a/b"`); use
[`distinct_id_slug()`](#lacing.id_slug.distinct_id_slug) when the slug becomes an id that must not collide.
`fallback` must itself be an id slug within `max_length` (`ValueError`
otherwise), so the result always is one.

```pycon
>>> slugify_id("Café Noir")
'Cafe-Noir'
>>> slugify_id("我的项目", fallback="project")
'project'
>>> slugify_id("../../etc/passwd")
'etc-passwd'
>>> slugify_id("a" * 300) == "a" * 255
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
