---
status: active
progress: 10
next_date: 2026-10-28
updated: 2026-10-28
---

# STATUS

## Now

Designing factory mode (v0.3.0): an opt-in, Orca-hosted loop that keeps building
approved tickets in parallel after `/to-tickets`, with install / pause (drain or stop)
/ resume / one-cycle controls. Design draft: `docs/factory-mode.md` (+ `.html`).
Branch: `feature/factory-mode`. Nothing built yet.

## Next

1. Run `/setup-matt-pocock-skills` once for this repo (no tracker configured yet).
2. Run `/to-spec` from `docs/factory-mode.md` and the decisions below.
3. `/to-tickets`; first ticket is the spike that checks Orca can run Claude unattended
   in this host's permission mode.

## Decisions

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

## Idea Shelf

- v2: post-merge verifier on the integration tip; stale-ticket requeue; CI shepherd for
  the integration → main PR.
- v3: operate stations (incident-response, perf watch); feedback → draft tickets for
  human approval; risk-tiered auto-merge to main.
- Cross-project Needs-you queue across every factory on one Orca host.
