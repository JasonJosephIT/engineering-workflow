# Engineering workflow

This is the shared engineering process. Platform mappings live in `adapters/`.
At session start, run the installed `workflow.py session --project . --platform
<claude|codex|gemini>` command from your bootstrap instructions. Report the version,
revision, integrity result, platform and capability limitations before substantive
work. A project pin overrides a user installation. Never silently upgrade.
If verification fails, stop workflow execution and report the mismatch.
If a cloud platform cannot execute hooks, perform the same check explicitly;
do not claim Guard enforcement or automatic continuation there.

## Skill resolution

Use the skill names in `workflow.lock.json`. Matt Pocock skills use `ew-matt-`,
personal skills use `ew-`. An upstream reference such as `mattpocock-skills:tdd`,
`tdd`, or `/to-spec` means the corresponding `ew-matt-` skill. Ponytail references
mean `ew-ponytail`. Preserve upstream relative reference paths. If a native Skill
tool is unavailable, read the indicated SKILL.md and its relevant references.
User-only invocation metadata remains binding: ask the human to invoke setup,
grilling entry points, Wayfinder, to-spec and to-tickets when needed; a pipeline
description does not override their explicit-only policy.

## Planning

Use grill-with-docs for a single-session code design, grill-me for non-code work,
or Wayfinder for an uncertain multi-session route. Wayfinder resolves decisions;
it does not build the product. Then to-spec confirms public testing seams, and
to-tickets proposes vertical slices and blocking edges for user approval.
Configure the issue tracker using setup-matt-pocock-skills once per project.
Local tickets must be committed to survive cloud sessions; GitHub issues are an
alternative when authorized. Do not publish issues without that authorization.

During explicitly invoked grilling, discover project audience, goals and
`public_facing` status (`unknown`, `yes` or `no`). For public-facing projects,
address all eight sections of
Open Thoughts' versioned portfolio contract: load the configured source rather
than copying or redefining it here. Record sourced answers, open questions and
reasoned non-applicability; never silently mark a section passed. The source
contract and ADR-002 distinguish completeness from factual review and approval.
If the source is missing, discovery remains incomplete; do not invent substitutes.
This supplements the invoked planning skill without invoking grilling implicitly.

Keep project identity and discovery in `.engineering-workflow-project.json`,
outside the installed runtime: project UUID, audience/goals, public-facing status,
standards source/version/hash, discovery entries and stable implementation key to
UUID mappings. Preserve it across reinstall. Public-facing describes the intended
project audience; it grants no permission to publish project facts or reviews.

## Implementation and review

Use ew-subagent-driven-development for approved build tickets, or ew-matt-implement
for one small ticket. Before starting, batch any contradictions between the spec,
tests and review standards for a human decision. Do not implement on main/master
without consent. Independent ready tickets may run in parallel, one worktree each,
created from the integration branch tip. Merge each blocker before its dependants.
Use fresh agent contexts containing only the ticket and a focused context pack.

Implementers load ew-ponytail then ew-matt-tdd: existing code, stdlib and native
facilities first; no speculative flexibility. Test at approved public seams with
red/green evidence. Run focused checks while iterating, the full relevant suite
before commit. TDD governs testing if Ponytail's minimum-check advice is weaker.

Per ticket: one implementer, one independent spec-and-quality reviewer, at most
one fix/re-review round. Escalate a second failed review to the controller; never
silently waive findings or loop indefinitely. Use the cheapest capable model
available on the actual platform. Claude uses Sonnet for mechanical tickets and
ticket review, Opus for other implementation. Other platforms use native models;
do not pass Claude aliases to them. Record the choice; do not invent model IDs.
Keep context lean and recover from the on-disk ledger after compaction.

Review packages cover the recorded ticket base through its final tip. Reviewers
inspect code and test evidence, rerunning focused checks only for concrete doubts.
Log completion only after review approval and integration. Work continuously
between approved tickets; pause for unresolved blockers or decisions, not routine
check-ins. Never message other people without authorization.

Once per branch: ew-matt-code-review runs its Standards and Spec axes as two
independent review contexts; then ew-ponytail-review checks bloat. These two axes
are the explicit exception to the one-reviewer ticket budget. Consolidate findings
into one fix pass. Security review is required when auth, trust boundaries, secrets
or payments change; use native security review if present, otherwise an explicit
security-focused review. Do not pretend a missing slash command exists.

## Factory mode

