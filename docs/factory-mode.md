# Factory mode for the engineering workflow (design draft)

Status: proposal, nothing built. Target: engineering-workflow v0.3.0 (installed v0.2.2).
Runs on: Orca 1.4.238 (`orca automations`, `orca orchestration`, `orca worktree`).

## Goal

Keep the front half of the workflow as it is (grill or Wayfinder, then `/to-spec`,
then `/to-tickets`). After the tickets are approved, the workflow offers to install a
"software factory" for the project: an Orca-hosted loop that keeps building ready
tickets in parallel, without a person in the chat, until it is paused.

The person controls it with four verbs: install, pause, resume, run one cycle then pause.

Borrowed from Ona's Software Factory: the stage pipeline, "humans on the loop", a
Needs-Human queue, a quality file that learns. Borrowed from CodeAF: code lands on an
integration branch, never main; one queue across projects; spend caps.

## What stays the same

| Step | Today | In factory mode |
|---|---|---|
| Plan | grill / Wayfinder → to-spec → to-tickets | unchanged, always human-led |
| Build | SDD in one chat session, subagents | SDD controller runs as an Orca automation; workers are Orca worktrees |
| Per-ticket review | 1 implementer, 1 Sonnet reviewer, ≤1 fix round | unchanged |
| Second failed review | escalate to controller/human in chat | Orca decision gate + unread dot ("Needs you") |
| Merge | into integration branch | unchanged; never main |
| Final review | code-review + ponytail-review (+ security) | runs when the queue empties, then the factory pauses itself; on Orca this is multi-model-review (see skill routing) |
| Finish branch | finishing-a-development-branch | still human: the factory never merges to main or deploys |

## Where the install prompt appears

1. Right after `/to-tickets` is approved: "Build here (SDD in this session), or install
   the factory?" Options: Build here / Install and run / Install paused / Run one cycle.
2. At session start, when a factory exists, the session report adds one line:
   `factory: paused · 4 ready · 1 needs you` and offers Resume / One cycle / Leave it.

## Pieces (v1)

- `workflow.py factory install|status|pause|resume|cycle|uninstall` (new subcommand).
- State file `.engineering-workflow/factory.json` (gitignored, local to the host):
  `mode` (`running|paused|once|draining`), `concurrency`, `daily_ticket_cap`,
  `max_turns`, `max_minutes`, `automation_id`, `integration_branch`, `last_cycle`.
- One Orca automation, the heartbeat:
  `orca automations create --name "factory:<project>" --trigger hourly
   --provider claude --repo id:<repoId> --base-branch <integration>
   --precheck "python3 .engineering-workflow/workflow.py factory precheck"
   --extra-agent-args="--model opus" --prompt "<controller prompt>"`
  The precheck exits 0 only when mode is `running` or `once`, ready tickets exist,
  no other controller is live, and the daily cap is not hit. Otherwise Orca records a
  skipped run and spends nothing.
- New skill `ew-factory`: the controller prompt. It is SDD with Orca dispatch:
  read ledger → pick ready tickets (blockers merged) up to `concurrency` → one
  `orca worktree create --agent claude --parent-worktree <integration>` per ticket →
  review → fix once → merge → update ledger, STATUS.md and worktree cards.
- Orca cards as the dashboard: each ticket worktree gets `--workspace-status`
  (in-progress / in-review / completed) and a one-line `--comment`. Needs-Human =
  `orca orchestration gate-create` + `worktree set --unread`.

## How it ties to skill routing

![How factory mode and skill routing fit together](ew-map.svg)

Skill routing (`docs/skill-routing.md`) ships right after this and plugs into the same
loop. The factory needs none of it to work; each piece is used only when installed.

- Workers start their context pack from graphify, and UI tickets go through
  design-genius `design-director`.
- The factory always runs on Orca, so its final review is multi-model-review
  (replacing code-review + ponytail-review), plus `critique` when UI changed.
- The factory's hooks write the same per-ticket state files as SDD, so
  `ew-flightdeck` shows factory tickets next to in-chat ones. Orca cards stay the
  Needs-Human surface.
- `blast_radius: high` already covers the design system; those tickets also get
  `critique` before you approve the merge.

## Turn cap (per ticket)

A stuck agent can loop on one failure for hours and burn the subscription. Each
ticket gets a hard limit; hitting it stops the worker and sends the ticket to
Needs-Human with the last failing output.

- `max_turns` (default 100): agent turns per ticket, implementer and fix round
  together. Counted by the workflow's existing PostToolUse hook, which increments a
  per-ticket counter in the ledger when `EW_FACTORY_TICKET` is set in the worker's
  environment. At the cap the hook tells the agent to stop and report BLOCKED.
