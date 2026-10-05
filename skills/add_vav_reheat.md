---
name: add-vav-reheat
description: Add a multi-zone VAV system using the parent skill's bundled OpenStudio 3.11.0 scripts.
---

Prioritize configured, compatible NLR OpenStudio MCP through
`delegated-nlr-modeling`. After selecting the local fallback, use
`openstudio-vav-reheat-system-creator`. Its doctor, preflight,
reviewed-plan apply and saved-topology validation run through host tools.
Read the skill and input contract; execute the scripts without loading their
implementation or drafting per-object code. Follow its missing-input and failure
handling. Use workflow-state tools only when the active task needs them;
simulation/results are a separate handoff after the saved model is ready.
