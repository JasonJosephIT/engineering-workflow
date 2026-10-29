# 05: Pause (drain and stop), resume, one cycle

**What to build:** A person can pause at a ticket boundary, stop everything mid-ticket without losing work, resume until the queue is empty, or run exactly one wave and have the factory pause itself, and the heartbeat costs nothing while there is nothing to do.

**Blocked by:** 02

**Status:** ready-for-agent

**Blast radius:** medium

- [ ] `factory pause` stops new starts; in-flight tickets finish, then the mode becomes paused
- [ ] `factory pause --now` stops every worker through the adapter, keeps their worktrees and branches, marks them interrupted, and pauses
- [ ] `factory requeue` on an interrupted ticket resumes it from its existing branch and worktree
- [ ] `factory resume` sets running and runs `tick`
- [ ] `factory cycle` starts one wave (every ticket ready right now), records it, and the mode returns to paused once every ticket in the wave is merged or waiting on the person
- [ ] `factory precheck` exits 0 only when the mode is not paused and there is ready, working or approved work; otherwise non-zero