- `max_minutes` (default 90): wall-clock backstop enforced by the controller with
  `orca orchestration worker-stop`, for agents that never reach a hook.
- A capped ticket is marked `capped` (not `failed`); its worktree stays. The digest
  asks one question for it: what factory change (skill, CLAUDE.md rule, ticket shape)
  would have prevented this? That answer goes to the Idea Shelf, not into a retry.

Orca has no built-in turn limit (`worker-start` only has `--timeout-ms` for waiting),
so the hook does the counting.

## Blast radius (ticket field)

`/to-tickets` adds `blast_radius: low | medium | high` to each ticket, and you approve
it along with the tickets.

| Radius | Touches |
|---|---|
| low | one component or module inside one service, no shared code |
| medium | shared code inside one service, or a public interface other code calls |
| high | database schema or data, auth, payments, secrets, the design system, or more than one service |

v1 uses it two ways:
- `high` tickets stop at Needs-Human after review passes; you approve the merge into
  the integration branch. `low` and `medium` merge after review, as today.
- The Orca card comment and the digest show it, so you can see what is risky.

v3 risk-tiered auto-merge to main reads the same field; nothing new is needed then.

## One cycle

One cycle = one wave: take every ticket that is ready now (up to `concurrency`),
carry each to merged or Needs-Human, update the ledger, write a digest, stop.
Tickets that a wave unblocks wait for the next cycle.

`factory cycle` sets mode `once` and calls `orca automations run <id>`. The controller
sets mode back to `paused` when the wave ends. "Run until the queue is empty" is
`resume`; the factory pauses itself when nothing is ready and runs the final review.

## Pause (two kinds)

- `pause` = drain, at a ticket boundary: no new tickets start; every in-flight ticket
  runs to merged or Needs-Human, then the factory sits at `paused`.
  Mode goes `draining` → `paused`.
- `pause --now` = stop, mid-ticket: `orca orchestration worker-stop` on live workers.
  Their worktrees and commits stay; the ledger marks each ticket `interrupted` with
  its last finished step, and the next cycle resumes it from there.
- Disabling the automation in Orca's UI is a hard pause too; precheck never runs.
- Both are offered wherever the factory is controlled: the CLI, the session-start
  line, and the Needs-Human prompt. No work is discarded by either.

## Guard rails

- Never merges to main, never pushes to main, never deploys, never publishes issues.
- Keeps native permissions: the automation runs in the permission mode the person
  set for that Orca host. Install refuses if unattended runs would need bypass mode.
- Token budget from the workflow is unchanged. Adds `daily_ticket_cap` (default 10).
- Concurrency default 3, capped by `orca orchestration worker-list` accounting.
- Fresh controller session per cycle; all state on disk (ledger + factory.json), so
  compaction never matters.

## Later (Idea Shelf, not v1)

- v2: post-merge verifier on the integration tip; stale-ticket requeue; CI shepherd
  for the integration → main PR.
- v3: operate stations (incident-response on errors, perf watch), feedback → draft
  tickets that wait for human approval, risk-tiered auto-merge to main.
- Cross-project queue: one Orca view of Needs-Human across every factory.
- From theSeniorDev's software-factory video (2026-10-12): deterministic quality
  gates fed back to the implementer (lint, types, duplication, complexity, dead
  code); before/after screenshots in Orca's browser; smoke-test subset plus a QA
  agent that acts as a user; intake agents (triage from Sentry/Slack, refinement
  with repro evidence, prioritizer); anonymized production-like seed data;
  bug-cluster review that points at architecture; strip issue-reference comments.

## Decisions (2026-10-28)

- Per-ticket turn cap: 100 turns (hook-counted) plus a 90-minute wall-clock backstop;
  capped tickets go to Needs-Human with a "what factory change prevents this?" note.
- Tickets carry `blast_radius` (low / medium / high). In v1, `high` tickets need your
  approval before merging into the integration branch.

## Decisions (2026-10-27)

- Pause has two kinds: drain (finish in-flight tickets, then pause) and stop
  (interrupt mid-ticket, resume later from the ledger).
- Heartbeat: hourly Orca automation with precheck.
- Concurrency: 3 by default.
- Home: engineering-workflow repo, new `ew-factory` skill + `workflow.py factory`,
  released as v0.3.0.
- One cycle = one wave (kept as default; your answer covered pause, not cycle size).

## Not verified yet

- Whether Orca automations can run Claude unattended in this host's permission mode.
  First v1 task.
- Whether Claude agents launched by Orca run the workflow's PostToolUse hook (needed
  for the turn count). Same spike.
