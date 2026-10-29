# Spec: Factory mode (engineering-workflow v0.3.0)

Status: ready-for-agent
Design: `docs/factory-mode.md` (decisions dated 2026-10-27 and 2026-10-28 in `STATUS.md`)

## Problem Statement

Once a feature is planned and its tickets are approved, building them still needs a
person sitting in a chat session: SDD runs inside one Claude session, one controller
at a time, and stops when the session ends or its context fills. The person cannot
walk away, cannot let tickets build in parallel overnight, and has no clean way to
stop the work part-way (at a ticket boundary or immediately) and pick it up later.
Running agents unattended with no limits also risks runaway loops that burn the
subscription, parallel builds that choke one machine, risky changes merging without
a look, and a pile of half-reviewed work that grows faster than the person can read it.

## Solution

After `/to-tickets` is approved, the workflow offers to install a **factory** for the
feature. The factory is an opt-in loop hosted on Orca that keeps building ready
tickets in parallel without a person in the chat, until it is paused.

Planning stays exactly as it is. Plain code owns the loop: a short, repeatable
`workflow.py factory tick` decides what runs next, enforces every limit, re-checks
and merges finished tickets, and changes modes. Agents only do the work inside one
ticket. An hourly Orca automation and each finishing worker trigger `tick`.

The person controls it with: install, pause (drain at a ticket boundary, or stop
mid-ticket), resume, and run one cycle then pause. Work lands on the integration
branch only; the person still decides what reaches main. Anything needing a human
shows on the ticket's Orca card with an unread dot, and the factory holds itself
when too much is waiting.

## User Stories

