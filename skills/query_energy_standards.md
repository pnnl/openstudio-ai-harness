---
name: query-energy-standards
description: Look up prescriptive building energy code requirements (equipment efficiency minimums, envelope U-factors and SHGC, lighting power densities, ventilation rates, economizer, energy recovery, fan power, pump and heat rejection requirements) for ASHRAE 90.1, 90.1 Appendix G (PRM), ASHRAE 189.1, ASHRAE 62.1 and IECC, using the Building Energy Standards Data MCP tools. Use when a question asks what a code version requires for a piece of equipment, assembly or space type, or when building an energy model that needs those values.
---

# Query Energy Standards

This skill describes how to query the Building Energy Standards Data (BESD) database through
the `building_energy_standards` MCP server, when to use it, and what the database does and
does not contain. For the full list of what is covered, see
[references/energy_standards_coverage.md](references/energy_standards_coverage.md).

## Server availability

The server is optional. The plugin registers it as the `besd-mcp` command, which must be
installed on the user's machine (it comes from the `building-energy-standards-data[mcp]`
package). If no `building_energy_standards` tools are available, say that the server is not
running and that `besd-mcp` is probably not installed or not on the PATH of the shell that
started the host; do not tell the user to run repository commands such as `uv sync`. Do not
answer from memory or substitute guessed values for a code requirement.

The database holds **tabulated prescriptive requirements** taken from building energy codes,
organized for use in energy simulation. It is read-only. It is not a copy of the standards'
text and it does not evaluate compliance.

## When to use it

Use these tools when the question is about a **numeric or categorical requirement in a code
version**, for example:

- "What is the minimum EER for an air-cooled chiller under 150 tons in 90.1-2019?"
- "What is the maximum roof U-factor in climate zone 5 for IECC 2021?"
- "What lighting power density does 90.1-2022 give for an open office?"
- "Which code versions require an air economizer in climate zone 3B?"
- "What outdoor air rate does 62.1-2016 give for a classroom?"

Do not use them for questions about the intent or text of a standard, compliance
interpretation, other standards (for example Title 24 or California codes), local
amendments, or code versions outside the ranges in the coverage reference. Answer those another way, or
say they are out of scope.

## Tools

The tool names below are the server's own. Your client may add a prefix (Claude Code shows
them as `mcp__building_energy_standards__<tool>`).

| Tool | Use it to |
|---|---|
| `get_candidate_tables` | Find which tables are relevant. Normally the **first** call |
| `get_table_metadata` | Get a table's columns, types, three sample rows and a description. Call before writing SQL |
| `get_unique_values` | See the distinct values in one or more columns, so filters match the stored format. Arguments: `table`, `column_names` (a list), optional `limit` (default 10, max 50), `where` |
| `run_sql` | Run a read-only `SELECT` or `WITH ... SELECT` |
| `list_tables` | List every available table name |
| `list_tables_with_descriptions` | List every table name with its description. Large; use only if candidate search fails |

## Workflow

1. **Find tables.** Call `get_candidate_tables` with whatever you can determine from the
   question. Leave a field out when unsure: a missing field is ignored, while a wrong value
   is penalized heavily.
2. **Inspect.** Call `get_table_metadata` on the top one to three results. Never write SQL
   against columns you have not seen.
