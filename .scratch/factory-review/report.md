# Engineering workflow review: factory, climb and Agent Orchestrator

Reviewed 2026-11-10 at main `79c5a3f` (VERSION 0.4.0). Labels: **verified** = read
in code or reproduced; **inferred** = reasoned, not run.

Inputs: none supplied, so this repository is the only source. Software Factory =
factory mode; Hillclimb Factory = the per-feature climb (`ew-hill-climb`); Agent
Orchestre = Agent Orchestrator (`--runner ao`). Missing: separate product specs,
and live AO behaviour (no `ao` or `orca` call was made).

## 1. Summary of current state

- Python owns the loop: `factory tick` claims tickets, launches one worker per
  ticket worktree, re-runs `gates.sh`, merges into an integration branch, enforces
  caps and holds high-risk work for approval.
- Runners: Orca (default) and AO (launchd heartbeat, an orchestrator session
  relays NEEDS YOU).
- New on main: one climb worker after all tickets merge, then the final review,
  then `factory queue` moves to the next feature.
- Health: 152 tests pass (284 s); `verify` passes.
- Evidence: Orca has one live run, AO a two-ticket dry run. Climb and queue ran
  against the fake Orca only (STATUS, 2026-11-04).

## 2. Identified issues / gaps

Release
1. **Main is unreleased and looks current.** The installed runtime is tag v0.4.0
   (`88a74c1`): no climb code, no queue, no `ew-hill-climb`. Main is also "0.4.0",
   so the session check reports up to date. Verified.

Factory core
2. **A worker's report waits behind a merge gate.** `report` takes the tick lock
   (`factory.py:1051`); `tick` holds it through gates (`:913-918`). Reproduced: a
   5.5 s wait behind a 6 s lock. Gates may run 90 minutes; agent commands time
   out within 10, so a finished ticket can end "interrupted". *Fixed in 0.5.0.*
3. **The daily cap resets between queued features.** `advance` clears the ledger
   (`:859`); the cap counts the ledger only (`:722`). Reproduced: room 0, then 3.
   *Fixed in 0.5.0.*
4. **The gate tests the ticket branch, not the merged result** (`:522`, `:551`).
   Two passing tickets can leave a red tip that the climb baselines on. On the
   Idea Shelf already; queue and climb raise its priority.
5. **The final review is unsupervised.** No ledger entry, liveness check, caps or
   result; "dispatched" is final (`:894`). On Orca it runs inside the integration
   checkout while merges land there (`:885`). The queue advances before findings
   exist (`:896`).

Climb
6. **Code does not check the score.** Only Status and Blast radius are parsed
   (`:398-404`); Metric, Target and Budget are prose. The merge trusts the
   worker's "approved", unlike tickets.
7. **Harness lock and held-out set rely on the agent**, which can read and edit both.
8. **Climbs share ticket caps** (100 turns, 90 minutes). A 15-round budget probably
   caps first. Inferred.
9. **`hill-climb/log.md` is one path for every feature**; the skill's
   parallel-worktree advice creates worktrees outside the hooks and caps.

Agent Orchestrator
10. **Per-ticket review is not independent.** AO workers cannot use subagents, so
    the implementer reviews itself (`SKILL.md:20`), against WORKFLOW.md.
11. **Heartbeat PATH is minimal** (`:200-201`): ao, git, `/usr/bin`, `/bin`. A
    heartbeat-run gate may not find node or Homebrew tools. Inferred.
12. **Notification rests on an LLM relay.** Pings are not retried (`:266-273`);
    the spawn id is regex-parsed from text (`:155`).

Docs and packaging
13. `docs/factory-mode.md` still says "proposal, nothing built"; `adapters/claude.md`
    names Orca only; briefs hard-code `ew-` names that plugin installs lack (`:608`).

## 3. Recommended improvements

| # | Change | Why | Fixes |
|---|---|---|---|
| R1 | Release main as v0.5.0 and reinstall; session check compares lock digests. | Climb cannot run until installed. | 1 |
| R2 | Workers write `reports/<id>.json` atomically, no tick lock; `tick` consumes them. | A report must never wait on someone else's gate. | 2 |
| R3 | Keep daily starts in `state.json` by date. | A spend cap must survive ledger archiving. | 3 |
| R4 | Merge the integration tip into the ticket worktree, gate, then fast-forward. | The tested tree equals the merged tree. | 4 |
| R5 | Make the review a ledger entry: own worktree at the pinned tip, caps, a reported result; queue advances on clean or your approval. | No stacking on unreviewed code. | 5 |
| R6 | Code-owned climb: validate `climb.md` at install/queue; `tick` measures baseline and final, holds on no gain or harness changes; caps from Budget; log per feature; no parallel worktrees. | Restores "tick trusts only its own run". | 6-9 |
| R7 | On AO, `tick` spawns a separate reviewer session when a worker reports (state `reviewing`). | Restores independent review. | 10 |
| R8 | `factory doctor --runner`: checks CLI reply shapes and runs the gate in the heartbeat's environment. Write `needs-you.md` beside the relay. | v0.3.1 was a reply-shape crash; notification should not need an LLM. | 11, 12 |
| R9 | Rewrite `docs/factory-mode.md` as current; fix the adapter; resolve skill names from the lock. | Agents read these as truth. | 13 |

Order: R1, R2, R3 (small, verified), then R6, R5, R4, R7.

## 4. Integration considerations for Agent Orchestrator

- macOS only: the heartbeat is hourly launchd, a backstop behind worker reports,
  so a dead worker can sit for an hour.
- AO owns worktrees; the factory finds them by claim branch, so AO must keep one
  worktree per branch.
- The brief forbids AO's PR workflow; nothing enforces it.
- The bypass check reads two project-config keys (`:180-181`).
- Unknown from this repo: AO's JSON contracts across versions, and whether
  `ao spawn` works under launchd's PATH. Record the tested AO version in state.

## 5. Suggested validation / testing plan

1. **Unit, fake runners, one failing test per fix first:** report returns in
   under 1 s while the tick lock is held; daily cap holds across `advance`; two
   individually green tickets that break together are stopped; a climb with no
   metric gain or a changed harness is held; a silent reviewer is capped.
2. **Contract:** `factory doctor` against real Orca and AO.
3. **Live AO run on a throwaway repo:** two tickets, a `climb.md` and one queued
   feature, with a 3-minute gate, `daily_ticket_cap 2`, one forced NEEDS YOU and
   one heartbeat-only tick. Pass: nothing interrupted, cap holds, message arrives,
   score recorded by code.
4. **Release:** full tests, `verify --expected 0.5.0`, `freeze`, then a fresh
   session shows `ew-hill-climb`.