1. As a developer, I want the workflow to offer a factory right after I approve tickets, so that I don't have to remember a separate setup step.
2. As a developer, I want to choose between building in this session, installing and running, installing paused, or running one cycle, so that I pick how much autonomy to grant each time.
3. As a developer, I want `factory install` to refuse to run when Orca is missing, the repo is not registered in Orca, the integration branch is main/master, or the project has no gate script, so that a broken setup never starts unattended work.
4. As a developer, I want install to show me a starter gate script built from the project's own commands when none exists, so that I approve the checks rather than write them from scratch.
5. As a developer, I want one hourly heartbeat that costs nothing when the factory is paused or has nothing to do, so that leaving the factory installed is free.
6. As a developer, I want the heartbeat agent to only run `factory tick` on a cheap model, so that no expensive agent makes scheduling decisions.
7. As a developer, I want `tick` to be safe to run any number of times, concurrently, so that a heartbeat and a finishing worker can never double-start or double-merge.
8. As a developer, I want ready tickets to be the tracker tickets marked `ready-for-agent` whose blockers have all merged into the integration branch, so that dependency order from `/to-tickets` is honoured.
9. As a developer, I want each ticket claimed by creating its own branch from the integration tip, so that no ticket ever starts twice, even across hosts.
10. As a developer, I want each ticket built in its own git worktree with its own Claude agent launched through Orca, so that tickets are isolated and visible in Orca's sidebar.
11. As a developer, I want at most 3 tickets building at once by default, and a way to change it, so that the factory fits my machine.
12. As a developer, I want a daily cap on tickets started (default 10), so that one runaway day can't burn a week of usage.
13. As a developer, I want each worker to follow one-ticket SDD (ponytail, TDD, gate script, fresh reviewer, at most one fix round), so that factory tickets meet the same bar as in-session ones.
14. As a developer, I want the reviewer to prove the new test fails without the change, so that tests that pass by accident are caught.
15. As a developer, I want every build and full test run to go through a shared build queue with a fixed number of slots (default 1), so that parallel workers don't slow each other down.
16. As a developer, I want queue wait recorded per ticket and excluded from the time cap, so that waiting for a build slot never gets a ticket capped.
17. As a developer, I want a ticket stopped at 100 agent turns, with further tool calls refused, so that a looping agent cannot burn the subscription.
18. As a developer, I want a ticket stopped after 90 minutes of working time, so that agents that never hit the turn hook still stop.
19. As a developer, I want a capped ticket kept (worktree and commits intact) and marked `capped`, not failed, so that I can look at it and requeue it.
20. As a developer, I want each worker to finish by reporting approved or blocked plus one line on what slowed it down, so that I can see the factory's bottleneck.
21. As a developer, I want `tick` to re-run the gate script itself on the ticket branch before merging and trust only its own run, so that an agent can't claim a pass it didn't earn.
22. As a developer, I want approved low and medium blast-radius tickets merged into the integration branch automatically, so that routine work flows without me.
23. As a developer, I want high blast-radius tickets (schema/data, auth, payments, secrets, design system, more than one service) to wait for my approval before merging, so that risky changes always get my eyes.
24. As a developer, I want merge conflicts to send the ticket to me instead of being resolved by guesswork, so that the integration branch stays sound.
25. As a developer, I want everything waiting on me shown on the ticket's Orca card (status, one-line comment, unread dot), so that I see it where I already work.
26. As a developer, I want the factory to stop starting tickets once 5 items are waiting on me, and carry on by itself when I clear them, so that review work never piles up beyond what I can handle.
27. As a developer, I want `factory approve <ticket>` to merge a held ticket and `factory requeue <ticket>` to put a capped, blocked or interrupted ticket back in the queue, so that I can clear the pile from the command line.
28. As a developer, I want `factory pause` to stop starting tickets and let in-flight ones finish before pausing, so that I can stop at a clean ticket boundary.
29. As a developer, I want `factory pause --now` to stop every worker immediately, keep their worktrees, and mark them interrupted, so that I can halt everything mid-ticket without losing work.
30. As a developer, I want an interrupted ticket to resume from its existing branch and worktree on the next cycle, so that stopping never throws work away.
31. As a developer, I want `factory resume` to run until the queue is empty, then run the final branch review and pause itself, so that a whole feature can finish unattended.
32. As a developer, I want `factory cycle` to start exactly one wave (every ticket ready right now), carry it to merged or waiting-on-me, then pause, so that I can let it run a bounded amount.
33. As a developer, I want disabling the automation in Orca's UI to act as a hard pause, so that I can stop it from Orca without a terminal.
34. As a developer, I want `factory status` to print one line like `factory: paused · 4 ready · 2 building · 1 needs you · held` plus the details, so that I know the state at a glance.
35. As a developer, I want that status line in every session-start report for the repo, so that I see where the factory is the moment I open a session.
36. As a developer, I want `factory status` to summarise the last wave (merges, waiting items, caps, queue wait, slowed-by lines) from the ledger, so that I can review a night's work in a minute.
37. As a developer, I want concurrency, build slots, caps and the pile limit read from the factory's state file each tick, so that I can tune them by editing one file without reinstalling.
38. As a developer, I want `factory uninstall` to remove the heartbeat but keep the ledger and worktrees, so that removing the factory never destroys work.
39. As a developer, I want the factory never to merge or push to main, deploy, publish issues or use bypass permissions, so that unattended runs stay inside the limits I already trust.
40. As a developer, I want all factory state on disk and every agent session fresh, so that nothing depends on chat history or context compaction.
41. As a workflow maintainer, I want the factory implemented with the standard library only and covered by the existing CLI-subprocess test style, so that it matches the rest of the package.
42. As a workflow maintainer, I want the factory's Orca calls isolated behind one small adapter, so that an Orca CLI change touches one place.

## Implementation Decisions

**Modules**

- New `factory` module, wired into the CLI the same way the reviews module is
  (`add_parser` / `run`), exposing `workflow.py factory <action>` with actions:
  `install`, `uninstall`, `status`, `pause` (`--now`), `resume`, `cycle`,
  `tick`, `precheck`, `gate`, `report`, `approve`, `requeue`. Added to the package's
  file list and release lock like the existing modules.
- An **Orca adapter** inside that module: the only code that calls the `orca` CLI
  (always with `--json`). Operations: register heartbeat, remove heartbeat, launch
  worker agent in a worktree, stop worker, is-worker-alive, set card (status,
  comment, unread). It resolves the executable the way the orca-cli guide says.
- Hook changes in the existing hook handler: PostToolUse counts turns for factory
  tickets; PreToolUse refuses tool calls for a ticket over its turn cap; SessionStart
  adds the factory status line when a factory exists.
