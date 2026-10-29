# 08: Back-pressure, slowed-by and the digest

**What to build:** A person never comes back to more than a handful of things waiting on them, can see what slowed the factory down, and sees the factory's state the moment they open a session.

**Blocked by:** 04, 07

**Status:** ready-for-agent

**Blast radius:** medium

- [ ] When needs-you plus capped tickets reach `stop_if_waiting` (default 5), `tick` starts nothing and status shows `held`; it starts again once the pile drops below the limit
- [ ] `factory report` accepts `--slowed-by "<line>"` and stores it
- [ ] When a wave ends, a digest entry lists merges, needs-you items, caps, total queue wait and the slowed-by lines; `status` shows the latest
- [ ] `factory set <setting> <value>` changes concurrency, build slots, caps and the pile limit, rejecting unknown settings and invalid values
- [ ] The session-start report includes the factory status line when a factory exists for the project