After the human approves to-tickets output, offer four choices: build here (SDD,
above); install and run (`workflow.py factory install --feature <slug>`); install
paused (`--paused`, start later with `factory resume`); or one cycle (install
`--paused`, then `factory cycle` for one wave). The factory needs a runner (Orca by
default, or Agent Orchestrator with `--runner ao`), a committed gate script and an
integration branch that is not main/master. Pass `--allow-bypass` only when the
human accepts the runner's permission-bypass launch. An hourly heartbeat (an Orca
automation, or a launchd job for AO) runs `factory tick`; each ticket gets its own worktree and
worker following the ew-factory worker brief, and a final review runs when the
feature is done. A feature with an approved `.scratch/<feature>/climb.md` first gets
one ew-hill-climb run (the climb brief) after its last ticket merges, and the final
review waits for that climb. `factory queue <feature>` lines up another feature whose
tickets are approved: after the final review is dispatched, the factory builds that
feature instead of pausing, and pings the human on each ticket it merges. The factory merges only into the integration branch; it never
merges to main, pushes to main, deploys or publishes issues. Tickets that need the
human show NEEDS YOU on their Orca cards, or reach the human through the project's AO
orchestrator session; once `stop_if_waiting` (5) of them are
needs-you or capped, the factory holds and starts nothing new. Use `factory status`
for state and the last wave's summary, `factory set <setting> <value>` to change
concurrency, build slots and caps, `factory pause` / `resume` to control it and
`factory uninstall` to remove it.

## Human implementation reviews

Use ew-implementation-review at meaningful implementation checkpoints and final
handoff. Give the human a short review in the session chat and queue the same
review for Open Thoughts. Cover outcome, purpose and decisions, evidence and its
limits, relevant standards implications, and what needs the human's attention.
Only address contract sections relevant to the implementation; record uncertainty
or gaps honestly. This narrative summarizes existing evidence. It adds no reviewer
rounds, replaces no mandatory tests or independent review, grants no approval and
never establishes completion by itself.

Use the producer CLI to configure the project, upsert a review with its stable
implementation key and expected base revision, attach feedback, and sync. Start
with base revision zero; on conflict, read the current review and reconcile rather
than overwriting it. Preserve implementation/session references and distinguish
human feedback from agent interpretation. Feedback classifications are feedback,
local clarification and shared-standard proposal. Shared proposals remain private
and unadopted until a human adopts them through Git in the standards source;
project feedback cannot silently change the shared contract.

Canonical narratives and feedback belong in the Daydreamer private bundle. The
producer's private outbox lives outside the repository; `--state-dir` selects an
explicit alternative. Sync writes only to a local private bundle, selected by
`--bundle`, `DAYDREAMER_BUNDLE`, or the existing home-relative Open Thoughts/daydream
convention. The private Git bundle must already exist; sync never pushes.
Existing private Git transport is external to this workflow. A cloud
session queues an outbox for explicit import into the local private workflow;
there is no new public API for private writes. Report queued, synced and failed
states accurately. Preserve existing capture once; full Codex/Gemini transcript
capture is deferred. Hooks may advertise missing checkpoints, but never infer
completion or start paid calls.

## Completion and context

Use ew-verification-before-completion: fresh evidence before success claims.
Use ew-finishing-a-development-branch, honoring integration choices already
authorized by the user. Never discard work or force-push without explicit consent.
Preserve harness-owned worktrees. A release requires separate release validation.

Use GLOSSARY.md (or GLOSSARY-MAP.md), docs/adr/, operational docs/agents/ tracker
configuration, and generated graphify-out/GRAPH_REPORT.md. Specs and tickets are
intent, so retain them. Avoid hand-written documentation restating implementation.
Read graph navigation before broad exploration when present; trust current code
over a stale graph. Refresh and commit graph output after integration if Graphify
is installed. Graphify is optional and not bundled; report when refresh is skipped.

## Scope and overlap

The selected bundle owns planning, SDD, Ponytail, Guard, goal persistence and
docs-health. Do not invoke retired Superpowers, general engineering, Taskmaster,
build-loop/build-mvp or upstream implement-spec as a second orchestrator.
No Runpod or entertainment. TypeSafe is optional application AI tooling, not
required for computer control or this process. Headroom is optional startup runtime
support only; enable one startup owner and no repeated shell hook. Keep native
permissions and sandboxes. Autopilot never bypasses them.
