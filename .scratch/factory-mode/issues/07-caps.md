# 07: Turn and time caps

**What to build:** A person can leave the factory overnight knowing a looping agent stops at 100 turns or 90 working minutes, keeps its work, and waits for them, and that a worker that died is noticed.

**Blocked by:** 05, 06

**Status:** ready-for-agent

**Blast radius:** high

- [ ] Inside a ticket worktree (found through its marker file), the PostToolUse hook increments the ticket's turn count
- [ ] Once turns reach `max_turns`, the PreToolUse hook refuses every tool call with a message telling the agent to report blocked
- [ ] `tick` stops a worker whose working minutes (wall time minus recorded queue wait) exceed `max_minutes`, or whose turns reached the cap, and marks it capped with its worktree kept
- [ ] `tick` marks a working ticket interrupted when the adapter reports its worker dead and it never reported
- [ ] `factory requeue` returns a capped ticket to ready
- [ ] Hooks outside ticket worktrees behave exactly as before (existing hook tests still pass)
