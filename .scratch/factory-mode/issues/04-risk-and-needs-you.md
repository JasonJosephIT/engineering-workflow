# 04: Blast radius, needs-you and clearing it

**What to build:** A person sees risky or failed work stop and wait for them on the ticket's Orca card, and clears it from the command line: high blast-radius tickets wait for approval before merging, and failures land in needs-you instead of being guessed at.

**Blocked by:** 02

**Status:** ready-for-agent

**Blast radius:** medium

- [ ] A ticket with `Blast radius: high`, or with no blast radius line, passes its gate and then waits in needs-you instead of merging
- [ ] A failed gate re-run, a merge conflict, or a worker reporting `blocked` puts the ticket in needs-you with a reason
- [ ] Needs-you sets the card to `in-review` with a `NEEDS YOU: <reason>` comment and the unread dot; working tickets show `in-progress`, merged ones `completed`
- [ ] `factory approve <ticket>` merges a held ticket after re-running its gate
- [ ] `factory requeue <ticket>` returns a blocked ticket to ready
- [ ] Low and medium tickets still merge automatically
