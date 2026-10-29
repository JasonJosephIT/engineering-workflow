# 03: Ticket order, concurrency and claim safety

**What to build:** A person with many tickets sees the factory honour the blocking order from `/to-tickets`, keep at most the configured number of tickets building at once, respect the daily start cap, and never start the same ticket twice even when two ticks run at the same moment.

**Blocked by:** 02

**Status:** ready-for-agent

**Blast radius:** low

- [ ] A ticket starts only when every ticket in its `Blocked by` line has merged into the integration branch
- [ ] No more than `concurrency` (default 3) tickets are working at once; more start as others finish
- [ ] No more than `daily_ticket_cap` (default 10) tickets start per calendar day
- [ ] Two concurrent `tick` runs never claim or merge the same ticket (tick lock); an existing claim branch counts as already claimed
- [ ] With a remote configured, the claim branch is pushed and a rejected push is treated as already claimed
- [ ] Ready tickets start in tracker order
