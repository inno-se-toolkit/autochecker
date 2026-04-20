# Frontend + UI/UX Team Spec

## Team Mission
Turn the upgraded autochecker capabilities into a product experience that clearly feels like:
- an AI tutor for students
- an AI teacher-assistant for instructors

This subteam owns clarity, interaction flow, and presentation quality.

## Team Members
- Frontend developer
- UI/UX designer

## Primary Objective
Transform existing bot- and dashboard-facing output into a more understandable, trustworthy, and useful user experience without forcing a rewrite of the current platform.

## Scope

### In Scope
- dashboard presentation and interaction design
- student-facing wording and message framing
- teacher-facing information hierarchy
- status, summary, and escalation-state presentation
- UX requirements for tutor mode and teacher-assistant mode
- templates and frontend-facing display logic

### Out Of Scope
- core check execution logic
- spec model implementation
- relay execution logic
- deep backend data modeling
- diagnostic-agent implementation itself

## Key Problems To Solve

### 1. Product Framing Is Too Technical
The current system exposes internal checker concepts too directly.

Target:
- students should feel guided by a tutor
- teachers should feel assisted by an intelligent teaching tool

### 2. Student Feedback Needs Better Presentation
Even if backend feedback improves, students still need:
- clear failure explanation
- visible next actions
- clear escalation state
- less raw technical noise

### 3. Teacher Views Need Better Decision Support
Teachers need views that answer:
- who is blocked
- what mistakes are most common
- where intervention is needed
- which tasks or labs are causing the most trouble

### 4. Non-Technical Learners Need Simpler UX
The product should become easier for less technical learners through:
- simpler wording
- guided states
- glossary or explanation patterns
- less intimidating presentation

## Deliverables

### Deliverable A: Product Framing
Define how the product is described in interfaces:
- student-facing terminology
- teacher-facing terminology
- escalation-state wording
- summary wording

Acceptance:
- the interface no longer reads like an internal checker tool

### Deliverable B: Student Feedback UX
Design and implement display requirements for:
- failure explanation
- likely cause
- next steps
- retries and attempt state
- escalation triggered / escalation complete states

Acceptance:
- a student can understand what to do next without reading raw logs first

### Deliverable C: Teacher Summary UX
Design and implement views for:
- per-student progress
- per-task difficulty
- cohort-level mistake patterns
- intervention suggestions

Acceptance:
- the dashboard helps a teacher make decisions quickly

### Deliverable D: Beginner-Track UX
Define how non-technical or beginner-friendly content should be presented:
- smaller chunks
- softer wording
- guided steps
- glossary and explanation moments

Acceptance:
- the same platform can support a simpler learning track without confusing advanced users

## Owned Surfaces
- `dashboard/templates/`
- frontend-facing parts of `dashboard/app.py`
- student-facing rendering of reports and summaries
- wording, labels, and presentation states tied to tutor/teacher-assistant experience

## Inputs Expected From Backend + AI
This subteam expects stable structured fields such as:
- check status
- short reason
- detailed reason
- likely cause
- next steps
- escalation state
- student summary data
- teacher summary data
- cohort analytics data

## Outputs Required For Backend + AI
This subteam should provide:
- agreed display contract for feedback blocks
- list of required fields for student and teacher views
- UX states for escalation flow
- wording rules for beginner-friendly vs technical tracks

## UX Principles
- Make the next action obvious.
- Reduce unnecessary technical noise.
- Keep detailed diagnostics available, but not as the first thing users see.
- Make status states visually distinct and easy to scan.
- Keep dashboard summaries compact and decision-oriented.
- Preserve consistency with the current product instead of inventing a disconnected new UI language.

## Milestones

### Milestone 1
- define product terminology
- design feedback block structure for students
- define teacher summary layouts

### Milestone 2
- implement tutor-mode presentation in current dashboard and reporting surfaces
- implement escalation-state presentation

### Milestone 3
- implement cohort and intervention views for instructors

### Milestone 4
- implement beginner-track presentation patterns

## Done Criteria
- Student-facing flows feel like tutoring, not only checking.
- Teacher-facing flows feel like assistant summaries, not raw tables only.
- Escalation states are clear and understandable.
- UI supports both technical and beginner-friendly presentation modes.
- New presentation works with the existing platform structure.
