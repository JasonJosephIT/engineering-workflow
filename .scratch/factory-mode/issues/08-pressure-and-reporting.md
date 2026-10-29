# 08: Back-pressure, slowed-by and the wave summary

**What to build:** A person never comes back to more than a handful of things waiting on them, can see what slowed the factory down, and sees the factory's state the moment they open a session.

**Blocked by:** 04, 07

**Status:** ready-for-agent

**Blast radius:** medium

- [ ] When needs-you plus capped tickets reach `stop_if_waiting` (default 5), `tick` starts nothing and status shows `held`; it starts again once the pile drops below the limit
- [ ] `factory report` accepts `--slowed-by "<line>"` and stores it
- [ ] `factory status` summarises the last wave from the ledger: merges, needs-you items, caps, total queue wait and the slowed-by lines
- [ ] Settings edited by hand in the factory state file (concurrency, build slots, caps, pile limit) take effect on the next tick; an invalid value makes `tick` and `status` fail with a clear error and change nothing
- [ ] The session-start report includes the factory status line when a factory exists for the project
