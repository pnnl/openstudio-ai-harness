# Runtime Learning

Learning guidance in exported Claude/Codex harnesses is candidate-only.

Allowed runtime outputs:

- candidate reusable recipes;
- candidate measures;
- session lessons;
- notes for future evals.

Runtime agents must not directly edit trusted `knowledge/`, `skills/`,
`measures/approved/`, or MCP tools.

The plugin does not currently provide candidate storage or an executable
learning pipeline. Use the skill-local schemas to draft a reviewable candidate,
but do not claim that it was persisted. A future MCP-backed workflow must own
candidate storage and validation before hosts can capture candidates directly.
