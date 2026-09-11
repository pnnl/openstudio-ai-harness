---
name: curate-learning
description: Curate local OpenStudio AI learning evidence without disrupting the active modeling workflow.
---

# Curate Learning

Use this skill only to curate local OpenStudio AI learning evidence. It must not
change an OpenStudio model, approve a candidate, or delete a record.

Before curation, call `runtime_plugin_compatibility`. This workflow requires
MCP interface contract `4`; stop and ask the user to refresh the plugin/runtime
if the compatibility result is not OK.

Run `openstudio-ai learning curate --json` to create unreviewed lesson and
measure candidates from local evidence. Run
`openstudio-ai learning propose-measures --json` when the task is limited to
repeated successful script logic. Summarize candidate IDs and evidence counts to
the parent workflow.

When the host supports subagents, this is a good bounded delegation: the curator
may read learning records and run the CLI, but it must not call
`learning_review_candidate` or `learning prune --yes`. In hosts without
subagents, invoke it after the modeling work is complete.

Use `openstudio-ai learning prune-preview --json` to report stale unapproved
candidates. Never run `learning prune --yes` unless the user explicitly asks to
delete the displayed candidate IDs.