3. **Check filter values.** Call `get_unique_values` (with a `limit` large enough to see every value) on each column you will filter on,
   especially `template`, climate zone, building category, equipment type and capacity
   columns. Stored formats are specific (see [Value formats](#value-formats)).
4. **Query.** Run a `SELECT` with `run_sql`. Select only the columns you need, and filter
   on the code version.
5. **Iterate.** On an error, read the message and fix the query. On zero rows, read the hint
   the tool returns (it suggests near matches for the failing filter), then retry. Stop after
   about three attempts and report what you tried.
6. **Answer.** State the value with its **unit**, the **code version**, and the **database
   table** it came from. Mention any conditions that came with the row (capacity range,
   equipment type, effective dates, annotation text).

## Using `get_candidate_tables`

Arguments, all optional except `domain`:

| Field | Values | Notes |
|---|---|---|
| `domain` | `envelope`, `hvac`, `lighting`, `ventilation`, `space_classification`, `support`, `unknown` | Always set. Fan, pump, economizer, energy recovery and heat rejection **system** requirements are under `hvac` |
| `topic` | `minimum_requirements`, `lighting_data`, `ventilation_data`, `space_types`, `materials`, `constructions` | |
| `system` | `boiler`, `chiller`, `furnace`, `heat_pump`, `unitary_ac`, `variable_refrigerant_flow_system`, `computer_room_ac`, `commercial_refrigerators_freezers`, `walkin_freezers_cooler`, `water_heaters`, `motor`, `heat_rejection`, `air_economizer`, `energy_recovery`, `fan_power`, `thermal_bridging`, and others | The strongest ranking signal. Set it whenever equipment is named |
| `sub_system` | `cooling`, `heating`, `ventilation`, `refrigeration` | Used to separate heat pump cooling from heating tables |
| `standard_family` | `ASHRAE_90_1`, `ASHRAE_62_1`, `ASHRAE_189_1`, `IECC` | Appendix G / PRM is **not** a family; use `compliance_path` |
| `standard_year` | e.g. `2019` | **Only set for lighting and ventilation questions** (see below) |
| `compliance_path` | `prescriptive`, `appendix_g` | `appendix_g` selects the 90.1 PRM tables (names ending `_prm`) |

How ranking works: each table is scored from its **name** against these fields. A match adds
the field's weight, a mismatch subtracts it, and a field the table does not have counts as a
small penalty. Tables that tie keep a fixed order, so a table that looks like the top result
may just have been listed first. Read the descriptions of all returned candidates instead of
trusting the first.

**Code version in the name or in a column.** Only the lighting (`level_3_lighting_<family>_<year>`)
and ventilation (`level_3_ventilation_62_1_<year>`) tables have the year in the table name,
so set `standard_year` for those. Equipment, envelope and system-requirement tables hold all
code versions of one family in a single table, with a `template` column. Do not set
`standard_year` for them: it would be scored against a missing value. Filter on `template`
in SQL instead.

## Value formats

Confirm with `get_unique_values`, but expect these patterns:

- **`template`** (the code version): `90.1-2019`, `90.1-PRM-2019`, `IECC-2021`, `189.1-2017`.
  The 90.1 tables also hold a pre-2004 `90-1975` template (note the different pattern). Not
  every table covers every version. Rows for one version can also be spread over several
  rows by equipment size, type or date.
- **Table family suffix:** `_90_1`, `_90_1_prm` (Appendix G), `_IECC`, `_189_1`. Choose the
  one that matches the requested standard. They are separate tables with separate data.
- **Climate zones differ by table family.** Envelope tables use a `climate_zone_set` column with
  values like `ClimateZone 5`, plus lettered subzones only where the code splits a zone
  (`ClimateZone 3A/3B/3C` in 90.1, `ClimateZone 4A/4B/4C` in IECC). A user's `5A` therefore
  maps to `ClimateZone 5`. System-requirement tables (for example air economizer) use a
  `climate_zone` column with values like `5A`. Check with `get_unique_values`.
- **Units** are in a separate column for lighting, ventilation and fan power allowance
  (`..._unit`) or in the column name, but equipment tables such as chillers have **no unit
  column** for capacity. Take the unit from the column description or `annotation`, or state
  that it is not recorded; never assume it.
- **Several efficiency metrics, one row.** Equipment rows carry many metric columns
  (for example chillers: `minimum_coefficient_of_performance`, `minimum_energy_efficiency_ratio`,
  `minimum_kilowatts_per_tons`, `minimum_integrated_part_load_value`) and only the ones the
  code defines for that row are non-null. Select the full-load and part-load columns
  together and report which are populated.
- **Equipment discriminators vary by table.** Chillers use `cooling_type`, `condenser_type`,
  `compressor_type` and `compliance_path` (`Path A` / `Path B`); unitary equipment uses
  `equipment_type`, `subcategory` and so on. Path A and Path B are alternatives with different
  full-load and part-load values, so show both or ask which applies.
- **Date ranges:** many equipment tables have `start_date` and `end_date`, stored as
  `m/d/yyyy` text with sentinels `9/9/1919` (no start) and `9/9/2999` (no end). Do not
  compare them as strings. A requirement can
  change on a date (for example when a test procedure or efficiency metric changed), so one
  equipment type may have more than one row. Say which applies or give both.
- **Capacity ranges:** `minimum_capacity` and `maximum_capacity` bound a row; `9999` means
  no upper bound and ranges are written non-overlapping (for example `0`-`149.99`, then
  `150`-`9999`). Find the row
  whose range contains the capacity in the question, and check how the range endpoints are
  treated (inclusive or exclusive) in the annotation or column description.
- **Empty (`NULL`) fields mean the code defines nothing there.** A `NULL` is not an unknown
  or missing value and not a `0`; do not guess it, borrow it from another row or edition, or
  ask the user for it. How to read it depends on the column:
  - *Threshold, limit or applicability columns* (for example the economizer
    `minimum_capacity` and `minimum_..._chilled_water_capacity_no_fan_cooling` columns, high-limit
    shutoff values, allowed-control-type flags): **no requirement** of that kind for the row's
    conditions. For example, 90.1-2025 climate zone 1A has an empty `minimum_capacity` because no
    economizer is required there. A column empty for every row of an edition, as the
    chilled-water capacity columns are for 90.1-2004 to 90.1-2013, means the edition does not
    define that threshold.
  - *Alternative efficiency metrics* (COP, EER, kW/ton, IPLV, thermal efficiency, and so on):
    the code expresses the requirement in another metric. Read the sibling columns; the
    requirement is "none" only if every metric column in the group is empty.
  - Anything else: report the value as empty and read the row's `annotation` before
    concluding anything.
  A `0` is a stored value, distinct from empty; read it with the row's `annotation`.

## `run_sql` rules and limits

- Only `SELECT` or `WITH ... SELECT` is accepted. Statements containing `DROP`, `DELETE`,
  `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `CREATE` or `REPLACE` are rejected.
- Output is JSON, **limited to the first 50 rows**; the total row count is reported. Use
  filters, `LIMIT`, or `COUNT(*)` instead of paging through large results.
- Only tables that `list_tables` returns are queryable. Lookup and support tables (space
  type mappings, materials, constructions, schedules, occupant data) are not exposed.
- `get_unique_values` returns at most 50 values per call.

## Answering well

- Give the number, unit, code version and table. Do not paraphrase the number.
- If several rows could apply, say which you chose and why, or show them.
- If the data does not contain the requested version or equipment, say so. Do not
  extrapolate from another version or standard.
- Many rows carry an `annotation` that names the source (for example
  `From 90.1-2019 Table 6.8.1-3`). Quote it when present. When it is absent, cite the
  database table name and do not invent a section number.
- Treat the result as a reference for modeling. For a compliance submission, confirm the
  value against the published standard.

## Using the values in an OpenStudio model

This skill only looks values up. It never edits a model; use the `openstudio_ai` MCP tools
and the HVAC skills for that. When a looked-up value feeds a model change:

- Confirm the standard, code version and (for 90.1) prescriptive vs. Appendix G path with
  the user when the request does not name them. Do not pick one silently.
- Convert units explicitly before use (for example kW/ton, COP, EER and IPLV are different
  metrics; OpenStudio efficiency fields are usually COP and SI). Say which metric the row
  provides and which one you set.
- Record the source (database table, `template`, row filters) next to the value in the
  workflow state or the final answer, so the choice is traceable.
- If no row matches the equipment or capacity, report that and ask. Do not fall back to
  another code version or a default without telling the user.
