"""Territories: the vocabulary a ``territory_excluded`` restriction is written in.

A :class:`lacing.Restriction` of kind :data:`lacing.TERRITORY_EXCLUDED` records
its ``codes`` verbatim (ISO 3166-1 alpha-2 country codes, or a region code such
as ``"EU"``). Reading one against a use needs the code set, the spellings that
name a country by another code, and what a region covers. They live here, beside
the kind, so every consumer (foley's licence gate, an's credits) reads codes the
same way instead of keeping its own copy (reeleehq/an#743).

>>> normalize_territory(" uk "), normalize_territory("EL"), normalize_territory("")
('GB', 'GR', None)
>>> territory_excluded({"EU", "GB"}, "fr"), territory_excluded({"EU"}, "US")
(True, False)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

__all__ = [
    "EU_MEMBER_STATES",
    "ISO_COUNTRY_CODES",
    "REGIONS",
    "TERRITORY_ALIASES",
    "WORLDWIDE",
    "normalize_territory",
    "territory_excluded",
    "unplaceable_codes",
]

#: The ISO 3166-1 alpha-2 country codes (the 249 officially assigned).
ISO_COUNTRY_CODES: frozenset[str] = frozenset(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN B"
    "O BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE"
    " DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW"
    .split()
)  # fmt: skip

#: Spellings that name a country by another code: the UK's common one and the
#: EU's code for Greece.
TERRITORY_ALIASES: Mapping[str, str] = {"UK": "GB", "EL": "GR"}

#: The territory of a use everywhere (online publishing reaches every country):
#: it falls in any exclusion.
WORLDWIDE = "WORLD"

#: The EU's member states, with the EU territories that carry their own codes:
#: France's outermost regions (Réunion, French Guiana, Guadeloupe, Martinique,
#: Mayotte, Saint-Martin) and Finland's Åland. (The Canaries, Azores, Madeira,
#: Ceuta and Melilla have none.)
EU_MEMBER_STATES: frozenset[str] = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE"
    " RE GF GP MQ YT MF AX"
    .split()
)  # fmt: skip

#: Region codes an exclusion may name, and the country codes each covers.
REGIONS: Mapping[str, frozenset[str]] = {"EU": EU_MEMBER_STATES}


def normalize_territory(territory: str | None) -> str | None:
    """``territory`` as an ISO 3166-1 alpha-2 code (or :data:`WORLDWIDE`), ``None`` when unstated.

    >>> normalize_territory("world")
    'WORLD'

    Raises:
        ValueError: If it is not a country code (a name, an alpha-3 code, a
            region): a gate cannot judge a use it cannot place.
    """
    if territory is None or not str(territory).strip():
        return None
    code = str(territory).strip().upper()
    code = TERRITORY_ALIASES.get(code, code)
    if code != WORLDWIDE and code not in ISO_COUNTRY_CODES:
        raise ValueError(
            f"territory must be an ISO 3166-1 alpha-2 country code (e.g. 'US', 'FR') "
            f"or {WORLDWIDE!r} (used everywhere), got {territory!r}"
        )
    return code


def unplaceable_codes(
    codes: Iterable[str], *, regions: Mapping[str, Iterable[str]] = REGIONS
) -> list[str]:
    """The recorded ``codes`` no use can be placed against, as recorded: one that
    is not an ISO code, an alias of one, or a region, and :data:`WORLDWIDE`
    (everywhere). A restriction recording any of them excludes every use.

    >>> unplaceable_codes(["eu", "Franc", "uk", "WORLD"])
    ['Franc', 'WORLD']
    """
    out = []
    for c in codes:
        code = str(c).strip().upper()
        code = TERRITORY_ALIASES.get(code, code)
        if code == WORLDWIDE or (code not in ISO_COUNTRY_CODES and code not in regions):
            out.append(c)
    return out


def territory_excluded(
    excluded: Iterable[str],
    territory: str | None,
    *,
    regions: Mapping[str, Iterable[str]] = REGIONS,
) -> bool:
    """Whether a use in ``territory`` falls in ``excluded`` (a region covers its members).

    It fails closed on both sides. Whenever anything is excluded, an unstated
    territory (``None``), a worldwide one, and one that is not a country code
    all count as excluded. And a recorded code is read through its aliases: one
    that names no country, no key of ``regions`` and not :data:`WORLDWIDE`
    (a typo such as ``"Franc"``) excludes every use, since nobody can tell what
    it meant; a recorded ``"WORLD"`` excludes every use by definition.

    >>> territory_excluded({"KR"}, None), territory_excluded({"UK"}, "gb")
    (True, True)
    >>> territory_excluded({"KR"}, "Korea"), territory_excluded(set(), None)
    (True, False)
    >>> territory_excluded({"KR"}, "WORLD"), territory_excluded(set(), "WORLD")
    (True, False)
    >>> territory_excluded({"Franc"}, "US"), territory_excluded({"WORLD"}, "US")
    (True, True)
    """
    codes = {str(c).strip().upper() for c in excluded}
    if not codes:
        return False
    codes = {TERRITORY_ALIASES.get(c, c) for c in codes}
    if unplaceable_codes(codes, regions=regions):
        return True  # recorded everywhere, or a code nobody can place
    try:
        code = normalize_territory(territory)
    except ValueError:
        return True
    if code is None or code == WORLDWIDE:  # unstated, or everywhere: it includes them
        return True
    return code in codes or any(
        code in members for region, members in regions.items() if region in codes
    )
