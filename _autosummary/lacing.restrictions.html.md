# lacing.restrictions

What a [`lacing.Restriction`](lacing.html.md#lacing.Restriction) means for one use (reeleehq/an#743).

lacing records a restriction and never classifies the licence it sits on top
of; this module answers the one question every consumer otherwise answers on
its own: *does this use break it?* [`restriction_breach()`](#lacing.restrictions.restriction_breach) returns why, or
`None`. Each well-known kind has a check in [`RESTRICTION_CHECKS`](#lacing.restrictions.RESTRICTION_CHECKS); a kind
with no check is not cleared, as [`lacing.Restriction`](lacing.html.md#lacing.Restriction) documents.

A use is a [`Use`](#lacing.restrictions.Use): its annual revenue (`revenue_usd`) and its
territory (`territory`, normalised by
[`lacing.territory.normalize_territory()`](lacing.territory.html.md#lacing.territory.normalize_territory) when the `Use` is made, so a
territory nobody can place is refused there, once). An unstated one fails
closed against any restriction that asks about it.

```pycon
>>> from lacing import Restriction
>>> cap = Restriction(kind="revenue_cap", usd=1_000_000, terms="stability-community")
>>> restriction_breach(cap, Use(revenue_usd=20_000)) is None
True
>>> restriction_breach(cap, Use(revenue_usd=2_000_000))
'stability-community: allowed only below $1,000,000 of revenue (the use: $2,000,000)'
>>> eu = Restriction(kind="territory_excluded", codes=["EU", "GB"])
>>> restriction_breach(eu, Use(territory="US")) is None, restriction_breach(eu, Use(territory="fr"))
(True, 'not allowed in EU, GB (the use: FR)')
>>> restriction_breach(Restriction(kind="no_broadcast"))
"an unknown restriction 'no_broadcast': not cleared"
```

### Module Attributes

| [`RestrictionCheck`](#lacing.restrictions.RestrictionCheck)   | `(restriction, use)` -> why the use breaks it, or `None`.   |
|---------------------------------------------------------------------|-------------------------------------------------------------|
| [`RESTRICTION_CHECKS`](#lacing.restrictions.RESTRICTION_CHECKS) | The check of each well-known kind.                          |

### Functions

| [`restriction_breach`](#lacing.restrictions.restriction_breach)(restriction[, use, checks])   | Why `use` breaks `restriction`, or `None` (an unstated use by default).   |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|

### Classes

| [`Use`](#lacing.restrictions.Use)(\*[, revenue_usd, territory])   | One use of an asset, as the restrictions on it ask about it.   |
|--------------------------------------------------------------------------------------|----------------------------------------------------------------|

### lacing.restrictions.RESTRICTION_CHECKS *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Callable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[Restriction](lacing.artifact.html.md#lacing.artifact.Restriction), [Use](#lacing.restrictions.Use)], [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)]]* *= {'revenue_cap': <function \_revenue_cap>, 'territory_excluded': <function \_territory_excluded>}*

The check of each well-known kind. A consumer that knows another kind passes
its own map (`checks=`); a kind missing from the map is not cleared.

### lacing.restrictions.RestrictionCheck

`(restriction, use)` -> why the use breaks it, or
`None`. The restriction’s parameters are already validated.

* **Type:**
  A kind’s check

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Restriction`](lacing.artifact.html.md#lacing.artifact.Restriction), [`Use`](#lacing.restrictions.Use)], str | None]

### *class* lacing.restrictions.Use(, revenue_usd=None, territory=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One use of an asset, as the restrictions on it ask about it.

`revenue_usd` is the user’s annual revenue in whole US dollars and
`territory` where the use happens (an ISO 3166-1 alpha-2 code, an alias
such as `"UK"`, or [`lacing.territory.WORLDWIDE`](lacing.territory.html.md#lacing.territory.WORLDWIDE)); `None` leaves
either unstated, which fails closed against a restriction that asks.

```pycon
>>> Use(territory=" uk ", revenue_usd=5_000)
Use(revenue_usd=5000, territory='GB')
>>> Use()
Use(revenue_usd=None, territory=None)
```

* **Raises:**
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `territory` is not one a gate can place (a name, an
        alpha-3 code, a region such as `"EU"`), or `revenue_usd` is
        negative.
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – If `revenue_usd` is not an `int` (a `bool` is not).

### lacing.restrictions.restriction_breach(restriction, use=Use(revenue_usd=None, territory=None), \*, checks={'revenue_cap': <function \_revenue_cap>, 'territory_excluded': <function \_territory_excluded>})

Why `use` breaks `restriction`, or `None` (an unstated use by default).

The reason leads with the restriction’s `terms` when it names them. A kind
with no entry in `checks` is never cleared (lacing#106’s consumer rule).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
