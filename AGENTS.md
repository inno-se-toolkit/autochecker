# Project Context

## Goal
This project is an automated lab-checking platform that is evolving into an AI tutor for students and an AI teacher-assistant for instructors.

The current base already exists:
- automated checking
- Telegram bot
- instructor dashboard
- repo and VM checks
- hints and LLM analysis
- some agent-style evaluation

This is not a rewrite. It is an upgrade of the existing autochecker architecture into a more tutor-like and teacher-assistant-oriented product.

## Product Direction

### Student-facing
- AI tutor, not just a checker
- Explain what failed, why it failed, and what to do next
- Track repeated failures and escalate to deeper diagnostics when needed

### Teacher-facing
- AI teacher-assistant
- Summarize progress per student, per task, and per cohort
- Surface common mistakes and intervention suggestions

### Platform-facing
- Scalable AI learning infrastructure built on repo-based assignments, automated checks, and agent diagnostics

## Team Context
- This project is being developed by one team with four disciplines:
- UI/UX
- Frontend
- Backend
- AI

Current working split:
- Backend and AI work as one delivery pair.
- UI/UX and Frontend work as one delivery pair.

Primary ownership for the current user:
- The current user is the backend developer.
- Backend work should be coordinated closely with AI-related implementation.
- When proposing tasks, prefer a split where backend and AI changes are grouped together, and UI/UX plus frontend changes are grouped together.

## What Codex Should Always Know
- This project is only about this codebase.
- Do not mix ideas from other projects.
- This repo already has working foundations. Extend them instead of replacing them.
- Follow the existing architecture and keep concerns separated between `autochecker/`, `bot/`, `dashboard/`, `relay/`, and `specs/`.
- Prefer editing existing files over creating new ones.
- Keep code simple, production-ready, and spec-driven.
- Preserve the current flow where lab behavior is largely defined by YAML specs.
- Treat this as an upgrade from "autochecker" to "AI tutor + AI teacher-assistant".
- Respect the team split:
- Backend + AI changes should be planned together.
- UI/UX + Frontend changes should be planned together.
- Prefer task decomposition that matches these two subteams.

## What We Need To Add
- Student tutor mode: not just pass/fail, but personalized feedback about what failed, why, and next steps.
- Escalation flow: after N failed attempts, launch a deeper diagnostic agent that checks repo, logs, and VM, then returns precise fix steps.
- Teacher-assistant mode: generate summaries per student, per task, and per cohort, with common mistakes and intervention suggestions.
- Assignment authoring tools: make it easier for instructors to define labs, rubrics, hints, escalation rules, and agent checks without too much manual YAML editing.
- Learning path support: add a simpler non-technical track with guided explanations, glossary, and smaller tasks.
- Better product framing and UI: students should experience an AI tutor, and instructors should experience an AI teaching assistant.

## Realization Plan
- Extend `autochecker/spec.py` to support tutoring text, escalation triggers, learning objectives, and teacher summaries.
- Add a diagnostic-agent layer on top of the current engine so repo and VM inspection can produce structured root-cause feedback.
- Upgrade `bot/handlers/check.py` to keep failure history, trigger escalation, and return action-oriented feedback.
- Upgrade `dashboard/app.py` with cohort analytics, common-failure clustering, and teacher recommendations.
- Harden relay and remote-check infrastructure so agent runs are reliable, logged, and retryable.
- Create a second content layer for beginner and non-technical course tracks, including tutor prompts and simpler specs.

## Stack
- Python
- Typer CLI
- FastAPI
- aiogram
- aiosqlite / SQLite
- Jinja2 templates
- Pydantic
- YAML lab specs
- GitHub and GitLab API integration
- Relay worker for SSH and internal network checks
- LLM-based analysis via external model APIs

## Rules
- Use only patterns that already exist in the repo unless there is a clear reason to introduce a new one.
- Do not rename files unless necessary.
- Do not rewrite working subsystems just to make them cleaner.
- Preserve spec-driven behavior and existing entry points.
- Keep student-facing feedback concrete and action-oriented.
- Keep instructor-facing output summarized and operationally useful.
- Ask before making broad schema changes or changing core data contracts.
- Run relevant verification after changes. Prefer `python verify.py` and targeted tests such as `pytest tests/test_agent_eval.py -v` when applicable.
- Keep infrastructure constraints in mind, especially relay-based access to student VMs and restricted university-network execution paths.

## Important Files
- `autochecker/__init__.py`
- `autochecker/engine.py`
- `autochecker/spec.py`
- `autochecker/llm_analyzer.py`
- `autochecker/reporter.py`
- `bot/handlers/check.py`
- `bot/database.py`
- `bot/config.py`
- `dashboard/app.py`
- `relay/worker.py`
- `specs/*.yaml`
- `specs/lab-06-eval.yaml`
- `docs/infrastructure.md`
- `docs/gotchas.md`
- `README.md`
- `verify.py`

## Definition Of Done
- The feature works within the current architecture.
- Existing flows for checking, bot usage, dashboard usage, and reporting still work.
- Student-facing output is more helpful, specific, and action-oriented.
- Instructor-facing output is more useful for summarization and intervention.
- No avoidable regressions are introduced in repo checks, VM checks, relay flows, or spec loading.
- Relevant verification passes.
