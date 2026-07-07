# OpenStudio AI Marketplace Install Guide

This guide is for energy modelers who want to use OpenStudio AI inside Claude
Code, Codex, or another supported AI coding tool.

OpenStudio AI has two parts:

1. The plugin, which gives the AI assistant OpenStudio modeling skills,
   supporting references, and setup workflows.
2. The local runtime, which provides the `openstudio-ai-mcp` command that lets
   the assistant run OpenStudio modeling, simulation, result, SDK lookup, and
   workflow-state tools on your computer.

The plugin needs the local runtime to do real modeling work.

## What You Need

- A supported AI tool, such as Claude Code or Codex.
- Python available on your computer.
- OpenStudio installed if you want to run simulations or edit real models.
- The OpenStudio AI plugin installed from a marketplace or plugin folder.

You do not need to understand Python packages or MCP servers. The setup workflow
is designed to check these pieces for you.

## Setup Flow

After installing the plugin, run the OpenStudio AI setup workflow in your AI
tool.

For Claude Code, invoke the setup skill:

```text
/openstudio-ai:setup-openstudio-ai
```

For Codex, ask:

```text
Run the OpenStudio AI setup workflow.
```

The assistant should:

1. Check that Python is available.
2. Check that the `openstudio-ai-mcp` runtime command is available.
3. Run the included runtime doctor script.
4. If the runtime is missing, explain what is missing and ask before attempting
   installation.
5. Run `openstudio-ai doctor` when the command is available.
6. Tell you whether OpenStudio AI is ready for model loading, HVAC workflow
   support, simulation, results, SDK lookup, and workflow state tracking.

## Normal Outcomes

### Ready

The assistant reports that `openstudio-ai-mcp` is available and the doctor check
passes. You can start asking modeling questions, such as:

- Inspect this OpenStudio model.
- Add or modify a VAV reheat system.
- Run a simulation and summarize the results.
- Compare parametric study results.
- Retrieve annual site energy, EUI, unmet hours, or HVAC sizing outputs.

### Runtime Missing

The assistant reports that `openstudio-ai-mcp` is not available. This means the
plugin is installed, but the local runtime is not installed yet.

The assistant should explain the next step and ask before running any installer
script.

### OpenStudio Missing

The assistant reports that OpenStudio is not available. The plugin may still
load skills and knowledge, but model editing and simulations may not work until
OpenStudio is installed and visible to the runtime.

## What The Plugin Should Not Do Silently

The assistant should not silently install software, delete files, or change your
models. It should explain what it is about to check or install and ask for
approval when installation or repair is needed.

## Troubleshooting Language

When setup fails, ask the assistant to explain the issue in building-energy
modeling terms. Useful prompts include:

```text
Explain what failed and what I need to install, without Python jargon.
```

```text
Can I still use OpenStudio AI for planning and SDK lookup before simulation is ready?
```

```text
What is the next smallest setup step?
```
