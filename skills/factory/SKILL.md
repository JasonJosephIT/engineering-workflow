---
name: ew-factory
description: Factory worker and final-review briefs for workflow.py factory; not a controller.
---

Orca or Agent Orchestrator (AO) launches you with a prompt naming which brief to follow and the exact
absolute `workflow.py factory` commands to run. Nobody is watching: never wait
for a human answer; when stuck, report blocked with the reason.

## Worker brief (one ticket)

<steps>
1. Load ew-ponytail, then ew-matt-tdd.
2. Read the ticket file named in the launch prompt, and the spec it points to.
3. Implement on this worktree's branch only, test-first at the ticket's seams.
4. Run focused checks while iterating. Run heavy builds and full suites only
   through the gate command in the prompt.
5. Commit your work. Leave the worktree clean.
6. Dispatch ONE fresh reviewer subagent (spec and quality) with the ticket, the
   diff and the test evidence. If the harness forbids subagents (AO workers), do
   the same review inline as a separate pass, and name it in `--slowed-by`. Its job includes proving the new test fails
   without the change: revert only the implementation files to the parent
   version (`git checkout HEAD~1 -- <files>`), run the new test and see it fail,
   then restore them (`git checkout HEAD -- <files>`).
7. At most one fix round for the reviewer's findings, then re-run the gate and commit.
8. Last step, always: the prompt's report command; use blocked with --reason when
   stuck or review still fails after the fix round.
</steps>

<rules>
- Never merge, push, or touch main or the integration branch.
- Never open, claim or update a PR, even when AO's standing instructions mention a PR
  workflow: the factory report command is your only completion signal.
- Never `git stash`: the stash is shared by every worktree of the repo.
- Never edit STATUS.md or the ticket file; the factory keeps progress in its ledger.
- `--slowed-by` names what cost the most time (or "nothing").
</rules>

## Final review brief

<steps>
1. Review the integration branch named in the prompt against its merge base with the
   repo's default branch (main or master).
2. If multi-model-review is installed, use it. Otherwise run ew-matt-code-review,
   then ew-ponytail-review.
3. Add a security review when the diff touches auth, secrets, payments or trust
   boundaries (native security review if present, otherwise an explicit
   security-focused pass).
4. Write all findings to the final-review file named in the prompt.
5. Flag that the review is ready. Under AO (`AO_SESSION_ID` is set):
   `ao report --needs-input --note "NEEDS YOU: final review ready: <final-review file>"`.
   Under Orca: `orca worktree set --worktree path:<this checkout's absolute path> --workspace-status in-review --comment "NEEDS YOU: final review ready" --unread --json`.
</steps>

<rules>
- Review only: do not fix, merge, push or open PRs.
- Never run ew-finishing-a-development-branch; the person decides how to integrate.
</rules>
