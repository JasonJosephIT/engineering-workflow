# 06: Build queue with recorded wait

**What to build:** A person running several tickets at once sees builds and full test runs take turns through a fixed number of build slots, and can see how long each ticket waited.

**Blocked by:** 02

**Status:** ready-for-agent

**Blast radius:** low

- [ ] `factory gate` holds one of `build_slots` (default 1) slots while the gate script runs and releases it afterwards, including when the process dies
- [ ] A second concurrent `gate` waits for a free slot rather than running alongside
- [ ] When run for a ticket, queue wait and gate run time are recorded in that ticket's ledger entry
- [ ] `tick`'s pre-merge gate goes through the same queue
