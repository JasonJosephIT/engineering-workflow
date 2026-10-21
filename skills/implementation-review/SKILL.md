---
name: ew-implementation-review
description: Present a concise human implementation review at meaningful checkpoints or final handoff and queue it for the private Open Thoughts workflow.
---

# Implementation review

Read the selected runtime's `core/WORKFLOW.md`. Preserve its mandatory tests,
independent review and bounded review budgets. This is an evidence summary for
the human, not a new reviewer or an approval step.
Use `core/REVIEW_CONTRACT.md` in that runtime for the JSON input and feedback fields.

1. Read `workflow.py project status --project .`. Use the recorded project UUID,
   audience/goals, stable implementation key and pinned external standards source.
   If discovery or the standard is missing, report the gap; never substitute a
   locally invented standard or silently claim a pass. Explicit grilling addresses
   all eight source sections; this review addresses only relevant ones.
2. Gather the actual outcome, implementation references, test/review evidence and
   limits. Preserve session references where available. Mark an interim review
   `checkpoint`; use `complete` only with evidence required by the shared workflow.
3. Show the human a short review covering **Outcome**, **Purpose and decisions**,
   **Evidence and limits**, **Standards implications**, and **Your attention**.
   Name unresolved issues or decisions. Narrative completeness grants no approval.
4. Save a review JSON with `title`, `status`, `sections` containing `outcome`,
   `purpose_decisions`, `evidence_limits`, `standards_implications`, `your_attention`,
   and `references` containing `implementation` strings and `sessions` objects
   (`platform`, `id`). Run `workflow.py review upsert --project . --implementation
   KEY --file FILE --base-revision N --platform PLATFORM`; use zero initially.
   Read `review show` and reconcile conflicts before retrying. Report queue failures.
5. Attach feedback with `review feedback --project . --implementation KEY --file
   FILE`. Preserve human words and distinguish `human` from `agent_interpretation`
   attribution. Classify it as `feedback`, `local_clarification`, or
   `shared_standard_proposal`. A proposal remains private and unadopted until a
   human adopts it in the source Git repository; do not edit shared standards from
   project feedback automatically.
6. Use `review sync --project . [--bundle PATH]` for the local private bundle.
   Canonical narratives and feedback belong there; the private outbox is outside
   the repository (`--state-dir` can select it). Report queued versus synced state.
   Sync requires an existing private Git bundle and never pushes. Existing
   private Git transport is external; cloud outboxes need explicit local
   import. Do not add public endpoints or imply full transcript capture: existing
   capture is preserved once and Codex/Gemini full transcripts remain deferred.

`public_facing` describes project audience independently of publication visibility.
No review, hook reminder or sync operation authorizes publication, infers completion
or starts a paid call.
