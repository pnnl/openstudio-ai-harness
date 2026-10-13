"""Bounded schedule ranges and nominal space/zone ventilation evidence."""

from common.outdoor_air import ref


def stable_evidence(value):
    """Geometry aggregates can differ in their last bits across SDK reloads."""
    if isinstance(value, dict):
        return {k: stable_evidence(v) for k, v in value.items()}
    if isinstance(value, list):
        return [stable_evidence(v) for v in value]
    return float(format(value, ".12g")) if type(value) is float else value


def schedule_bounds(schedule):
    constant = schedule.to_ScheduleConstant()
    limits = schedule.scheduleTypeLimits()
    unit = limits.get().unitType() if limits.is_initialized() else None
    if constant.is_initialized():
        numbers = [constant.get().value()]
    else:
        ruleset = schedule.to_ScheduleRuleset()
        if not ruleset.is_initialized():
            return dict(
                ref(schedule),
                minimum=None,
                maximum=None,
                unit_type=unit,
                verified=False,
            )
        ruleset = ruleset.get()
        days = [ruleset.defaultDaySchedule()] + [
            r.daySchedule() for r in ruleset.scheduleRules()
        ]
        for suffix in (
            "SummerDesignDay",
            "WinterDesignDay",
            "Holiday",
            "CustomDay1",
            "CustomDay2",
        ):
            if not getattr(ruleset, "is" + suffix + "ScheduleDefaulted")():
                days.append(
                    getattr(ruleset, suffix[0].lower() + suffix[1:] + "Schedule")()
                )
        numbers = [x for day in days for x in day.values()]
    return dict(
        ref(schedule),
        minimum=min(numbers) if numbers else None,
        maximum=max(numbers) if numbers else None,
        unit_type=unit,
        verified=bool(numbers),
    )


def zone_requirements(loop):
    zones = []
    for zone in sorted(
        loop.thermalZones(), key=lambda x: (x.nameString(), str(x.handle()))
    ):
        spaces = []
        for space in sorted(
            zone.spaces(), key=lambda x: (x.nameString(), str(x.handle()))
        ):
            oa = space.designSpecificationOutdoorAir()
            people = list(space.people())
            if space.spaceType().is_initialized():
                people += list(space.spaceType().get().people())
            occupants = []
            for person in sorted(
                {str(p.handle()): p for p in people}.values(),
                key=lambda x: str(x.handle()),
            ):
                schedule = person.numberofPeopleSchedule()
                occupants.append(
                    dict(
                        ref(person),
                        occupancy_schedule=(
                            schedule_bounds(schedule.get())
                            if schedule.is_initialized()
                            else None
                        ),
                    )
                )
            row = dict(
                space=ref(space),
                design_people=space.numberOfPeople(),
                floor_area_m2=space.floorArea(),
                volume_m3=space.volume(),
                people=occupants,
                outdoor_air=None,
                nominal_oa_m3_s=0.0,
            )
            if oa.is_initialized():
                oa = oa.get()
                terms = dict(
                    people=space.numberOfPeople() * oa.outdoorAirFlowperPerson(),
                    area=space.floorArea() * oa.outdoorAirFlowperFloorArea(),
                    fixed=oa.outdoorAirFlowRate(),
                    ach=space.volume() * oa.outdoorAirFlowAirChangesperHour() / 3600,
                )
                schedule = oa.outdoorAirFlowRateFractionSchedule()
                row["outdoor_air"] = dict(
                    ref(oa),
                    method=oa.outdoorAirMethod(),
                    per_person_m3_s=oa.outdoorAirFlowperPerson(),
                    terms_m3_s=terms,
                    fraction_schedule=(
                        schedule_bounds(schedule.get())
                        if schedule.is_initialized()
                        else None
                    ),
                )
                row["nominal_oa_m3_s"] = (
                    sum(terms.values())
                    if oa.outdoorAirMethod() == "Sum"
                    else max(terms.values())
                )
            spaces.append(row)
        zones.append(
            dict(
                zone=ref(zone),
                multiplier=zone.multiplier(),
                nominal_oa_m3_s=sum(s["nominal_oa_m3_s"] for s in spaces)
                * zone.multiplier(),
                spaces=spaces,
            )
        )
    return stable_evidence(
        dict(
            zones=zones,
            zone_count=len(zones),
            nominal_design_oa_m3_s=sum(z["nominal_oa_m3_s"] for z in zones),
            basis="Nominal design people and Sum/Maximum space OA; zone multiplier applied once; excludes time-varying OA schedules, coincidence, distribution effectiveness and exhaust",
        )
    )
