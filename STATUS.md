---
status: active
progress: 30
next_date: 2026-10-28
updated: 2026-10-28
---

# STATUS

## Now

Designing factory mode (v0.3.0): an opt-in, Orca-hosted loop that keeps building
approved tickets in parallel after `/to-tickets`, with install / pause (drain or stop)
/ resume / one-cycle controls. Design draft: `docs/factory-mode.md` (+ `.html`).
Skill routing, add-ons and the `ew-flightdeck` dashboard are designed to ship right
after it (`docs/skill-routing.md`). `docs/ew-map.svg` shows how both fit the workflow.
Both designs are merged to main. Factory spec: `.scratch/factory-mode/spec.md`. Nothing built yet.

## Next

1. `/ew-matt-to-tickets` from `.scratch/factory-mode/spec.md`; first ticket is the
   manual spike (unattended Claude via Orca, hooks firing in Orca-launched agents,
   cheap-model heartbeat, worker running `factory report`, Orca card/stop/liveness).
2. Right behind factory mode: `/ew-matt-to-spec` from `docs/skill-routing.md`, then
   `/ew-matt-to-tickets`.

## Decisions

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

- Unverified: whether Orca automations can run Claude unattended under the current
  permission mode.
- Confirm "one cycle = one wave".
- Unverified: whether Claude agents launched by Orca run the workflow's PostToolUse
  hook (the turn cap depends on it). Check in the same spike.
- Unverified: whether the heartbeat accepts `--extra-agent-args="--model haiku"`, and
  whether a worker can run `factory report` as its last step. Same spike.

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
