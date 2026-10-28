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
| Final review | code-review + ponytail-review (+ security) | runs when the queue empties, then the factory pauses itself |
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
  `automation_id`, `integration_branch`, `last_cycle`.
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