- New skill `ew-factory` (in the package's skills, added to the lock): the
  one-ticket worker brief and the final-review brief. Not a controller.
- `core/WORKFLOW.md` (and the Claude adapter) gain the install offer after
  `/to-tickets` approval and the factory rules. Vendored upstream skills are not edited.

**State** (all under the project's `.engineering-workflow-state/factory/`, which
install makes sure is git-ignored)

- `state.json`: `mode` (`running|paused|once|draining`), `feature` (the tracker
  feature slug), `integration_branch`, `concurrency` (3), `build_slots` (1),
  `daily_ticket_cap` (10), `stop_if_waiting` (5), `max_turns` (100),
  `max_minutes` (90), `automation_id`, `wave` (ticket ids of the current once-wave),
  `final_review` (not-started / dispatched), `last_tick`.
- `ledger.json`: one entry per ticket: `state`, `branch`, `worktree`,
  `worker_handle`, `started_at`, `turns`, `queue_wait_seconds`,
  `gate_seconds`, `slowed_by`, `reason`, `history` (timestamped transitions).
- `tick.lock` (exclusive `fcntl` lock), `slots/` (one lock file per build slot).
  Settings are edited by hand in `state.json`; `tick` re-reads them every run and
  rejects invalid values with a clear error (ponytail: no `set` command until
  hand-editing proves error-prone). No separate digest file: `status` summarises the
  last wave from the ledger.
- Each ticket worktree gets a small marker file in its own ignored state dir naming
  the ticket id and the absolute path of the factory state, so hooks running inside
  the worktree find the ledger without relying on environment variables.

**Tickets** come from the local tracker: `.scratch/<feature>/issues/NN-slug.md`.
The factory reads `Status:`, `Blocked by:` and a new `Blast radius: low|medium|high`
line. A missing blast radius is treated as `high`. The factory never edits ticket
files; its own progress lives in the ledger.

**Ticket lifecycle** (ledger `state`):

```
ready ─claim─> working ─report approved─> approved ─gates pass─┬─ low/medium ─> merged
                 │                                              └─ high ───────> needs-you ─approve─> merged
                 ├─report blocked──> needs-you (blocked)
                 ├─turn/time cap──> capped
                 ├─pause --now────> interrupted
                 └─gates fail / merge conflict at merge time ─> needs-you
capped | interrupted | needs-you(blocked) ─requeue─> ready (interrupted keeps its branch and worktree)
```

**Modes**: `paused` (precheck always skips), `running`, `once`, `draining`.
`resume` → running; `cycle` → once; `pause` → draining; `pause --now` → paused
immediately. `tick` moves draining → paused and once → paused when nothing it started
is still working; moves running → paused after dispatching the final review when no
ticket is ready, working or approved.

**`tick` order** (under the tick lock; exits in seconds):
1. Reconcile: workers the ledger thinks are working but Orca reports dead and that
   never reported → `interrupted`.
2. Enforce caps: working minutes (wall time minus queue wait) over `max_minutes`, or
   turns over `max_turns` → stop worker, `capped`.
3. Merge approved tickets: run the gate script on the ticket branch through the build
   queue; on PASS merge (no fast-forward) into the integration branch in the
   integration checkout unless blast radius is high; on FAIL, conflict or high →
   `needs-you` with a reason. Merged tickets' worktrees are removed; branches stay.
4. Back-pressure: count `needs-you` + `capped` tickets; at `stop_if_waiting` start
   nothing this tick and record `held`.
5. Start tickets (only in `running`, or in `once` for the first wave): pick ready
   tickets in tracker order up to `concurrency` minus working and within the daily
   cap. Claim = create branch `factory/<feature>-<NN>` from the integration tip
   (failure = already claimed; with a remote, push the branch and treat a rejected
   push as claimed). Create the worktree with `git worktree add` from that branch,
   write the marker file, launch `claude` there via Orca with the worker brief.
6. Final review: in `running`, when nothing is ready, working or approved and the
   final review hasn't been dispatched, launch one agent in the integration checkout
   with the final-review brief, then pause.
7. Mode bookkeeping and card updates for every ticket whose state changed; the
   wave's end time is recorded so `status` can summarise it.

**`precheck`** exits 0 only when mode is not `paused` and `tick` has something to do
(ready tickets with free capacity and not held, working tickets to check, or approved
tickets to merge); otherwise non-zero so Orca skips the run.

**Heartbeat**: one Orca automation per factory, hourly, provider `claude`, running in
the integration checkout's Orca workspace, cheap model via extra agent args, precheck
above, prompt "Run `workflow.py factory tick` for this project, report its output,
do nothing else."

**`gate`**: acquires one of `build_slots` slot locks (non-blocking attempts, then
wait), runs the project's committed gate script, releases the slot, records queue
wait and run time in the ledger when run for a ticket, and exits 0 only if the
script's last line is exactly `GATES: PASS`. A missing script is a FAIL. Workers run
heavy builds and full suites only through `gate`.

**`report <ticket> approved|blocked --slowed-by "<line>" [--reason "<line>"]`**:
updates the ledger, then runs `tick`.

**Turn counting**: PostToolUse inside a ticket worktree increments the ticket's
`turns`. PreToolUse refuses every tool call once `turns ≥ max_turns`, with the
message "Factory turn cap reached; run factory report <ticket> blocked". `tick`
then marks it `capped` (step 2) and stops the worker.

**Needs-you surface**: the ticket's Orca card gets status `in-review`, a comment
starting `NEEDS YOU:` with the reason, and the unread dot. Working tickets show
`in-progress`, merged tickets `completed`. (This replaces the design draft's
orchestration decision gates, which need orchestration tasks the factory doesn't use.)

**Install** preflight refuses on: no `orca` executable; repo not registered in Orca;
integration branch missing or named main/master; feature has no ticket files; no
gate script (prints a starter generated from detected project commands for the
person to save and commit). Install writes state with `--paused` or running, adds the
state dir to the ignore file if needed, and registers the heartbeat. A second install
for the same project refuses.

**Final review brief** uses multi-model-review when installed, otherwise
ew-matt-code-review then ew-ponytail-review, plus security review when the diff
touches auth, secrets, payments or trust boundaries; findings go to the ledger (shown by
`status`) and the integration card. The factory never runs finishing-a-development-branch.

## Testing Decisions

- A good test drives the factory only through the `workflow.py` CLI (subprocess),
  exactly as a person or the heartbeat would, and asserts on observable results:
  stdout/exit codes, ledger and state JSON, git branches/worktrees/merge commits in a
  temporary repo, and the log of Orca calls. No test imports internal helpers or
  asserts on function structure.
- Fixtures: a temporary git repo with an integration branch, ticket files under
  `.scratch/<feature>/issues/` (Status, Blocked by, Blast radius), and a tiny gate
  script whose PASS/FAIL is controlled per test. A fake `orca` executable placed
  first on `PATH` logs each call and returns canned JSON (including worker alive/dead).
- The turn cap is tested through the existing `workflow.py hook --platform claude`
  path, feeding PostToolUse/PreToolUse events with a ticket worktree as `cwd`.
- Covered behaviours: ready-ticket selection and blocker order; double tick never
  double-claims; concurrency, daily cap and back-pressure hold; drain vs stop;
  once-wave ends in paused; interrupted/capped tickets resume via requeue; gates
  re-run before merge and FAIL/conflict/high radius go to needs-you; approve merges;
  build-slot queueing records wait and excludes it from the time cap; precheck exit
  codes; install preflight refusals; uninstall keeps ledger and worktrees; status
  line; never touches main.
- Prior art: `tests/test_reviews.py` (CLI subprocess against a temp git project with
  env and state-dir injection) and `tests/test_workflow.py` (hook events over stdin,
  temp git repos with spaces in paths).
- The real Orca CLI is not called in the unit suite. Its behaviour is checked by the
  first ticket, a manual spike.

## Out of Scope

- Remote or disposable build compute (Orca SSH hosts, VM services), warm snapshots.
- GitHub/GitLab issue trackers as the factory's ticket source (local markdown only).
- Auto-merge to main, deploys, CI shepherding, post-merge verifier, stale requeue
  (v2/v3 on the Idea Shelf).
- Intake agents, QA agent, visual diffs, goal tickets, AI judge panels.
- Non-Claude workers (Codex, Gemini) and more than one feature per factory.
- Editing `STATUS.md` or ticket files automatically.
- A cross-project Needs-you view and the `ew-flightdeck` dashboard (skill routing).

## Further Notes

- First ticket is a manual spike on this host: unattended Claude in the current
  permission mode via Orca automations and `agent launch`; the workflow hooks firing
  in Orca-launched agents; heartbeat accepting a cheap-model extra arg; a worker able
  to run `factory report` as its last step; Orca's card, liveness and stop commands
  for agents launched with `agent launch`. Later tickets adjust the adapter to what
  the spike finds.
- Deviations from the design draft, made while reading the code: state lives in
  `.engineering-workflow-state/factory/` (beside the goal state, outside verified
  package files); worktrees are created with `git worktree add` and agents launched
  into them, rather than letting Orca create the branch; the turn hook finds its
  ticket through a marker file, not an environment variable; needs-you uses the card
  + unread dot instead of orchestration gates.
- "One cycle = one wave" is still marked not yet confirmed in `STATUS.md`.
