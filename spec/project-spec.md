# Project Spec

## Project Name
Autochecker Upgrade: AI Tutor + AI Teacher-Assistant

## Goal
Upgrade the current autochecker from a repo-checking and evaluation platform into a product with two clear experiences:
- student-facing AI tutor
- teacher-facing AI teacher-assistant

This project must extend the current working system, not replace it.

## Current Baseline
The repo already has the following foundations:
- automated checking of student repositories
- Telegram bot for student interaction
- instructor dashboard
- repo and VM checks
- hints and LLM analysis
- agent-style evaluation for some labs
- relay-based infrastructure for internal VM access

Main code areas already carrying this logic:
- `autochecker/`
- `bot/`
- `dashboard/`
- `relay/`
- `specs/`

## Product Vision

### Student Experience
The student should experience the system as an AI tutor.

That means:
- feedback is not only pass/fail
- failed checks explain what is wrong
- feedback suggests concrete next actions
- repeated failure triggers deeper diagnostics
- the system can guide both technical and beginner learners

### Teacher Experience
The instructor should experience the system as an AI teacher-assistant.

That means:
- the system checks work at scale
- the system summarizes student progress
- the system identifies common mistakes across the cohort
- the system suggests where intervention is needed
- the system helps instructors author and evolve assignments

### Platform Experience
The platform should remain:
- spec-driven
- operationally reliable
- compatible with repo-based labs
- extensible for future tracks and assignment styles

## Product Requirements

### 1. Student Tutor Mode
The system must provide:
- structured failure explanation
- root-cause-oriented feedback where possible
- clear next-step recommendations
- better phrasing and product framing in bot and dashboard output

### 2. Escalation Agent Flow
After a configurable number of failed attempts:
- trigger a deeper diagnostic run
- inspect repo, logs, and VM state where available
- produce targeted fix guidance
- store enough structured output to show useful history

### 3. Teacher-Assistant Mode
The system must support:
- per-student summary
- per-task summary
- cohort-level summary
- common-failure clustering
- teacher recommendations and intervention hints

### 4. Assignment Authoring Improvements
The system must make it easier to define:
- labs
- rubrics
- hints
- escalation triggers
- tutoring content
- teacher summary content
- agent checks

### 5. Non-Technical Learning Track
The system should support a simpler learning path for less technical learners:
- smaller tasks
- guided explanations
- glossary support
- clearer language in feedback

## Architecture Constraints
- Do not rewrite the existing autochecker architecture.
- Continue using spec-driven behavior.
- Keep the boundaries between `autochecker/`, `bot/`, `dashboard/`, `relay/`, and `specs/`.
- Keep relay and VM constraints in mind.
- Preserve existing CLI, bot, and dashboard entry points.
- Changes must be production-oriented, not prototype-only.

## Major Workstreams

### Workstream A: Product Logic
- extend specs
- add tutoring metadata
- add escalation rules
- add structured summary generation

### Workstream B: Diagnostic Intelligence
- build a deeper diagnostic-agent layer
- inspect repo state and VM state
- generate structured root-cause output

### Workstream C: Student Experience
- improve bot responses
- improve result formatting
- make next steps more obvious

### Workstream D: Teacher Experience
- improve dashboard summaries
- add cohort analytics
- add error clustering and recommendations

### Workstream E: Content and Tracks
- add support for beginner or non-technical course variants
- define prompts and content patterns for guided learning

## Team Structure
One team, split into two delivery pairs:
- Backend + AI
- Frontend + UI/UX

User role context:
- the current user is the backend developer
- backend work is expected to be tightly coordinated with AI work

## Subteam Responsibilities

### Backend + AI
Own:
- spec model extensions
- engine changes
- diagnostic-agent layer
- bot checking flow logic
- structured feedback generation
- backend/dashboard data shaping
- reliability of relay-backed flows

### Frontend + UI/UX
Own:
- product framing in UI
- student-facing wording and interaction flow
- instructor-facing dashboard presentation
- information hierarchy
- visual clarity of summaries, statuses, and escalation states

## Inter-Team Contract
Backend + AI should expose:
- stable structured result shapes
- stable summary payloads
- clear status types for checks and escalations
- explicit fields for student feedback and teacher summaries

Frontend + UI/UX should produce:
- screen-level flows
- display requirements for new feedback states
- UI requirements for tutor mode, escalation mode, and teacher summary mode

## Suggested Phases

### Phase 1
- improve student-facing feedback
- add spec support for tutoring metadata
- keep output structured and backward-compatible where possible

### Phase 2
- add escalation flow and diagnostic-agent execution
- store escalation results and expose them to bot and dashboard

### Phase 3
- add teacher-assistant summaries and cohort analytics
- refine dashboard and reporting views

### Phase 4
- add beginner or non-technical learning track support
- improve authoring ergonomics for instructors

## Definition of Done
- The project remains stable on the current architecture.
- Student output is more useful than raw pass/fail.
- The system can escalate repeated failures into deeper diagnostics.
- Teachers can view summarized, actionable information.
- Ownership boundaries between the two subteams remain clear.
- Relevant verification passes before merging.
