# CalBEM flash talk: From an LLM to a verifiable modeling workflow

Status: talk and recording plan drafted October 4, 2026. The proposed lighting
case has not been executed or validated. No energy results are asserted here.

## Message and title

Suggested subtitle under the program title, “Agentic AI Foundations and
Applications for BEM”: **From Prompts to Verified Models: The AI Harness**.

One takeaway: **The LLM proposes actions; the harness connects those actions to
engineering tools, checks, and evidence.**

The talk teaches one foundation concept and demonstrates it through one familiar
modeling task. Avoid a survey of AI architectures or a catalog of plugin features.

## Five-minute run of show

| Time | Screen | Purpose |
| --- | --- | --- |
| 0:00–0:25 | Slide 1: “Can you trust the model change?” | Start with an engineer's question. |
| 0:25–1:40 | Slide 2: LLM → prompt → context → harness | Explain the foundation through the lighting example. |
| 1:40–2:10 | Slide 3: inspect → change → run → verify | Introduce the OpenStudio AI plugin and the controlled case. |
| 2:10–4:10 | Embedded two-minute video | Show an actual before/after workflow and its evidence. |
| 4:10–4:50 | Slide 4: “Inspect the change. Trace the result.” | State the limits and the practical takeaway. |
| 4:50–5:00 | Hold closing slide | Timing margin. |

Four slides plus the video are sufficient. Slides should contain a diagram or
one sentence, with detailed definitions in the spoken track.

## Foundation slide

These are complementary layers, not replacements for each other or a strict
historical sequence. Use progressive reveals so the audience sees one layer at
a time.

| Layer | Plain-language question | Same BEM example at every layer |
| --- | --- | --- |
| LLM | What generates the proposed response or action? | A model trained on patterns in language and other data generates text and proposed tool calls. Fluent output alone does not establish engineering correctness. |
| Prompt engineering | What exactly are we asking it to do? | Reduce office lighting power density from 10 to 7 W/m² and compare annual energy. |
| Context engineering | What information does it need, and at which step? | Supply the actual space and lighting assignments before editing, relevant SDK guidance during editing, and simulation logs and SQL outputs when interpreting results. |
| Harness engineering | How does the work execute, get checked, and retain evidence? | Coordinate tools and workflow steps, preserve the baseline, validate the edit, run the engine, and associate results with the right model variant. |

Spoken analogy: an engineering assignment needs a clear scope, the right project
information, and an execution and checking process. A better instruction alone
does not supply all three.

## Spoken draft outside the video

**Opening, 0:00–0:25**

“Suppose I ask AI to reduce lighting power in an OpenStudio model and report the
energy savings. A convincing answer is easy to read. But as modelers, we need to
know: which spaces changed, did the simulation finish, and where did the numbers
come from? That is the problem I want to focus on today.”

**Foundation, 0:25–1:40**

“A large language model generates responses from patterns learned during
training. It can interpret a request and propose steps, but that does not make
its answer a verified simulation result.

“Prompt engineering makes the request precise: reduce office lighting power
density from ten to seven watts per square meter, then compare annual energy.

“Context engineering supplies the right information at the right step. Before
editing, the agent needs the actual lighting assignments. While editing, it
needs the relevant OpenStudio methods. After simulation, it needs the logs and
results, rather than guessing the savings.

“Harness engineering organizes how that work happens. It connects the model to
tools and workflow instructions, preserves state, and checks the outputs. Think
of it as the execution and checking process around the AI.

“These layers work together: the request, the information, and the process.”

**Demo setup, 1:40–2:10**

“The OpenStudio AI plugin brings that workflow into an AI assistant. Here is a
controlled lighting retrofit on a small office model. We preserve the baseline,
change one input, run both cases, and trace the comparison back to simulation
outputs. The video compresses the waiting time; the results come from the
recorded runs.”

**Closing, 4:10–4:50**

“The useful output is the model change, the completed run, and the evidence
connecting them. Lower lighting power also changes internal heat gains, so we
look at heating and cooling as well as lighting electricity.

“This demonstration is a bounded task, not proof that every modeling problem
can be automated. Engineers still define the assumptions and judge the results.
The practical question to ask of an AI modeling workflow is: can I inspect the
change and trace the result? That is what the harness is designed to support.”

Rehearse with the actual video. Trim spoken explanations before shortening the
results frame. Match the setup's claims to what the final recording proves.

## Two-minute video storyboard

| Video time | Visible action and evidence | Suggested narration |
| --- | --- | --- |
| 0:00–0:12 | Small-office geometry or recognizable model summary; one short user request. | “The task is a lighting retrofit in an existing office model.” |
| 0:12–0:32 | Actual inspection output: targeted spaces, effective LPD, lighting schedules, baseline file. Overlay: **Context: inspect first**. | “The agent checks which lighting objects serve these spaces and records the starting assumptions.” |
| 0:32–0:50 | Proposed scope and engineer approval; saved variant and concise change table, 10 → 7 W/m². Overlay: **Harness: controlled edit**. | “We approve a scoped change. The baseline stays available, and the edited model is checked before simulation.” |
| 0:50–1:12 | Baseline and variant jobs, completion status, actual warning summary and retained SQL/log artifacts. Label cuts **Simulation wait shortened**. | “OpenStudio and EnergyPlus run both cases. The workflow checks completion and retains the outputs.” |
| 1:12–1:42 | Readable before/after table: lighting electricity, heating by fuel, cooling electricity, total site EUI. Show units, model names, and result references. | “The comparison comes from simulation outputs. Lower lighting power changes both electricity use and internal heat gains.” |
| 1:42–2:00 | Hold results beside links to baseline OSM, variant OSM, change report, SQL and logs. Overlay: **Verify: inspect the change, trace the result**. | “The deliverable includes a model you can inspect and results you can trace.” |

