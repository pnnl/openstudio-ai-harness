# VAV source trace and phase 4 implementation boundary

Reviewed October 4, 2026 against the local `openstudio-standards` checkout at
commit `8bad404ef113019661fc0c14274a3554234219f7`. That checkout has unrelated
Rakefile/test-helper changes; the traced library files have no local changes.
Reference root: `/Users/xuwe123/github/openstudio-standards/lib/openstudio-standards`.
The scripts execute independently of that checkout and require OpenStudio 3.11.0.

## Conclusion

Our generic profile follows the air-system creation sequence and defaults in
`model_add_vav_reheat`. It is a bounded implementation, not a complete port of the
outer prototype dispatcher or every standards template. Phase 3 contained only
planning, so construction parity could not yet be established. The phase 4
implementation adds the missing equipment/controller settings and verifies the
saved system, including its actual supply order.

The exact dispatcher requested by the user is
[Prototype.Model.hvac.rb:21](/Users/xuwe123/github/openstudio-standards/lib/openstudio-standards/prototypes/common/objects/Prototype.Model.hvac.rb:21).
It always passes `reheat_type: 'Water'`, provides both water loops, and creates
missing plants. Our already agreed skill scope requires explicitly selected
existing plants. Gas, electric, DX, and no-reheat choices come from the inner
builder; central heating `None` is our explicit extension. Ruby defaults missing
central heating to gas, so we must never present `None` as equivalent behavior.
The dispatcher explicitly states `reheat_type: 'Water'` and
`fan_pressure_rise: 4.0` (lines 82 and 89).

Our coil roles also select plants independently. Ruby uses one hot-water-loop
argument for both main water heating and water reheat; providing that loop
selects main water heating. Combinations such as electric main heat with water
reheat, or different existing heating plants for those two roles, are explicit
extensions in our input contract. The all-water configuration is the direct
comparison with the requested outer dispatcher.

## Call graph

Names below are library methods; SDK constructors, setters, connections, unit
conversions, Ruby logging, and collection iteration are the leaves.

```text
model_add_hvac [VAV dispatcher, Prototype.Model.hvac.rb:21–92]
  model_get_zones_from_spaces_on_system [same file:567]
  model_get_return_plenum_from_system [same file:593]
  model_add_hw_loop [Prototype.hvac_systems.rb:42]
    Schedules.create_constant_schedule_ruleset [schedules/create.rb:113]
      Schedules.create_schedule_type_limits [same file:18]
    create_boiler_hot_water [Prototype.BoilerHotWater.rb:22]
  model_add_cw_loop [Prototype.hvac_systems.rb:480, WaterCooled only]
    model_add_curve [Standards.Model.rb:3567]
      model_find_object -> model_find_objects [same file:2573 -> 2389]
    prototype_apply_condenser_water_temperatures [Prototype.CoolingTower.rb:9]
      prototype_condenser_water_temperatures [same file:109]
  model_add_chw_loop [Prototype.hvac_systems.rb:228]
    chw_sizing_control [Standards.PlantLoop.rb:21; PRM override:619]
      Schedules.create_constant_schedule_ruleset [generic implementation]
    plant_loop_set_chw_pri_sec_configuration [Standards.PlantLoop.rb:57]
    pump_variable_speed_set_control_type [Standards.PumpVariableSpeed.rb:10]
    kw_per_ton_to_cop [Prototype.utilities.rb:414]
    model_add_waterside_economizer [Prototype.hvac_systems.rb:6640, optional]
  model_add_vav_reheat [Prototype.hvac_systems.rb:1830]
    model_add_schedule [Standards.Model.rb:2772]
      model_find_objects [same file:2389]
      model_add_vals_to_sch [same file:5759]
    standard_design_sizing_temperatures [Prototype.hvac_systems.rb:7]
    adjust_sizing_system [Prototype.SizingSystem.rb:9]
    Schedules.create_constant_schedule_ruleset [as above]
    create_fan_by_name [Prototype.Fan.rb:130]
      get_fan_from_standards [same file:90] -> model_find_object
      lookup_fan_curve_coefficients_from_json [same file:200]
        model_find_object
      create_fan_variable_volume_from_json [Prototype.FanVariableVolume.rb:154]
        create_fan_variable_volume [same file:104]
          PrototypeFan.apply_base_fan_variables [Prototype.Fan.rb:76]
    create_coil_heating_water [Prototype.CoilHeatingWater.rb:17]
    create_coil_heating_gas [Prototype.CoilHeatingGas.rb:13, optional]
    create_coil_heating_electric [Prototype.CoilHeatingElectric.rb:13, optional]
    model_set_central_preheat_coil_spm [Standards.Model.rb:6101]
    create_coil_cooling_water [Prototype.CoilCoolingWater.rb:15]
    create_coil_cooling_dx_two_speed [Prototype.CoilCoolingDXTwoSpeed.rb:13]
    ThermalZone.thermal_zone_get_outdoor_airflow_rate_per_area
      [thermal_zone/thermal_zone.rb:699]
      ThermalZone.thermal_zone_get_outdoor_airflow_rate [same file:633]
    air_terminal_single_duct_vav_reheat_apply_initial_prototype_damper_position
      [Prototype.AirTerminalSingleDuctVAVReheat.rb:11; template/building overrides]
      air_terminal_single_duct_vav_reheat_reheat_type
        [Standards.AirTerminalSingleDuctVAVReheat.rb:69, some overrides only]
```

