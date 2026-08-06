---
name: sdk_simulation_results
description: OpenStudio Python SDK idioms for simulation files, OSW setup, SQL attachment, and result extraction.
version: 0.1.5
---

# SDK Simulation and Results Context

This pack documents source-observed simulation and SQL idioms. In OpenStudio AI,
actual simulation execution, polling, artifact retrieval, and result summaries
belong to MCP `sim_*` and `results_*` tools. Do not use host Python execution
to launch OpenStudio CLI, shell commands, or subprocesses.

Use this pack when explaining existing scripts, understanding result artifacts,
or drafting a non-executed review plan.

## Attach User-Supplied Weather and Design Days

Weather and design-day assets are model inputs. OpenStudio AI does not package
sample EPW or DDY files: require user-supplied paths, verify they exist, and
record their paths in the edit summary. Prefer a relevant MCP `model_*` tool
when it supports the requested model setup; use these SDK idioms only for a
scoped model-editing script.

```python
epw_path = "/path/to/weather.epw"
epw_file = openstudio.EpwFile(epw_path)
openstudio.model.WeatherFile.setWeatherFile(model, epw_file)
```

To merge design days from a user-supplied DDY file, check the IDF load result
before translating it back into model objects:

```python
ddy_path = openstudio.path("/path/to/design-days.ddy")
ddy_idf_opt = openstudio.IdfFile.load(ddy_path)
if not ddy_idf_opt.is_initialized():
    raise ValueError("Failed to load DDY file")

ddy_workspace = openstudio.Workspace(ddy_idf_opt.get())
ddy_model = openstudio.energyplus.ReverseTranslator().translateWorkspace(
    ddy_workspace
)
model.addObjects(ddy_model.objects())
```

This changes the model only; simulation execution, polling, artifacts, and
result retrieval remain MCP responsibilities.

## Forward Translate Model to IDF

```python
forward_translator = openstudio.energyplus.ForwardTranslator()
idf = forward_translator.translateModel(model)
idf.save(openstudio.path(f"{run_dir}/in.idf"), True)
model.save(openstudio.path(f"{run_dir}/in.osm"), True)
```

This translates an OpenStudio model to EnergyPlus IDF and saves both model and
IDF inputs. In OpenStudio AI, prefer MCP simulation workflows instead of doing
this inside host Python execution.

## Prepare WorkflowJSON

```python
model.resetSqlFile()
workflow = openstudio.WorkflowJSON()
workflow.setSeedFile("in.osm")
workflow.setWeatherFile(epw_name)
workflow.saveAs(os.path.abspath(str(osw_path)))
```

`resetSqlFile()` detaches a previous SQL result from the model before a new run.
`WorkflowJSON` defines the seed OSM and weather file for an OpenStudio CLI run.

## Attach SQL File to Model

```python
sql_path = openstudio.path(os.path.join(run_dir, "run", "eplusout.sql"))
if openstudio.exists(sql_path):
    sql = openstudio.SqlFile(sql_path)
    if sql.connectionOpen():
        model.setSqlFile(sql)
```

This checks for a SQL result file, opens it, verifies the connection, and
attaches it to the model.

## Query Severe and Fatal Errors

```python
query = "SELECT ErrorMessage FROM Errors WHERE ErrorType in(1,2)"
errs_optional = model.sqlFile().get().execAndReturnVectorOfString(query)
errs = errs_optional.get() if errs_optional.is_initialized() else []
```

This runs a direct SQL query against the attached result file. The query result
is optional.

## Load SQL and Read Annual End Uses

```python
sql = openstudio.SqlFile(openstudio.path(ep_sql_file_path))
gas_gj = sql.naturalGasTotalEndUses().get()
electricity_gj = sql.electricityTotalEndUses().get()
```

This loads an EnergyPlus SQL file and retrieves annual natural gas and
electricity totals in GJ. The reviewed code unwraps the optionals after checking
the SQL path exists. Generated scripts should check optionals when possible.

## Output Summary Reports

```python
reports = model.getOutputTableSummaryReports()
reports.addSummaryReport("AllSummaryAndSizingPeriod")
```

This requests EnergyPlus summary tables in future simulation output.

## MCP Routing Reminder

- Use `model_validate` before simulation when a copied model was edited.
- Use `sim_run` to start the simulation.
- Use `sim_status` until the job reaches `SUCCEEDED` or `FAILED`.
- Use `sim_artifacts` to retrieve output model, SQL, logs, and report artifact
  IDs.
- Use `results_query` and `results_summarize` for result retrieval and user
  summaries.
