"""What a :class:`lacing.Restriction` means for one use (reeleehq/an#743).

lacing records a restriction and never classifies the licence it sits on top
of; this module answers the one question every consumer otherwise answers on
its own: *does this use break it?* :func:`restriction_breach` returns why, or
``None``. Each well-known kind has a check in :data:`RESTRICTION_CHECKS`; a kind
with no check is not cleared, as :class:`lacing.Restriction` documents.

A use is a :class:`Use`: its annual revenue (``revenue_usd``) and its
territory (``territory``, normalised by
:func:`lacing.territory.normalize_territory` when the ``Use`` is made, so a
territory nobody can place is refused there, once). An unstated one fails
closed against any restriction that asks about it.

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
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from lacing.artifact import REVENUE_CAP, TERRITORY_EXCLUDED, Restriction
from lacing.territory import WORLDWIDE, normalize_territory, territory_excluded

__all__ = [
    "RESTRICTION_CHECKS",
    "RestrictionCheck",
    "Use",
    "restriction_breach",
]


@dataclass(frozen=True, kw_only=True)
class Use:
    """One use of an asset, as the restrictions on it ask about it.

    ``revenue_usd`` is the user's annual revenue in whole US dollars and
    ``territory`` where the use happens (an ISO 3166-1 alpha-2 code, an alias
    such as ``"UK"``, or :data:`lacing.territory.WORLDWIDE`); ``None`` leaves
    either unstated, which fails closed against a restriction that asks.

    >>> Use(territory=" uk ", revenue_usd=5_000)
    Use(revenue_usd=5000, territory='GB')
    >>> Use()
    Use(revenue_usd=None, territory=None)

    Raises:
        ValueError: If ``territory`` is not one a gate can place (a name, an
            alpha-3 code, a region such as ``"EU"``), or ``revenue_usd`` is
            negative.
        TypeError: If ``revenue_usd`` is not an ``int`` (a ``bool`` is not).
    """

    revenue_usd: int | None = None
    territory: str | None = None

    def __post_init__(self) -> None:
        revenue = self.revenue_usd
        if revenue is not None:
            if isinstance(revenue, bool) or not isinstance(revenue, int):
                raise TypeError(
                    f"revenue_usd must be a whole number of US dollars, got {revenue!r}"
                )
            if revenue < 0:
                raise ValueError(f"revenue_usd cannot be negative, got {revenue!r}")
        object.__setattr__(self, "territory", normalize_territory(self.territory))


#: The use nothing is stated about: every restriction that asks fails closed.
_UNSTATED_USE = Use()

#: A kind's check: ``(restriction, use)`` -> why the use breaks it, or
#: ``None``. The restriction's parameters are already validated.
RestrictionCheck = Callable[[Restriction, Use], "str | None"]


def _params(restriction: Restriction) -> Mapping:
    return restriction.__pydantic_extra__ or {}


def _revenue_cap(restriction: Restriction, use: Use) -> str | None:
    cap = _params(restriction)["usd"]
    revenue = use.revenue_usd
    if revenue is not None and revenue < cap:
        return None
    stated = "state the revenue" if revenue is None else f"the use: ${revenue:,}"
    return f"allowed only below ${cap:,} of revenue ({stated})"


def _territory_excluded(restriction: Restriction, use: Use) -> str | None:
    codes = _params(restriction)["codes"]
    if not territory_excluded(codes, use.territory):
        return None
    if use.territory is None:
        stated = "state the territory"
    elif use.territory == WORLDWIDE:
        stated = f"{WORLDWIDE}: a use everywhere includes them"
    else:
        stated = f"the use: {use.territory}"
    return f"not allowed in {', '.join(codes)} ({stated})"


#: The check of each well-known kind. A consumer that knows another kind passes
#: its own map (``checks=``); a kind missing from the map is not cleared.
RESTRICTION_CHECKS: Mapping[str, RestrictionCheck] = {
    REVENUE_CAP: _revenue_cap,
    TERRITORY_EXCLUDED: _territory_excluded,
}


def restriction_breach(
    restriction: Restriction,
    use: Use = _UNSTATED_USE,
    *,
    checks: Mapping[str, RestrictionCheck] = RESTRICTION_CHECKS,
) -> str | None:
    """Why ``use`` breaks ``restriction``, or ``None`` (an unstated use by default).

    The reason leads with the restriction's ``terms`` when it names them. A kind
    with no entry in ``checks`` is never cleared (lacing#106's consumer rule).
    """
    check = checks.get(restriction.kind.strip())
    if check is None:
        reason = f"an unknown restriction {restriction.kind!r}: not cleared"
    else:
        reason = check(restriction, use)
    if reason is None:
        return None
    return f"{restriction.terms}: {reason}" if restriction.terms else reason