The outer dispatcher does not request heat-pump boilers, district cooling, or
waterside economizing. Those helper branches are options outside the selected
VAV path; they are not implicitly enabled by our profile. In particular,
`waterside_economizer` defaults to `none`. Its optional helper uses a counterflow
HX; integrated placement is upstream of chillers with copied outlet setpoints,
while nonintegrated placement is parallel with a chiller override and possible
pump relocation. Neither branch is shipped in this pilot.

## Dispatch, plants, and object resolution

Ruby resolves zones through `space_names`, logs missing spaces/zones and
continues, and resolves the plenum through a space name. Our interface takes
explicit zone names/handles, blocks missing or duplicate references, requires
spaces and thermostats, and rejects zones that already have HVAC. The plenum
must be a distinct existing plenum zone. These stricter checks prevent partial
or accidental edits; they are intentional differences.

The outer dispatcher reuses plants named `Hot Water Loop` and `Chilled Water
Loop` without our explicit type gate. It takes a positive system chiller count
over a positive prototype count, otherwise one; tower count defaults to one.
WaterCooled creates centrifugal variable-speed open towers with two cells each.
A named existing CHW loop bypasses new condenser-loop creation entirely.

| Helper | Assumptions and options traced | Pilot behavior |
| --- | --- | --- |
| HW loop | 180 F supply, 20 R delta, 10 C minimum, scheduled outlet setpoint; variable pump unless Constant, 60 ft water head, motor 0.9, intermittent. Dispatcher selects NaturalGas boiler; loop helper passes efficiency 0.78, upper outlet limit 203 F, optional sizing factor. Boiler helper uses LeavingSetpointModulated, nominal PLR 0–1.2, optimum 1; obsolete leaving-design field is skipped for modern SDKs. | No plant creation; water ratings use selected existing plant exit temperature and delta. |
| CHW sizing | Generic 44 F supply and **10.1 R** delta; loop limits 1–40 C; scheduled outlet setpoint. PRM override uses outdoor reset 54 F at 60 F OA to 44 F at 80 F OA. | Existing plant controls are preserved. |
| CHW pumps | `const_pri` uses variable pump configured as constant flow, 60 ft. `const_pri_var_sec` uses generic common pipe (constant primary 15 ft, variable secondary 45 ft) or PRM heat-exchanger configuration. Pump control helper supplies Constant Flow, Riding Curve, VSD No Reset, or VSD DP Reset polynomial coefficients. | No pump, HX, or EMS creation. |
| Chillers | Electricity; AirCooled requires no CW, WaterCooled requires CW. Default COP = 3.517/1.188 for AirCooled, 3.517/0.66 otherwise. ConstantFlow, min PLR .15, max/optimum 1, unloading .25, lower CHW limit 36 F, entering condenser 95 F, per-chiller sizing factor round(1/count,2). | No chiller creation. |
| CW | Constant pump by default, intermittent, 49.7 ft head; tower variants single/two/variable speed. Dispatcher selects variable speed with free-convection fraction .125 and `VSD-TWR-FAN-FPLR` curve. Summer WB=>MDB design days, then companion DDY, then 78 F fallback provide wet bulb. | No CW creation or weather lookup. |
| CW sizing helper | Clamp design wet bulb to 68–80 F; leaving CW = min(85 F, wet bulb+10 F), range 10 R. Tower design values and outdoor wet-bulb-following SPM reflect this; EnergyPlus plant sizing remains 85 F/10 R. Operational minimum 70 F; maximum is raised to minimum if necessary. | Existing plant assumptions are not relabeled as our defaults. |

