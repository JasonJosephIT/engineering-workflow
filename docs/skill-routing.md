# Skill routing, add-ons and the EW dashboard (design, 2026-10-28)

Status: grilled, decisions settled; next step is `/to-spec`. Nothing built.
Branch: `feature/skill-routing`. Ships right after factory mode (v0.3.0).

## Problem

EW names only `ew-` skills. Graphify, codebase-explainer and multi-model-review are
wired into no stage. About 150 skills load in every Claude session, pushing ~65 skill
descriptions out of the listing, so even EW skills sometimes can't auto-trigger. There
is no single view of which tickets are being worked on.

## Decisions

### 1. Stage → skill routing (in `core/WORKFLOW.md`, all platforms)

| EW stage | Routed skill | When |
|---|---|---|
| Session start | graphify | `graphify-out/` exists: read `GRAPH_REPORT.md` before broad exploration |
| Session start | graphify | engineering repo with no graph: offer once to build a code-only graph (no LLM); a "no" is remembered for that repo |
| Planning (grill / Wayfinder / to-spec) | graphify query | before reading code for a question |
| Planning | codebase-explainer | unfamiliar repo, or the user asks to explain it |
| Build (SDD) | graphify | context packs start from graph neighbours of the ticket's files |
| Bug / failing test | ew-matt-diagnosing-bugs | anything broken, throwing or slow |
| Branch review, Orca available | multi-model-review | every branch; **replaces** ew-matt-code-review + ew-ponytail-review (its rounds 1–2 cover both axes) |
| Branch review, no Orca | ew-matt-code-review → ew-ponytail-review | every branch; multi-model-review only when the user asks |
| Spec or ticket that changes UI | design-genius `design-director` | sets direction before the build (Direction → Build → Review) |
| Branch review, UI changed | design-genius `critique` | alongside the branch review above |
| Design ask outside a ticket | design-genius | not routed; the user prompts it |
| After merge | graphify update | refresh and commit `graphify-out/` |

Routed add-ons are used **only when installed**; `workflow.py session` reports which
were found. A missing add-on is reported, never faked.

### 2. Add-ons and domain packs (`workflow.py`)

- `workflow.py addon install|list|remove <name>`: add-ons are pinned (version + hash)
  and verified like EW's own skills. Add-ons: graphify, multi-model-review,
  codebase-explainer, design-genius (`JasonJosephIT/design-genius`), ew-flightdeck.
- `workflow.py pack add|remove <pack>`: links a domain pack into one project only.
  Packs: `web-design` (awwwards ×5, genjutsu cast/bunshin/paint, clone-website,
  extract-design, dembrandt, generate-ui-from-brand), `output-engine`, `personal`
  (brag-slim, tailoring-resumes, financial-insights, create-payment-credential,
  use-link-identity).
- Global outside EW: design-genius, graphify, watch-lite/plus only. design-genius
  replaces frontend-team, which it already consolidates; frontend-team is removed.

### 3. multi-model-review gets its own repo

Private repo `JasonJosephIT/multi-model-review`, created from the current skill,
versioned and installed as an EW add-on.

### 4. ew-flightdeck: the EW dashboard (Claude only)

Fork of FlightDeck (MIT) in its own add-on repo. Mods draw in the terminal and the
desktop app's Code tab, not on a phone over Remote Control.

| Panel | Keep / change |
|---|---|
| main (model, context, cost, rate limits) | keep |
| architect (consults timeline) | keep; EW reviewers count as the architect |
| tickets | new: one row per ticket in progress across all sessions and projects, with its agents and permission checks (replaces agents + gate) |
| last prompt | new one-liner: time since the user's last prompt |
| log, loops, receipt | removed |

Ticket source: EW hooks write one small JSON state file per active ticket into EW's
local state folder (outside any repo); the mod reads them on a timer. Factory mode's
tickets use the same files.

## Not decided here (spec details)

- How each add-on is fetched (git tag vs package manager) and pinned.
- Claude-only add-ons (ew-flightdeck) on Codex/Gemini: skipped with a report.
- Release number after v0.3.0.
