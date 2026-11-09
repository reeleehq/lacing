"""What a :class:`lacing.Restriction` means for one use (reeleehq/an#743).

lacing records a restriction and never classifies the licence it sits on top
of; this module answers the one question every consumer otherwise answers on
its own: *does this use break it?* :func:`restriction_breach` returns why, or
``None``. Each well-known kind has a check in :data:`RESTRICTION_CHECKS`; a kind
with no check is not cleared, as :class:`lacing.Restriction` documents.

A use is stated by its annual revenue (``revenue_usd``) and its territory
(``territory``, read by :func:`lacing.territory.normalize_territory`). An
unstated one fails closed against any restriction that asks about it.

>>> from lacing import Restriction
>>> cap = Restriction(kind="revenue_cap", usd=1_000_000, terms="stability-community")
>>> restriction_breach(cap, revenue_usd=20_000) is None
True
>>> restriction_breach(cap, revenue_usd=2_000_000)
'stability-community: allowed only below $1,000,000 of revenue (the use: $2,000,000)'
>>> eu = Restriction(kind="territory_excluded", codes=["EU", "GB"])
>>> restriction_breach(eu, territory="US") is None, restriction_breach(eu, territory="FR")
(True, 'not allowed in EU, GB (the use: FR)')
>>> restriction_breach(Restriction(kind="no_broadcast"))
"an unknown restriction 'no_broadcast': not cleared"
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from lacing.artifact import REVENUE_CAP, TERRITORY_EXCLUDED, Restriction
from lacing.territory import WORLDWIDE, territory_excluded

__all__ = [
    "RESTRICTION_CHECKS",
    "RestrictionCheck",
    "restriction_breach",
]

#: A kind's check: ``(restriction, revenue_usd, territory)`` -> why the use
#: breaks it, or ``None``. The restriction's parameters are already validated.
RestrictionCheck = Callable[[Restriction, "int | None", "str | None"], "str | None"]


def _params(restriction: Restriction) -> Mapping:
    return restriction.__pydantic_extra__ or {}


def _revenue_cap(
    restriction: Restriction, revenue_usd: int | None, territory: str | None
) -> str | None:
    cap = _params(restriction)["usd"]
    if revenue_usd is not None and revenue_usd < cap:
        return None
    use = "state the revenue" if revenue_usd is None else f"the use: ${revenue_usd:,}"
    return f"allowed only below ${cap:,} of revenue ({use})"


def _territory_excluded(
    restriction: Restriction, revenue_usd: int | None, territory: str | None
) -> str | None:
    codes = _params(restriction)["codes"]
    if not territory_excluded(codes, territory):
        return None
    if territory is None or not str(territory).strip():
        use = "state the territory"
    elif str(territory).strip().upper() == WORLDWIDE:
        use = f"{WORLDWIDE}: a use everywhere includes them"
    else:
        use = f"the use: {territory}"
    return f"not allowed in {', '.join(codes)} ({use})"


#: The check of each well-known kind. A consumer that knows another kind passes
#: its own map (``checks=``); a kind missing from the map is not cleared.
RESTRICTION_CHECKS: Mapping[str, RestrictionCheck] = {
    REVENUE_CAP: _revenue_cap,
    TERRITORY_EXCLUDED: _territory_excluded,
}


def restriction_breach(
    restriction: Restriction,
    *,
    revenue_usd: int | None = None,
    territory: str | None = None,
    checks: Mapping[str, RestrictionCheck] = RESTRICTION_CHECKS,
) -> str | None:
    """Why a use with ``revenue_usd`` in ``territory`` breaks ``restriction``, or ``None``.

    The reason leads with the restriction's ``terms`` when it names them. A kind
    with no entry in ``checks`` is never cleared (lacing#106's consumer rule).
    """
    check = checks.get(restriction.kind.strip())
    if check is None:
        reason = f"an unknown restriction {restriction.kind!r}: not cleared"
    else:
        reason = check(restriction, revenue_usd, territory)
    if reason is None:
        return None
    return f"{restriction.terms}: {reason}" if restriction.terms else reason