The selected plant helpers also add supply/demand bypass and endpoint adiabatic
pipes. More than three chillers in the HX primary/secondary configuration warns
about its EMS limit. These plant choices need a separate creation contract and
sizing evidence before we can offer full dispatcher parity.

## Air-system sequence and settings

The inner builder is
[Prototype.hvac_systems.rb:1830](/Users/xuwe123/github/openstudio-standards/lib/openstudio-standards/prototypes/common/objects/Prototype.hvac_systems.rb:1830).
Its insertion sequence is fan, heating coil, cooling coil, OA system, all at the
supply inlet. The resulting flow order is **OA → cooling → heating → fan → supply
outlet**. The independent validator checks this order after OSM reload.

| Object/helper | Settings implemented and independently checked |
| --- | --- |
| SizingSystem | Sensible load, autosized design OA, Coincident unless configured otherwise, heating maximum system airflow ratio .3, ZoneSum, DesignDay heating/cooling, all-OA flags false. Design temperatures 45/55/55/55/104/55 F for preheat/precool/main heat/main cool/zone heat/zone cool; humidity ratios .008/.008/.008/.0085 as appropriate. |
| Supply setpoint | Constant ScheduleRuleset at central cooling design temperature, Temperature/Continuous type limits 0–100 C, SetpointManagerScheduled on supply outlet. We use a system-specific schedule name and do not reuse an unrelated matching schedule. |
| Fan | VariableVolume; explicit total .62, motor .9, 4 inH2O = 996.35564 Pa; AlwaysOnDiscrete and VAV System Fans. JSON lookup adds motor-in-air fraction 1, Fraction minimum-flow method, .25 power minimum flow. Static-pressure-reset coefficients .040759894/.08804497/−.07292612/.943739823; JSON fifth coefficient null leaves SDK default zero. |
| Water heating | Plant demand branch first, air attachment next; rated inlet water = plant design exit, outlet = exit−delta. Main air rating preheat→central heat; reheat central heat→zone heat. Controller minimum water flow zero and convergence .1 set after connections. |
| Water cooling | Plant demand branch and air attachment; AlwaysOnDiscrete, autosized inlet water design temperature, CrossFlow exchanger, controller Reverse with minimum flow zero. Other design temperatures keep pinned SDK defaults. |
| Gas/electric heat | AlwaysOnDiscrete; gas burner .80 and zero on-cycle electric/off-cycle gas parasitics, electric efficiency 1. Capacity retains pinned SDK autosizing. |
| DX cooling | Only explicit approved DXTwoSpeed with Ruby's `OS default` behavior: pinned SDK curves. Residential Minisplit and PSZ/PTAC custom-curve branches are not offered. |
| OA/ventilation | FixedMinimum, autosized minimum flow, maximum fraction and economizer minimum dry-bulb reset; configured economizer and optional damper schedule, mechanical ventilation ZoneSum. |
| Availability | Loop operation schedule applied after OA attachment; CycleOnAny with 1800-second night-cycle runtime. Equipment and terminal schedules stay AlwaysOnDiscrete. |
| Reheated terminal | VAVReheat, Constant minimum fraction .3 unless configured, Normal damper heating action, 40 C maximum reheat temperature. Zone DesignDayWithLimit cooling, DesignDay heating, maximum heating fraction 1, explicit heating/cooling design temperatures. |
| No-reheat terminal | VAVNoReheat and Constant minimum fraction; cooling method/temperature and heating maximum fraction set. Existing zone heating method and design temperature are preserved, as in Ruby. |
| Return plenum | Each selected zone connects to the explicitly resolved plenum. Saved validation checks plenum zone and number of inlet branches. |

