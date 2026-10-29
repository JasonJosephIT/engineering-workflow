# 01: Orca spike: confirm unattended Claude on this host

**What to build:** A person runs a short manual check on this machine and records exactly which Orca commands and behaviours the factory can rely on, so the Orca adapter is built on facts rather than guesses. Spec: `.scratch/factory-mode/spec.md` (Further Notes).

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

**Blast radius:** low

- [ ] An Orca automation with a precheck runs Claude unattended in the current permission mode, and a failing precheck records a skipped run with no agent started
- [ ] The heartbeat accepts a cheap-model extra agent argument (or the alternative that works is recorded)
- [ ] An agent launched with `orca agent launch` into an existing `git worktree` checkout (not created by Orca) starts with a given prompt
- [ ] The engineering-workflow hooks (SessionStart, PreToolUse, PostToolUse) fire inside that Orca-launched agent
- [ ] A worker can run a `workflow.py` command as its last step without a permission prompt blocking it
- [ ] The commands for setting a card's status, comment and unread dot on that worktree, for checking whether its agent is alive, and for stopping it are confirmed
- [ ] Findings, with the exact command shapes and JSON fields, are appended under `## Comments` in this file, and any spec change they force is noted in STATUS.md
