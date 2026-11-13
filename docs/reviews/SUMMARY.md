# HVAC and SDK release review

| Scope | Review outcome |
| --- | --- |
| Terminals (11a–11b) | In-place airflow and reheat control edits and VAV ↔ constant-volume no-reheat conversions approved. Reheat-terminal conversion remains separate. |
| Plant performance (12a–12i) | Boiler efficiency, parasitics, capacity and part-load limits, chiller COP, capacity and unloading, tower fan power and low-load controls, and district capacity approved. No open findings. |
| Plant topology (13a–13b) | Demand-free plant cleanup and boiler/chiller replacement with corresponding district water sources approved. Unsupported component-setpoint dispatch is rejected. |
| SDK packaging | Both hosts export shared guides and schemas once, rewrite skill links and hash Markdown. This restores 12 omitted guides. Reviewed size was 1,037,189 bytes per host against a 1,114,112-byte cap. |
| PR #47 weather preservation | Five edit and replacement workflows accept weather metadata from the reviewed companion EPW when the source has none. Unexpected metadata and resource changes remain rejected. |
