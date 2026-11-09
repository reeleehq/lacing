# lacing.territory

Territories: the vocabulary a `territory_excluded` restriction is written in.

A [`lacing.Restriction`](lacing.html.md#lacing.Restriction) of kind `lacing.TERRITORY_EXCLUDED` records
its `codes` verbatim (ISO 3166-1 alpha-2 country codes, or a region code such
as `"EU"`). Reading one against a use needs the code set, the spellings that
name a country by another code, and what a region covers. They live here, beside
the kind, so every consumer (foley’s licence gate, an’s credits) reads codes the
same way instead of keeping its own copy (reeleehq/an#743).

```pycon
>>> normalize_territory(" uk "), normalize_territory("EL"), normalize_territory("")
('GB', 'GR', None)
>>> territory_excluded({"EU", "GB"}, "fr"), territory_excluded({"EU"}, "US")
(True, False)
```

### Module Attributes

| [`ISO_COUNTRY_CODES`](#lacing.territory.ISO_COUNTRY_CODES)   | The ISO 3166-1 alpha-2 country codes (the 249 officially assigned).                                                                                                                                 |
|----------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`TERRITORY_ALIASES`](#lacing.territory.TERRITORY_ALIASES)   | the UK's common one and the EU's code for Greece.                                                                                                                                                   |
| [`WORLDWIDE`](#lacing.territory.WORLDWIDE)           | The territory of a use everywhere (online publishing reaches every country): it falls in any exclusion.                                                                                             |
| [`EU_MEMBER_STATES`](#lacing.territory.EU_MEMBER_STATES)    | The EU's member states, with the EU territories that carry their own codes: France's outermost regions (Réunion, French Guiana, Guadeloupe, Martinique, Mayotte, Saint-Martin) and Finland's Åland. |
| [`REGIONS`](#lacing.territory.REGIONS)             | Region codes an exclusion may name, and the country codes each covers.                                                                                                                              |

### Functions

| [`normalize_territory`](#lacing.territory.normalize_territory)(territory)                     | `territory` as an ISO 3166-1 alpha-2 code (or [`WORLDWIDE`](#lacing.territory.WORLDWIDE)), `None` when unstated.                                                                        |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`territory_excluded`](#lacing.territory.territory_excluded)(excluded, territory, \*[, ...]) | Whether a use in `territory` falls in `excluded` (a region covers its members).                                                                                                                         |
| [`unplaceable_codes`](#lacing.territory.unplaceable_codes)(codes, \*[, regions])            | The recorded `codes` no use can be placed against, as recorded: one that is not an ISO code, an alias of one, or a region, and [`WORLDWIDE`](#lacing.territory.WORLDWIDE) (everywhere). |

### lacing.territory.EU_MEMBER_STATES *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= frozenset({'AT', 'AX', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GF', 'GP', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MF', 'MQ', 'MT', 'NL', 'PL', 'PT', 'RE', 'RO', 'SE', 'SI', 'SK', 'YT'})*

The EU’s member states, with the EU territories that carry their own codes:
France’s outermost regions (Réunion, French Guiana, Guadeloupe, Martinique,
Mayotte, Saint-Martin) and Finland’s Åland. (The Canaries, Azores, Madeira,
Ceuta and Melilla have none.)

### lacing.territory.ISO_COUNTRY_CODES *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= frozenset({'AD', 'AE', 'AF', 'AG', 'AI', 'AL', 'AM', 'AO', 'AQ', 'AR', 'AS', 'AT', 'AU', 'AW', 'AX', 'AZ', 'BA', 'BB', 'BD', 'BE', 'BF', 'BG', 'BH', 'BI', 'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ', 'BR', 'BS', 'BT', 'BV', 'BW', 'BY', 'BZ', 'CA', 'CC', 'CD', 'CF', 'CG', 'CH', 'CI', 'CK', 'CL', 'CM', 'CN', 'CO', 'CR', 'CU', 'CV', 'CW', 'CX', 'CY', 'CZ', 'DE', 'DJ', 'DK', 'DM', 'DO', 'DZ', 'EC', 'EE', 'EG', 'EH', 'ER', 'ES', 'ET', 'FI', 'FJ', 'FK', 'FM', 'FO', 'FR', 'GA', 'GB', 'GD', 'GE', 'GF', 'GG', 'GH', 'GI', 'GL', 'GM', 'GN', 'GP', 'GQ', 'GR', 'GS', 'GT', 'GU', 'GW', 'GY', 'HK', 'HM', 'HN', 'HR', 'HT', 'HU', 'ID', 'IE', 'IL', 'IM', 'IN', 'IO', 'IQ', 'IR', 'IS', 'IT', 'JE', 'JM', 'JO', 'JP', 'KE', 'KG', 'KH', 'KI', 'KM', 'KN', 'KP', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC', 'LI', 'LK', 'LR', 'LS', 'LT', 'LU', 'LV', 'LY', 'MA', 'MC', 'MD', 'ME', 'MF', 'MG', 'MH', 'MK', 'ML', 'MM', 'MN', 'MO', 'MP', 'MQ', 'MR', 'MS', 'MT', 'MU', 'MV', 'MW', 'MX', 'MY', 'MZ', 'NA', 'NC', 'NE', 'NF', 'NG', 'NI', 'NL', 'NO', 'NP', 'NR', 'NU', 'NZ', 'OM', 'PA', 'PE', 'PF', 'PG', 'PH', 'PK', 'PL', 'PM', 'PN', 'PR', 'PS', 'PT', 'PW', 'PY', 'QA', 'RE', 'RO', 'RS', 'RU', 'RW', 'SA', 'SB', 'SC', 'SD', 'SE', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL', 'SM', 'SN', 'SO', 'SR', 'SS', 'ST', 'SV', 'SX', 'SY', 'SZ', 'TC', 'TD', 'TF', 'TG', 'TH', 'TJ', 'TK', 'TL', 'TM', 'TN', 'TO', 'TR', 'TT', 'TV', 'TW', 'TZ', 'UA', 'UG', 'UM', 'US', 'UY', 'UZ', 'VA', 'VC', 'VE', 'VG', 'VI', 'VN', 'VU', 'WF', 'WS', 'YE', 'YT', 'ZA', 'ZM', 'ZW'})*

The ISO 3166-1 alpha-2 country codes (the 249 officially assigned).

### lacing.territory.REGIONS *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]]* *= {'EU': frozenset({'AT', 'AX', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GF', 'GP', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MF', 'MQ', 'MT', 'NL', 'PL', 'PT', 'RE', 'RO', 'SE', 'SI', 'SK', 'YT'})}*

Region codes an exclusion may name, and the country codes each covers.

### lacing.territory.TERRITORY_ALIASES *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {'EL': 'GR', 'UK': 'GB'}*

the UK’s common one and the
EU’s code for Greece.

* **Type:**
  Spellings that name a country by another code

### lacing.territory.WORLDWIDE *= 'WORLD'*

The territory of a use everywhere (online publishing reaches every country):
it falls in any exclusion.

### lacing.territory.normalize_territory(territory)

`territory` as an ISO 3166-1 alpha-2 code (or [`WORLDWIDE`](#lacing.territory.WORLDWIDE)), `None` when unstated.

```pycon
>>> normalize_territory("world")
'WORLD'
```

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If it is not a country code (a name, an alpha-3 code, a
      region): a gate cannot judge a use it cannot place.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.territory.territory_excluded(excluded, territory, , regions={'EU': frozenset({'AT', 'AX', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GF', 'GP', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MF', 'MQ', 'MT', 'NL', 'PL', 'PT', 'RE', 'RO', 'SE', 'SI', 'SK', 'YT'})})

Whether a use in `territory` falls in `excluded` (a region covers its members).

It fails closed on both sides. Whenever anything is excluded, an unstated
territory (`None`), a worldwide one, and one that is not a country code
all count as excluded. And a recorded code is read through its aliases: one
that names no country, no key of `regions` and not [`WORLDWIDE`](#lacing.territory.WORLDWIDE)
(a typo such as `"Franc"`) excludes every use, since nobody can tell what
it meant; a recorded `"WORLD"` excludes every use by definition.

```pycon
>>> territory_excluded({"KR"}, None), territory_excluded({"UK"}, "gb")
(True, True)
>>> territory_excluded({"KR"}, "Korea"), territory_excluded(set(), None)
(True, False)
>>> territory_excluded({"KR"}, "WORLD"), territory_excluded(set(), "WORLD")
(True, False)
>>> territory_excluded({"Franc"}, "US"), territory_excluded({"WORLD"}, "US")
(True, True)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.territory.unplaceable_codes(codes, , regions={'EU': frozenset({'AT', 'AX', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GF', 'GP', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MF', 'MQ', 'MT', 'NL', 'PL', 'PT', 'RE', 'RO', 'SE', 'SI', 'SK', 'YT'})})

The recorded `codes` no use can be placed against, as recorded: one that
is not an ISO code, an alias of one, or a region, and [`WORLDWIDE`](#lacing.territory.WORLDWIDE)
(everywhere). A restriction recording any of them excludes every use.

```pycon
>>> unplaceable_codes(["eu", "Franc", "uk", "WORLD"])
['Franc', 'WORLD']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
