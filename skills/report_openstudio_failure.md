---
name: report-openstudio-failure
description: Capture and automatically submit sanitized unexpected OpenStudio AI execution failures to pnnl/openstudio-ai-harness, retaining local drafts and reproduction gaps when submission is unavailable. Use before recovery and on resume; exclude expected readiness questions and general feature requests.
---

# Report OpenStudio Failure

The selected policy automatically submits qualifying failures to
`https://github.com/pnnl/openstudio-ai-harness`. No additional per-incident
confirmation is needed for the sanitized diagnostic payload.
Issues are created under your own authenticated GitHub account.
The helper uses your existing GitHub CLI login. This authorization does not include
model/CSV/EPW attachments, transcripts, credentials, comments on
existing issues, or security disclosures. General preview-approved issues for
the plugins repository still use `github-issue-submitter`.

## Capture before recovery

Unexpected SDK exceptions, inconsistent repeated plans, saved validation or
translation failures, crashes and broken provider/plugin integration qualify.
Missing selections, supported-scope refusals, cancellation, version/environment
readiness questions and `requires_preparation` do not. An explicit user bug report
can qualify an otherwise expected outcome. Preserve the original incident even
if a supported workaround succeeds; do not repeat a mutation to obtain evidence.

Run from the project root with host Python. The standalone stdlib helper at
`scripts/report_failure.py` works without OpenStudio, MCP or the plugin's `sdk/`.
State defaults to `.openstudio_ai_failures/`. Use the same absolute `--state-dir`
and `OPENSTUDIO_AI_FAILURE_DIR` for SDK commands if work runs from another CWD.
The helper never reads a user model or attachment for submission.

1. Reuse `failure_receipt` from the failed bundled command. For MCP errors,
   doctor/probe crashes, integrity failures or killed processes without a receipt,
   write a local event following [the event contract](references/event.schema.json).
   Include operation/stage/provider, expected and actual behavior, exit code,
   sanitized invocation, plugin/SDK/host versions, minimal numeric configuration,
   relevant component counts/connections, attempts and publication state. List
   private model/zone/system names in `private_values` for consistent aliasing.
   Do not put secrets in the event intentionally. Mark security-sensitive incidents
   `security_sensitive: true`; they remain local for a private maintainer channel.
2. Capture the event and submit the returned receipt:

   ```bash
   python /absolute/skill/scripts/report_failure.py --state-dir /project/.openstudio_ai_failures capture --event /project/work/failure-event.json
   python /absolute/skill/scripts/report_failure.py --state-dir /project/.openstudio_ai_failures submit --receipt /project/.openstudio_ai_failures/<fingerprint>/receipt.json
   ```

   Capture creates a sanitized receipt and a separate private `private.json`
   containing the original exception message/traceback, which stays local.
   Submit writes the exact fallback
   issue JSON before network access, checks repository templates and searches
   open/closed issues for the fingerprint. It creates at most one issue, or links
   a duplicate without editing/commenting. Use existing `gh` authentication on
   `github.com`; never collect or echo tokens. If `gh` is unavailable, retain the
   draft rather than inventing another upload path.
3. Add ordered synthetic reproduction steps when verified. Never claim a private
   building/path is an accessible reproducer. Otherwise keep
   `not_independently_reproducible_yet` and identify the equivalent synthetic input
   or additional evidence needed. A report can still be useful without uploading
   private inputs. Report attribution remains provisional for upstream failures.
4. Return issue URL or local receipt/draft and its reason. Store the receipt/issue
   under `failure_incidents[fingerprint]` in the workflow blackboard when active.
   Continue otherwise safe modeling recovery without changing provider priority.

## Resume, privacy and stopping rules

Run `pending` on resume using the same state directory and submit pending receipts
before a new modeling step. The list is bounded; `total` indicates additional
receipts. A fingerprint binds operation/stage/provider, bundle/release and normalized
failure signature, excluding transient object IDs and private paths. Retries and
workarounds retain the first evidence and receipt.

Submission requires a successful duplicate lookup. Standard Markdown bug templates map summary, reproduction, expected behavior,
environment and evidence sections plus their labels. New issue forms/templates
that have no maintained field mapping leave a draft with
`repository_template_requires_mapping`; do not bypass them. Network/auth failures
retain `pending`. An uncertain POST is durably recorded, checked for a matching
issue, and never automatically posted again—even if search indexing is delayed.
`busy` means a local submission lock is held; a crashed process can leave one.
Verify the process has stopped before manually removing its lock; a persisted
`submitting` state still prevents a second POST.

Exception messages are published only as fixed `error_code`/message templates.
Public tracebacks contain at most 12 plugin file/function/line locations verified
against shipped source; raw messages, traceback text, source lines and locals
stay local. If SDK sources are missing, omit frames. Legacy receipts return
`requires_recapture` without contacting GitHub; do not automatically recapture
submitted or uncertain incidents as new identities. Preserve those records for
manual reconciliation. Pending legacy incidents can be captured afresh from
their local evidence using the current helper.

Other allowlisted fields use bounded text, redacted paths/URLs, credentials and
quoted values, and aliased private settings. Unknown event fields are dropped.
Never copy raw exceptions into observations, reproduction steps or workarounds;
use fixed error codes and verified synthetic instructions instead. This is a
diagnostic filter, not a guarantee arbitrary private prose
can be made public safely: supply `private_values`, minimal factual excerpts and
synthetic inputs; use `security_sensitive` when public reporting is inappropriate.
Never attach raw model/config/plan/log files or use the helper to submit an edited
free-form draft. Local state is private and git-ignored by this repository.

`doctor` reports optional reporting readiness; it does not gate modeling.
`policy disabled` retains capture/drafts without contacting GitHub. `policy automatic`
restores the selected automatic policy. Policy is project-local in the state
directory and does not trigger historical submissions during installation.

Do not recursively report failures of this reporter. Retain their reason in the
original receipt/draft and continue safe modeling recovery. Configuration beyond
the diagnostic size budget is omitted with an explicit reproduction gap.
