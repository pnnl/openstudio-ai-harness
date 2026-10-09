# Main-supply water heating to electric conversion

Use [the schema](coil_conversion.schema.json). Example explicit configuration:

```json
{
  "output_model_path": "/absolute/path/electric.osm",
  "coil": {"name": "Office Main Heating Coil"},
  "efficiency": 0.98,
  "temperature_control": "Preserve",
  "sizing": "Autosize",
  "reference_policy": "Reject"
}
```

The efficiency illustrates a choice; it is not a default. `temperature_control:
Preserve` is the only supported control mode. Conversion adds no outlet manager
or temperature schedule. Existing outlet managers stay in place. Where the outlet
is unmanaged in the OSM, OpenStudio retains its generated supply-air tracking,
including downstream fan heat compensation. Before/after translated controls are
recorded in `impact` and independently checked after saving. Explicit fixed
preheat/setpoint changes are outside this conversion contract; old
`outlet_temperature_c` configurations are rejected and must be replanned.
The source water controller must use Normal Temperature/Flow control, zero minimum
flow and normal sensor/actuator locations (or native defaults). Other controller
strategies need separate coverage. Electric capacity is autosized;
the original air-system and plant sizing settings are unchanged. The input coil
must have a dedicated single-coil plant demand branch and direct main-supply
connections. Cooling, gas/DX, OA/unitary/terminal coils and reference transfer are
not implemented.

Review `impact.before`, `impact.after`, affected zones, source-plant remaining
loads, removed-object counts and controller metadata removal. Coil name and
availability are retained. Coil metadata retains its identity and features with
its owner pointer changed to the new electric coil. External references to the
removed coil, controller or water nodes prevent preflight readiness. The output
report maps original and new coil identities and reports its preserved outlet controls.
Never reuse removed handles in subsequent plans or workflow-state records.

The source plant and its supply equipment/pumps remain even if unserved. The
current HVAC remover excludes plant deletion. Review cleanup separately, carry
the output and its `<stem>/` companions together, then request sizing/simulation.
