# What the BESD database covers

Summary of the tables reachable through the MCP tools, for choosing where to look and for
recognizing what is out of scope. `list_tables` is the authority on what exists; if this
file and the tool disagree, trust the tool.

## Standards and versions

| Standard | Versions | Where the version is |
|---|---|---|
| ASHRAE 90.1 (prescriptive) | 1975 (`90-1975`, in some tables), 2004, 2007, 2010, 2013, 2016, 2019, 2022, 2025 | `template` column (`90.1-<year>`) in equipment, envelope and system tables; year in the table name for lighting |
| ASHRAE 90.1 Appendix G (PRM) | 2004, 2007, 2010, 2013, 2016, 2019, 2022, 2025 | `template` column (`90.1-PRM-<year>`); tables with a `_prm` suffix |
| ASHRAE 189.1 | 2009, 2011, 2014, 2017, 2020, 2023 | `template` column (`189.1-<year>`); year in the table name for lighting. Some system tables skip 2014 |
| IECC | 2006, 2009, 2012, 2015, 2018, 2021, 2024 | `template` column (`IECC-<year>`); year in the table name for lighting |
| ASHRAE 62.1 | 1999, 2004, 2007, 2010, 2013, 2016, 2019, 2022 | Year in the table name (ventilation only) |

Not every table covers every version of its standard. Check the `template` values in the
table with `get_unique_values`.

## Table groups

Table names end with the family suffix `_90_1`, `_90_1_prm`, `_IECC` or `_189_1`, except
lighting and ventilation, where the family and year are in the middle (for example
`level_3_lighting_90_1_2022`, `level_3_ventilation_62_1_2019`).

**Envelope** (`domain = envelope`)

| Table prefix | Content |
|---|---|
| `envelope_requirements` | Maximum U, C, F-factor and R-value, SHGC, minimum visible transmittance, by climate zone set, surface type and building category |
| `envelope_thermal_bridging_requirements` | Thermal bridging requirements (90.1 and IECC only) |

**Lighting** (`domain = lighting`)

| Table prefix | Content |
|---|---|
| `level_3_lighting_<family>_<year>[_prm]` | Interior lighting power density by space type, plus control requirements. One table per version. 90.1 has prescriptive and `_prm` versions; 189.1 and IECC have prescriptive only |
| `exterior_lighting` | Exterior lighting power allowances by lighting zone |

**Ventilation** (`domain = ventilation`)

| Table prefix | Content |
|---|---|
| `level_3_ventilation_62_1_<year>` | Ventilation rates by space type, ASHRAE 62.1 |

**HVAC equipment minimum efficiency** (`domain = hvac`, prefix `hvac_minimum_requirements_`)

`boilers`, `chillers`, `furnaces`, `heat_pumps_cooling`, `heat_pumps_heating`,
`unitary_air_conditioners`, `computer_room_air_conditioners`,
`variable_refrigerant_flow_systems`, `heat_rejection`, `water_heaters`, `motors`,
`commercial_refrigerators_freezers`, `walkin_freezers_coolers`.

Computer room air conditioners and variable refrigerant flow systems have no `_prm` table.
Heat pump cooling and heating are separate tables.

**HVAC system requirements** (`domain = hvac`, prefix `system_requirements_`)

| Table prefix | Content |
|---|---|
| `air_economizer` | Where an air economizer is required, allowed control types and high-limit set points |
| `energy_recovery` | Where exhaust air energy recovery is required, and minimum effectiveness |
| `fan_control` | Variable speed fan control and part-load fan power thresholds |
| `fan_power_allowance` | Fan power allowances by system type and capacity |
| `fan_power_allowance_pressure_drop_adjustment` | Pressure drop credits by device |
| `fan_power_allowance_altitude_correction_factor` | Altitude correction (90.1-2025 only) |
| `heat_rejection` | Heat rejection (cooling tower) system requirements |
| `hydronic_variable_flow` | Pump variable flow / variable speed drive requirements |

Most system-requirement tables have prescriptive 90.1, IECC and 189.1 versions; only
`air_economizer`, `energy_recovery` and `hydronic_variable_flow` also have a `_prm` version.

## Not available through the tools

These exist in the database but are not queryable through the MCP tools:

- Space type hierarchy and mapping tables (`level_1_*`, `level_2_*`)
- Support data: construction materials, performance curves, schedules, occupant data,
  standard templates and name tags (`support_*`)

Not in the database at all: the text of the standards, compliance rules and exceptions
beyond the stored `annotation` columns, standards other than those above, local
amendments, and data for other years.
