---
status: active
progress: 100
next_date: 2026-10-29
updated: 2026-10-31
---

# STATUS

## Now

Factory mode v0.3.0 is merged to main (tickets 01-10 merged, final
review done and its findings fixed): 127 tests and `verify --expected 0.3.0` pass;
Merged to main via PR #6 (c398dd6) on 2026-10-29; not yet tagged. Build log:
`.engineering-workflow-state/sdd/factory-mode/progress.md`.

## Next

0. v0.4.0 (AO runner, PR #9) released 2026-10-31. New factories use `--runner ao`; the two
   live Orca factories (Aristocrat course-factory-mvp, Herculean iolaus-columns) finish on Orca.
1. Tag and release v0.3.0 from main (c398dd6).
3. Remove the `orca-spike` repo entry in Orca's UI (left by the spike; no CLI for it).
4. First real factory run (Herculean Iolaus-columns, 2026-10-30) confirmed the `agent launch` reply shape (fixed in v0.3.1); `terminal read` and `terminal show` shapes still to confirm.
5. Skill routing: spec written (`.scratch/skill-routing/spec.md`); next
   `/ew-matt-to-tickets` for it.

## Decisions

- 2026-10-31: Factory gets `--runner ao` (Agent Orchestrator) beside Orca, default still `orca`.
  AO owns ticket worktrees (`ao spawn --branch` on the claim branch, then the brief via `ao send`
  once the marker is written); a launchd job runs `precheck && tick` hourly (no agent session);
  NEEDS YOU goes by `ao send` to the project's AO orchestrator, reused or spawned, which only relays.
  AO handles are `ao:<session>`, so Orca ledgers are untouched. Dry run on Chazak (2 tickets):
  both merged, final review ran on `factory/<feature>-final-review`, relay answered, uninstall
  removed the heartbeat. Found and fixed: brief said `main` (now default branch); AO workers
  can't use subagents, so the reviewer pass may run inline; AO's PR workflow is ruled out in the brief.
- 2026-10-30: v0.3.1 fixes the first real factory run (Herculean, Iolaus-columns): real Orca `agent launch` replies `{outcome: {handle}}` with no `launch` wrapper, so every launch started the worker, then the tick crashed with `KeyError: 'launch'` and recorded no handle. `launch_worker` now reads `outcome` at the top and still accepts the old wrapped shape; the fake orca replies in the real shape.
- 2026-10-29: PR #6 merged to main (merge commit c398dd6) at your request.
- 2026-10-29: At the turn cap the hook lets exactly one command through: the worker's
  own `workflow.py factory report <NN> blocked` (no shell operators), so a capped ticket
  lands in needs-you with the worker's reason; every other tool call stays refused.
  `build/factory-mode` lands by push + PR against main (your choice); nothing merges
  to main until you approve the PR.
- 2026-10-29: Final-review fixes for factory mode: tick and approve gate with the
  integration branch's `gates.sh`, never the ticket's; a ticket that changes workflow
  control files (`.engineering-workflow/`, `.claude/`, `CLAUDE.md`, `AGENTS.md`, the
  feature's tickets, ...) is held for approval; hooks inside factory worktrees never
  yield to a project pin found there and fail closed instead of hanging; person-only
  commands are refused from ticket worktrees; uninstall stops workers and archives the
  ledger; `precheck` wakes tick whenever a ticket is working, even when paused, so caps
  keep running; `report`/heartbeat ticks run detached so a Bash timeout can't kill a
  merge. README states that Guard is not a sandbox in bypass mode.
- 2026-10-29: The factory's final review runs only when the whole feature is done:
  nothing ready, working or approved, and nothing waiting on you (needs-you, capped,
  interrupted). Until then a running factory idles at no cost; `precheck` wakes it
  when the review becomes due (e.g. after the last `factory approve`). This tightens
  the spec's "nothing ready, working or approved" so a held high-radius ticket is
  never reviewed before it merges.
- 2026-10-29: Factory turn counts and the "permission needed" flag live in a small file
  in each ticket worktree (`.engineering-workflow-state/factory-turns.json`), not in
  `ledger.json`, so hooks never wait on the tick lock while a pre-merge gate runs;
  `tick` copies the count into the ledger. A relaunched (requeued) ticket starts with
  its turn count reset.
- 2026-10-29: The factory's final review writes its findings to
  `.engineering-workflow-state/factory/final-review.md` (agents writing ledger JSON is
  fragile); `factory status` points at that file and the integration card gets a
  `NEEDS YOU: final review ready` comment. `factory uninstall` removes the heartbeat and
  `state.json` only, keeping the ledger, worktrees and branches.
- 2026-10-29: `factory approve` merges only a held ticket, one whose worker reported
  approved (held for high blast radius, failed gate re-run, merge conflict or
  uncommitted changes). Blocked, permission-needed, bypass-stopped and launch-failed
  tickets are refused with "requeue it instead".
- 2026-10-29: Ticket 07 (caps) now waits for 04 as well as 05+06: one generic
  `factory requeue` (needs-you, capped or interrupted → ready, keeping branch and
  worktree) lives in ticket 04, so 07 needs it. The "requeue an interrupted ticket"
  test moves from 05 to 07.
- 2026-10-29: Factory build details fixed for ticket 02 onward: gate script is
  `.engineering-workflow/gates.sh` (from the design doc); factory state and ticket
  worktrees live under `.engineering-workflow-state/factory/` (worktrees in
  `worktrees/<feature>-<NN>`); install ignores the state dir through
  `.git/info/exclude`, not `.gitignore`, so the integration checkout stays clean for
  merges; `state.json` also records `integration_checkout`. Workers launch without
  `--model`; only the heartbeat uses `--model sonnet`.
- 2026-10-29: Orca spike done (ticket 01): Orca launches Claude with
  `--dangerously-skip-permissions` by default and the factory can't change that.
  Bypass becomes an opt-in: `factory install --allow-bypass`. Without it, `tick`
  detects a bypass-launched worker, stops it, sends the ticket to needs-you and pauses.
  In ticket worktrees, Guard `ask` becomes `deny` + needs-you ("permission needed")
  so no worker waits on a prompt. Heartbeat uses `--model sonnet` (haiku hit an API
  400). Spec, tickets 02 and 07 updated.
- 2026-10-29: `factory set` is back in the factory spec and ticket 08 (overrides the
  ponytail cut below): it changes concurrency, build slots, caps and the pile limit,
  rejecting unknown settings and invalid values. The other three cuts stand.
- 2026-10-29: Ponytail (full) governs all factory-mode and skill-routing work until
  v0.4.0 is pushed: reuse what exists, stdlib first, shortest working diff, cut
  speculative commands.
- 2026-10-29: Ponytail cuts to both specs: no `factory set` (edit the factory
  `state.json` by hand; `tick` validates it), no `digest.md` (`factory status`
  summarises the last wave from the ledger), no `addon list` (the session report
  shows add-ons), no `pack list` (the packs file and project links show it). Factory
  ticket 08 updated to match.
- 2026-10-28: Skill routing spec written (`.scratch/skill-routing/spec.md`,
  ready-for-agent), release v0.4.0. Settled: add-ons fetched by git tag and pinned by
  tag + commit + file hashes, verified at session start (tampered = reported, not
  trusted); Claude-only add-ons skipped on other platforms with a report; packs are
  defined in user config, never in the repo; new `ticket start|update|done` command
  writes format-1 state files that ew-flightdeck reads, shared by SDD and factory;
  `docs --decline-graph` remembers a "no" to the graph offer. Test seam: the
  `workflow.py` CLI with fake add-on git repos and a temp HOME.
- 2026-10-28: Factory mode split into 10 tickets under `.scratch/factory-mode/issues/`:
  01 Orca spike (manual), 02 tracer, 03 order/limits, 04 risk/needs-you, 05 modes,
  06 build queue, 07 caps (high radius: Guard hook path), 08 back-pressure/reporting,
  09 final review/brief/install offer, 10 release v0.3.0.
- 2026-10-28: Factory spec written (`.scratch/factory-mode/spec.md`, ready-for-agent).
  Changes from the design draft: state lives in `.engineering-workflow-state/factory/`;
  ticket worktrees come from `git worktree add` on the claimed branch, then
  `orca agent launch`; the turn hook finds its ticket via a marker file in the
  worktree, not an env var; needs-you is the Orca card (`in-review`, `NEEDS YOU:`
  comment, unread dot), not orchestration gates; a ticket without a blast radius is
  treated as high; v1 reads tickets only from the local `.scratch/` tracker. Added
  `factory approve` and `factory requeue` for clearing the pile. Test seam: the
  `workflow.py` CLI as a subprocess with a fake `orca` on PATH.
- 2026-10-28: Build queue in v1: workers and `tick` run `gates.sh` only through
  `workflow.py factory gate`, which holds one of `build_slots` (default 1) lock-file
  slots (`fcntl.flock`). Queue wait is logged per ticket and excluded from
  `max_minutes`. Each worker reports one `--slowed-by` line; the cycle digest shows
  them next to total queue wait.
- 2026-10-28: Factory loop is owned by code (from Super Simple Software Factory):
  `workflow.py factory tick` (Python, idempotent, lock file) does sequencing, caps,
  merges and mode changes. The LLM controller is dropped; `ew-factory` becomes the
  one-ticket worker brief; the hourly heartbeat agent only runs `tick` on a cheap
  model. Workers end with `factory report`, which runs `tick`.
- 2026-10-28: Branch claims (from addyosmani/factory): `tick` claims a ticket by
  creating `factory/<ticket-id>`; an existing branch means claimed. With a remote,
  first push wins.
- 2026-10-28: Gate script (from addyosmani/factory): per-project
  `.engineering-workflow/gates.sh` ending in `GATES: PASS|FAIL <checks>`; a missing
  required check is a FAIL; `tick` re-runs it before merging. The reviewer also proves
  the new test fails without the change.
- 2026-10-28: Review-pile back-pressure (from addyosmani/factory): `stop_if_waiting`
  (default 5) counts gates, high-radius approvals and capped tickets; at the cap `tick`
  starts no new tickets until the pile is cleared.
- 2026-10-28: Factory mode and skill routing are one plan: the factory's final review
  is multi-model-review (it always runs on Orca), its workers use the routed skills,
  and its hooks write the same ticket state files `ew-flightdeck` reads. Both designs
  merged to main together.
- 2026-10-28: design-genius (`JasonJosephIT/design-genius`) is an EW add-on and the
  one global design skill; it replaces frontend-team, which is removed. EW routes any
  spec or ticket that changes UI to `design-director`, and runs its `critique` at
  branch review when UI changed. Design asks outside tickets stay user-prompted.
- 2026-10-28: Add-ons install via `workflow.py addon install|list|remove`, pinned and
  verified like EW skills. Domain packs link into one project via `workflow.py pack add`
  (`web-design`, `output-engine`, `personal`).
- 2026-10-28: With Orca available, multi-model-review replaces ew-matt-code-review +
  ew-ponytail-review at branch review. Its repo is private
  (`JasonJosephIT/multi-model-review`).
- 2026-10-28: The dashboard is a fork of FlightDeck (`ew-flightdeck` add-on). Panels:
  main, architect, tickets, last prompt. Tickets come from per-ticket state files that
  EW hooks write; factory mode uses the same files.
- 2026-10-28: Skill routing (`docs/skill-routing.md`, branch `feature/skill-routing`)
  ships right after factory mode, not before it.
- 2026-10-28: EW routes to graphify, multi-model-review and codebase-explainer only
  when installed, and gets an install endpoint for them as EW add-ons.
- 2026-10-28: multi-model-review gets its own versioned repo. With Orca available it
  runs at every branch review; without Orca it runs only when the user asks.
- 2026-10-28: EW offers to build a graph in an engineering repo that has none.
- 2026-10-28: Only frontend-team, graphify and watch-lite/plus stay global; every other
  non-EW skill becomes a domain pack.
- 2026-10-28: FlightDeck gets a full EW revamp: keep the main (context/cost) and
  architect panels; replace agents and gate with the tickets in progress (across
  sessions); drop the session log but keep "last prompt" time.
- 2026-10-28: Per-ticket turn cap: 100 agent turns (counted by the workflow's
  PostToolUse hook via `EW_FACTORY_TICKET`) plus a 90-minute wall-clock backstop
  (`worker-stop`). A capped ticket goes to Needs-Human with a "what factory change
  prevents this?" note for the Idea Shelf.
- 2026-10-28: Tickets carry `blast_radius: low | medium | high`, set by `/to-tickets`
  and approved with the tickets. v1: `high` needs human approval before merging into
  the integration branch; v3 auto-merge reads the same field.
- 2026-10-27: Factory mode keeps the planning front half unchanged (grill / Wayfinder →
  to-spec → to-tickets); the install offer comes after tickets are approved.
- 2026-10-27: Runs on Orca: one hourly `orca automations` heartbeat with a precheck
  (`workflow.py factory precheck`) so empty or paused runs cost nothing.
- 2026-10-27: Pause has two kinds: drain (no new tickets; in-flight tickets finish, then
  pause) and stop (`pause --now`, interrupt mid-ticket; worktrees stay, ledger marks
  `interrupted`, next cycle resumes).
- 2026-10-27: Default concurrency is 3 tickets.
- 2026-10-27: Lives in this repo as a new `ew-factory` skill plus a `workflow.py factory`
  subcommand, released as v0.3.0.
- 2026-10-27: One cycle = one wave (every ticket ready at that moment), then pause.
  Default kept; not yet confirmed.
- 2026-10-27: Code lands on the integration branch only; the factory never merges to
  main, deploys, publishes issues or uses bypass permissions.

## Open items / waiting on

- Unverified on real Orca: `terminal read` output shape (bypass check now fails
  closed if it can't read), and that `terminal show` reports `connected: false` only
  for dead workers.
- Untested paths: git timeouts on worktree add/merge/remove; requeue of a leftover
  claim whose branch is gone. A claim rejected by another host's push retries each tick.
- Follow-up: `factory.state_dir` trusts the `state_dir` in a worktree's marker file,
  which the worker can rewrite; derive it from the worktree's location instead.
- Guard is not a sandbox in bypass mode: a worker can edit its own counters/marker or
  any reachable file; the time cap and the control-file merge hold are the backstops.

## Idea Shelf

- v2: post-merge verifier on the integration tip; stale-ticket requeue; CI shepherd for
  the integration → main PR.
- v3: operate stations (incident-response, perf watch); feedback → draft tickets for
  human approval; risk-tiered auto-merge to main.
- Cross-project Needs-you queue across every factory on one Orca host.
- From theSeniorDev's software-factory video (watched 2026-10-28):
  - Deterministic quality gates fed back to the implementer: lint, types, duplication,
    cyclomatic complexity, dead code.
  - Before/after screenshots and videos per ticket, using Orca's built-in browser.
  - Smoke-test subset on every merge, plus a QA agent that only knows the user and
    the feature.
  - Intake agents: triage from Sentry/Slack, refinement with repro evidence, prioritizer.
  - Anonymized, production-shaped seed data so agents can reproduce bugs.
  - Monthly bug-cluster review of closed tickets to find architecture problems.
  - Docs/changelog agent; strip issue-reference comments agents leave in code.
  - Not adopting: his "TDD is a waste of tokens" stance; the workflow keeps TDD at
    public seams.
- From Theo's "How To Give Claude Unlimited Usage" (watched 2026-10-28):
  - Remote build compute when queue wait grows: Orca SSH hosts first, then disposable
    VMs (he uses a service the captions call "boat.dev"; unverified).
  - Snapshot a warm, built checkout so workers skip full setup.
  - Goal tickets that climb a measurable target ("2x faster, all checks pass").
  - AI judge panel comparing screenshots for goals with no code check.
