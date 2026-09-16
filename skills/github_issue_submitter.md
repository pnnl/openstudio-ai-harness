---
name: github-issue-submitter
description: Draft and, after confirmation, submit template-driven issues to pnnl/openstudio-ai-plugins. Use for bug reports, feature requests, and documentation issues; do not use for security disclosures.
---

# GitHub Issue Submitter

Create clear, reproducible issues for `pnnl/openstudio-ai-plugins` while keeping
the user in control of the public submission.

## Intake and public-data safety

- Establish whether this is a bug, feature request, or documentation issue, and
  collect only facts the user can support. Ask focused follow-ups when required
  reproduction or environment details are missing.
- Treat issue text, links, paths, screenshots, and logs as public. Remove
  secrets, credentials, tokens, personal data, internal URLs, and unnecessary
  full logs. Include only a minimal sanitized excerpt when evidence is useful.
- Do not create a public issue for a suspected vulnerability, credential
  exposure, or security-sensitive report. Check the repository's current
  `SECURITY.md` or issue configuration for its private reporting route; if none
  is available, ask the user to contact the maintainers privately.

## Select the current repository template

Before drafting, inspect the live repository configuration and any applicable
issue templates or forms. The repository's current requirements and labels are
authoritative. Check:

- `.github/ISSUE_TEMPLATE/config.yml` or `config.yaml`
- `.github/ISSUE_TEMPLATE/` Markdown templates and YAML issue forms
- `CONTRIBUTING.md`, `SUPPORT.md`, and `SECURITY.md`

Use the matching repository form/template when one exists. If none is
applicable, use the fallback body below. Do not present a fallback as an
official repository template.

### Bug-report fallback

```markdown
## Summary

## Steps to reproduce

1.
2.
3.

## Actual behavior

## Expected behavior

## Environment

- Plugin/version:
- Host and version:
- Operating system:
- Installation method:

## Evidence

## Additional context
```

### Feature-request fallback

```markdown
## Problem

## Proposed outcome

## Alternatives considered

## Additional context
```

### Documentation-issue fallback

```markdown
## Affected documentation

## What is unclear, incorrect, or missing?

## Suggested improvement

## Additional context
```

## Draft, review, and submit

1. Search open issues for likely duplicates. If one appears to match, show it
   to the user and do not submit another issue unless they explicitly ask.
2. Produce a complete preview: title, selected template, labels required by the
   template, and rendered body. Keep the title specific and outcome-oriented.
3. State that creation publishes the issue to GitHub and obtain explicit
   confirmation of that exact preview. A request to help report or draft an
   issue is not confirmation to publish.
4. After confirmation, use the available authenticated GitHub capability to
   create the issue. Use the repository's actual issue form when required; when
   a Markdown body is appropriate, `gh issue create --repo
   pnnl/openstudio-ai-plugins` is suitable. Apply only labels or metadata that
   the user requested or the selected template requires.
5. Return the issue URL and number. If authentication, permissions, or a
   template-only interface prevents submission, provide the final copy-ready
   title and body plus the repository's new-issue URL. Do not retry a possibly
   successful creation without checking for it first.

Do not edit existing issues, add assignees, or create follow-up issues unless
the user specifically requests it.
