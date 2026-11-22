# Engineering Workflow

A versioned, portable engineering process (planning, TDD, review, parallel ticket building) packaged so Claude Code, Codex, Gemini CLI and Antigravity all follow the same rules. This repo is the package, not a product project.

## Language

### Package and runtime

**Workflow**:
The shared engineering process defined in `core/WORKFLOW.md`, identical across platforms.
_Avoid_: Process doc, playbook

**Adapter**:
The per-platform mapping of the workflow onto one tool's capabilities (Claude, Codex, Gemini, Agy).
_Avoid_: Platform layer, port

**Runtime**:
The installed copy of the workflow that a session actually uses, either user-wide or pinned to one project.
_Avoid_: Install, deployment

**Project pin**:
A runtime committed inside a project, which takes precedence over the user install.
_Avoid_: Local override, vendored copy

**Release**:
A tagged, checksum-verified version of the package; the tag is the trust anchor.
_Avoid_: Build, snapshot

**Session report**:
The startup output naming the chosen runtime, version, source commit, integrity result and capability limits.
_Avoid_: Boot log, health check

**Guard**:
The shell-call safety check run by hooks; an extra check, not a sandbox.
_Avoid_: Sandbox, firewall

**Wool mode**:
An install flag that makes completion verification and docs upkeep optional while Graphify, Guard and review gates stay on.
_Avoid_: Lite mode, relaxed mode

### Planning and building

**Grilling**:
Relentless questioning of a plan or decision before any building starts.
_Avoid_: Interview, brainstorm

**Wayfinder**:
A planning skill for an uncertain multi-session route; it resolves decisions and builds nothing.
_Avoid_: Roadmapper

**Spec**:
The written statement of intent, with confirmed public testing seams, that tickets are cut from.
_Avoid_: PRD, requirements doc

**Ticket**:
One vertical slice of work with blocking edges, stored as a local markdown file under `.scratch/<feature>/`.
_Avoid_: Task, story, issue

**Integration branch**:
The branch tickets merge into; the workflow never merges it to main.
_Avoid_: Feature branch, release branch

**SDD (subagent-driven development)**:
Building approved tickets in-session, one fresh implementer and one independent reviewer per ticket.
_Avoid_: Agent loop

**Ponytail**:
The lazy-solution discipline: reuse existing code and the standard library, add no speculative flexibility.
_Avoid_: Minimalism mode

### Factory mode

**Factory**:
The opt-in loop that builds approved tickets in parallel into an integration branch without a person in the chat.
_Avoid_: Pipeline, CI loop

**Tick**:
One short, idempotent run of `factory tick` that enforces caps, merges, and starts ready tickets.
_Avoid_: Cron run, poll

**Runner**:
The host that launches factory workers: Orca or Agent Orchestrator (AO).
_Avoid_: Backend, executor

**Worker**:
An agent session that builds one ticket in its own worktree and ends by filing a report.
_Avoid_: Bot, sub-agent

**Gate**:
The committed `.engineering-workflow/gates.sh` script whose final `GATES: PASS` line decides whether a ticket passed.
_Avoid_: Test run, CI check

**NEEDS YOU**:
The marker on a ticket that has stopped and waits for a human to approve, fix or requeue it.
_Avoid_: Blocked, alert

**Climb**:
An optional metric-improvement run (`ew-hill-climb`) after the last ticket merges, scored by the factory itself.
_Avoid_: Optimization pass, tuning

**Final review**:
The whole-feature code review the factory runs once all tickets (and any climb) have merged.
_Avoid_: QA, sign-off

### Project knowledge

**Graph overlay**:
The code-only Graphify map that keeps the heavy graph outside the repo and commits a thin `docs/map/MAP.md`.
_Avoid_: Code index, repo map

**Workspace**:
The folder the workflow runs in; a project groups several workspaces.
_Avoid_: Repo, module

**Goal**:
An explicit project-local objective that lets stop hooks continue a session, capped at 30 continuations.
_Avoid_: Todo, objective

**Implementation review**:
A short human-facing narrative of a checkpoint, queued to Open Thoughts, that adds no approval.
_Avoid_: Status update, sign-off

**STATUS.md**:
The repo-root file recording where work stands: Now, Next, Decisions, Open items.
_Avoid_: Changelog, progress log
