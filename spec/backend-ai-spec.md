# Backend + AI Team Spec

## Team Mission
Build the system logic that turns the current autochecker into:
- an AI tutor for students
- an AI teacher-assistant backend for instructors

This subteam is the main owner of platform intelligence, execution, structured feedback, and reliability.

## Team Members
- Backend developer
- AI developer

## Primary Objective
Extend the existing Python-based backend and checking engine so the product can:
- explain failures better
- escalate repeated failures into deeper diagnosis
- generate structured summaries for instructors
- remain reliable in repo, VM, and relay-based workflows

## Scope

### In Scope
- `autochecker/spec.py`
- `autochecker/engine.py`
- `autochecker/llm_analyzer.py`
- `autochecker/reporter.py`
- `autochecker/` support modules needed for new feedback flows
- `bot/handlers/check.py`
- `bot/database.py`
- `bot/config.py`
- backend-facing parts of `dashboard/app.py`
- `relay/worker.py` when reliability or structured execution needs change
- new project docs or structured config related to tutoring or escalation

### Out Of Scope
- major visual redesign
- final UX copy polishing
- presentation-layer interaction design
- dashboard layout redesign owned by Frontend + UI/UX

## Key Problems To Solve

### 1. Student Feedback Is Too Thin
Current checks already support hints, but the product must go beyond:
- pass or fail
- one hint line
- raw technical output

Target:
- structured feedback with failure reason, likely cause, and next step

### 2. Repeated Failure Needs Escalation
After repeated failed attempts, the system should:
- detect escalation eligibility
- run a deeper diagnostic flow
- inspect repo and VM state where possible
- return precise, high-signal remediation steps

### 3. Teacher Summaries Need Structured Data
The backend must generate stable, structured data for:
- student summary cards
- task summary views
- cohort-level mistake clustering
- intervention recommendations

### 4. Infrastructure Must Stay Reliable
The new logic must respect:
- relay limitations
- VM reachability constraints
- LLM access constraints
- timeout and retry behavior
- safe fallback behavior

## Deliverables

### Deliverable A: Spec Model Extension
Extend project spec support so lab definitions can include:
- tutoring text
- escalation thresholds or triggers
- learning objectives
- teacher summary metadata
- optional beginner-track content

Acceptance:
- spec loading remains stable
- old specs continue to work unless intentionally migrated

### Deliverable B: Structured Feedback Model
Introduce a structured feedback shape for checks and runs.

Suggested fields:
- status
- short_reason
- detailed_reason
- likely_cause
- next_steps
- hint
- escalation_state

Acceptance:
- bot and dashboard can consume the data without relying on fragile string parsing

### Deliverable C: Escalation Agent Layer
Add a deeper diagnostic path that can:
- inspect repo content
- inspect logs or runtime state when available
- inspect VM via existing infrastructure where applicable
- produce structured root-cause output

Acceptance:
- escalation can be triggered by attempt history or explicit policy
- failure output is actionable and more specific than baseline hints

### Deliverable D: Bot Flow Upgrade
Update checking flow logic so it can:
- track repeated failures cleanly
- decide when escalation applies
- show action-oriented feedback
- expose escalation results to students clearly

Acceptance:
- normal checks still work
- attempt accounting remains correct
- escalation does not break existing lab flows

### Deliverable E: Teacher Data APIs
Provide data structures for:
- per-student summary
- per-task summary
- cohort summary
- common failure clusters
- suggested teacher actions

Acceptance:
- frontend can render these without backend-side template hacks

## File Ownership Guidance

### Primary Ownership
- `autochecker/`
- `bot/`
- execution logic in `dashboard/app.py`
- relay-related reliability code

### Shared Boundary With Frontend + UI/UX
- `dashboard/app.py`
- `dashboard/templates/`
- report presentation fields

Rule:
- Backend + AI own data shape and business logic.
- Frontend + UI/UX own display structure and interaction presentation.

## Technical Approach

### Preferred Approach
- extend current models
- keep changes incremental
- keep runtime behavior spec-driven
- store structured results, not only rendered text
- preserve backward compatibility when practical

### Avoid
- rewriting the engine
- embedding UX-only decisions deep inside backend logic
- duplicating logic between bot and dashboard
- overcoupling agent behavior to one specific lab

## Milestones

### Milestone 1
- define structured feedback contract
- extend spec model
- wire improved feedback into current check results

### Milestone 2
- implement escalation policy and execution path
- store and expose escalation output

### Milestone 3
- add teacher summary generation and clustering support
- expose summary data to dashboard consumers

### Milestone 4
- support beginner-track content and alternate tutoring prompts

## Done Criteria
- Existing checks still run.
- New feedback is structured and actionable.
- Escalation works for repeated failure paths.
- Teacher summary data is available in a stable format.
- Relay and VM flows remain robust.
- Relevant verification passes.
