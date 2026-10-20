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
