---
name: capture-session-lesson
description: Draft a candidate OpenStudio AI session lesson for later review.
---

# Capture Session Lesson

Capture a candidate lesson from the current session only after the user confirms
they want it saved for future OpenStudio AI sessions. Record only reviewable
observations, assumptions, failure modes, or reusable workflow notes.

1. Call `learning_capture_observation` with concise evidence and the applicable
   workflow/model scope. Do not include secrets or unnecessary transcript text.
2. Call `learning_create_candidate` with the resulting event ID, a proposed
   lesson, guidance, and retrieval tags.
3. Show the candidate to the user. Call `learning_review_candidate` only when
   the user explicitly approves or rejects it.

Approval creates a user-local personal lesson that later workflows may retrieve
with `learning_search_lessons`. It never edits trusted skills, knowledge,
measures, or MCP tools. Use `references/session_lesson.schema.json` as the
candidate shape, and clearly distinguish saved personal lessons from shared
plugin assets.
