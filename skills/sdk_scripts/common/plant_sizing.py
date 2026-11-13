"""Read effective translated plant-sizing controls without changing the model."""


def sizing_context(model, sdk, workspace):
    optional = model.getOptionalSimulationControl()
    control = optional.get() if optional.is_initialized() else None
    defaulted = control is None or control.isDoPlantSizingCalculationDefaulted()
    objects = workspace.getObjectsByType(sdk.IddObjectType("SimulationControl"))
    effective = None
    if len(objects) == 1:
        index = objects[0].iddObject().getFieldIndex("Do Plant Sizing Calculation")
        if index.is_initialized():
            raw = objects[0].getString(index.get())
            value = raw.get().lower() if raw.is_initialized() else ""
            if value in ("yes", "no"):
                effective = value == "yes"
    return dict(
        design_day_count=len(model.getDesignDays()),
        sizing_period_count=len(model.getSizingPeriods()),
        plant_sizing_flag_defaulted=defaulted,
        requested_plant_sizing=(
            None if defaulted else control.doPlantSizingCalculation()
        ),
        effective_plant_sizing=effective,
        translated_control_verified=effective is not None,
    )


def require_plant_sizing(planned, context):
    """An input edit is allowed; an unconfigured sizing run is not ready to simulate."""
    planned["impact"]["plant_sizing"] = context
    if (
        context["effective_plant_sizing"] is not True
        or context["sizing_period_count"] == 0
    ):
        planned["simulation_ready"] = False
        planned["warnings"].append(
            "Explicit Autosize lacks a verified plant-sizing setup: translated sizing is off/unverified or no sizing periods exist. Marked not ready to simulate; configure sizing periods and plant sizing explicitly. EnergyPlus can still size some fixed-flow cases without a plant-sizing run, so this is a conservative readiness guard, not a guaranteed failure. Controls are unchanged"
        )
