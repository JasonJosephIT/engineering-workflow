# 09: Final review, worker brief and the install offer

**What to build:** A person who resumes a factory gets a whole feature finished unattended, ending in a final branch review and a paused factory, and the workflow offers the factory at the right moment after `/to-tickets`.

**Blocked by:** 05

**Status:** ready-for-agent

**Blast radius:** medium

- [ ] In running mode, when nothing is ready, working or approved, `tick` launches one final-review agent in the integration checkout and pauses; it does this once
- [ ] `factory uninstall` removes the heartbeat and keeps the ledger, worktrees and branches
- [ ] A new `ew-factory` skill holds the one-ticket worker brief (ponytail, TDD, gate through `factory gate`, fresh reviewer proving the new test fails without the change, one fix round, `factory report` last) and the final-review brief (multi-model-review when installed, otherwise code-review then ponytail-review, plus security review when relevant)
- [ ] `tick` launches workers with that brief
- [ ] The core workflow and Claude adapter describe the factory and the install offer after `/to-tickets` approval (build here, install and run, install paused, one cycle)
- [ ] The new skill is in the lock and discoverable under its `ew-` name