The fan data is in `standards/ashrae_90_1/data/ashrae_90_1.fans.json:268` and
`ashrae_90_1.curves.json:8279`. Pressure **is converted from inH2O** inside
`create_fan_variable_volume_from_json`, despite misleading Pa parameter comments
in higher-level fan helpers. Curve lookup only copies coefficients into the fan;
it does not install the curve object's output bounds.

Schedule resolution in Ruby first reuses a named schedule; missing standards
schedule data logs an error and falls back to AlwaysOnDiscrete. Its schedule
factory loads Constant/Hourly day values, seasonal dates, weekday/weekend rules,
and design-day schedules with interpolation No. Our script selects existing
schedules by exact identity and blocks missing/unsuitable references. It does
not generate schedules from standards datasets or silently substitute one.
Existing schedule type limits are checked; all time-series values are not.

## Polymorphic assumptions and deferred standards processing

The generic preheat callback is a no-op. The PRM override at
`standards/ashrae_90_1_prm/ashrae_90_1_prm.Model.rb:817` finds the highest winter
heating thermostat setpoint (22.2 C fallback), subtracts 20 F, and installs a
coil-outlet scheduled setpoint. That override is not part of this generic profile.

The OA-per-area helper sums space requirements using Sum or Maximum, including
people, area, fixed flow, and ACH, then divides by floor area. Generic initial
damper position ignores that result and uses .3. The script does not perform an
unused division, and does not claim a ventilation-based damper calculation.

All prototype damper override definitions were examined. DOE reference and
90.1-2004/2007 use .3. 90.1-2010/2013/2016/2019 distinguish gas/electric (.3) from
water/other (.2) via reheat-coil type. NZE/ZE AEDG also distinguish water/electric/
gas. Several building overrides choose .2 for newer templates and .3 otherwise;
Outpatient has named-zone exceptions up to 1.0 and several intermediate fractions.
This library therefore does not have one universally correct VAV minimum.

Later standards application can revise fan efficiencies/pressure, minimum damper
positions, OA sizing and SAT reset. Those post-sizing/compliance transformations
are not called by the selected inner creation method and are not included here.
Our profile remains an explicitly approved generic initial construction profile.

## Verification and known limits

Phase 4 checks 32 combinations of main heating (Water/Gas/Electric/None), cooling
(Water/DX), and reheat (Water/Gas/Electric/None), plus multiple zones, schedules,
noncoincident sizing, economizer override, and return plenum. Failure checks
cover stale/tampered plans, wrong SDK, rejected or ineffective setters, and a
competing destination writer. Saved models are validated before exclusive atomic
publication. Repeating apply refuses the existing destination.

SDK-generated object UUIDs differ between new runs; determinism here means the
resolved engineering settings and topology, not byte-identical new OSMs. Routine
apply output lists engineering objects and counts, excluding generated nodes and
connectors to reduce agent context. Token savings will be measured in phase 5.

Native hydronic and electric/DX five-zone design-day runs verify positive fan,
terminal, reheat, and cooling sizing and no EnergyPlus severe/fatal or node
connection errors. The disposable copies exclude unrelated service-water
equipment. Remaining seed/default warnings (28 hydronic, 29 electric/DX) cover
inherited schedules, weather location, unused/comfort/daylighting objects,
Constant terminals ignoring the alternate fixed-flow field, default zone air
distribution effectiveness, and unavailable meters/monthly reports. Hydronic sizing uses
explicit fixture plants with district sources; it validates our water-coil
connections, not the deferred boiler/chiller/tower creation branches. Annual
performance, code compliance, ventilation adequacy, and native Windows/Linux
execution remain outside this evidence. See the phase plan and verification
JSON for commands, measurements, and review status.