Keep tool details collapsed except for one short inspection and one result
reference. Use large text, a fixed crop, and a visible cursor. Record a genuine
workflow, then edit its waiting time; do not animate fabricated results. Use
captions and plan for live narration so the talk works without room audio.

## Proposed recording test case

**Engineering question:** What happens to annual lighting, heating, cooling,
and total site energy when office LPD changes from 10 to 7 W/m²?

Prepare a small, already runnable office model with a documented California EPW,
annual run period, functioning HVAC, and known lighting assignments. Use a demo
fixture with 10 W/m² effective LPD in every target office space, no daylighting
or other variable lighting controls, and fixed lighting schedules. Document any
non-office spaces and exclude them explicitly. Resolve shared definitions and
space-level overrides before recording. This is a controlled demonstration,
not a Title 24 compliance claim or a calibrated prediction for a real building.

Keep geometry, envelope, weather, schedules, occupancy, equipment, and HVAC input
settings unchanged. State whether HVAC is autosized: unchanged sizing inputs do
not necessarily mean unchanged computed capacities when internal gains change.
Prefer a model with already fixed capacities for this controlled comparison.

### Recording prompts

First prompt:

> Inspect this office model and prepare a lighting retrofit comparison. Identify
> the target office spaces, effective lighting power density, lighting schedules,
> and any shared definitions or overrides. Propose a change from 10 to 7 W/m²
> only in those spaces. Preserve the source model. Show the scope and assumptions
> before editing, and wait for my approval.

Second prompt, after checking the scope:

> Apply the proposed change to a new variant. Verify each target space reaches
> 7 W/m² and report any other changed inputs. Run annual baseline and variant
> simulations using the same weather and run settings. Compare lighting
> electricity, heating by fuel, cooling electricity, and total site EUI with
> units and links to the corresponding SQL and logs. Report completion status
> and warnings. Separate observed results from explanations that need more
> investigation.

### Pass criteria before filming

1. The source file hash is unchanged; baseline and variant have distinct IDs or
   filenames, and each result is associated with its correct model and job.
2. Effective LPD equals 10 W/m² before and 7 W/m² after in every target space.
   Non-target loads and input settings are unchanged; clone-related handle or
   serialization changes are distinguished from engineering input changes.
3. Both annual runs complete successfully. There are no fatal or unresolved
   severe errors; remaining warnings are reviewed and disclosed as appropriate.
4. Every displayed result matches its corresponding SQL output, with compatible
   units and the same floor-area basis for EUI. Missing metrics are reported as
   unavailable, never as zero.
5. With the selected fixture's fixed schedules and no lighting controls, target
   lighting electricity should decrease approximately 30%. Use a proposed
   acceptance band of 29–31% and investigate departures before filming. If the
   whole-building total includes unchanged non-office lighting, its decrease
   need not be 30%; use a fixture with all interior lighting targeted or obtain
   appropriate target-specific outputs.
6. Heating, cooling, and total energy changes are read from the simulation.
   Their signs and magnitudes are not predefined pass criteria. Lower lighting
   reduces heat gains, but climate, operation, and system response govern the
   annual outcome. Do not promise 30% whole-building savings.
7. A repeat edit starting from the original reaches the same target inputs.
   Applying the request to the already edited variant must not reduce LPD again
   to 4.9 W/m²: the instruction specifies an absolute target.

These are proposed acceptance checks, not completed test results. Record actual
values, runtimes, warnings, versions, and artifact locations after rehearsal.

## Recording readiness and backup

- Pin and verify the installed plugin, runtime, OpenStudio SDK, and CLI versions.
  The checked-in harness and generated distribution currently document different
  versions; do not infer the installed runtime from either README alone.
- Rehearse the complete workflow on a fresh copy. Keep the source model, EPW,
  prompts, edit report, run settings, SQL outputs, logs, and final comparison.
- Use local video playback, ideally embedded in the presentation. Check it on
  the presentation machine, including caption readability and playback duration.
- Keep a static results screenshot as the video backup. Insert measured energy
  values only after the case passes validation.
- No automated checks were run for this planning artifact. Manual review checked
  the timeline totals, the storyboard's 120-second duration, engineering scope,
  and alignment with documented capabilities. A runtime test remains necessary.

## Sources and claim boundaries

- CalBEM's [program](https://calbem.ibpsa.us/) lists the talk as “Agentic AI
  Foundations and Applications for BEM.” Its practitioner emphasis supports the
  proposed framing; the five-minute allocation comes from the speaker's request.
- Anthropic defines context engineering around the “optimal set of tokens
  (information)” in [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
  “What information, when” is a presentation shorthand for selection and timing,
  not a definition limited to timing.
- Anthropic recommends obtaining “ground truth” from the environment in
  [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).
  The proposed execution/checking loop follows that principle.
- Local [README](../README.md) documents “model lifecycle, simulation, results,
  SDK lookup” and workflow state. [HANDOFF](../HANDOFF.md) states that diagnostic
  tools are “planned for contract `6`”; this talk does not present those planned
  tools as already demonstrated capabilities.
- [SDK editing instructions](../skills/openstudio_sdk_model_editor.md) explicitly
  cover lights, load densities, schedules, and space-level summaries.
  [Result-query instructions](../skills/query_results.md) route SQL-backed
  retrieval through MCP. The [smoke tests](../tests/test_mcp_openstudio_smoke.py)
  cover simulation completion and SQL results, but do not validate this proposed
  lighting retrofit case.
