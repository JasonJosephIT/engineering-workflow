---
name: ew-fable
description: Fable 5.2 adapter for this workflow. Use when the session model, a subagent or a factory worker is Fable 5.2 (`claude-fable-5-2`), when writing a brief or ticket a Fable agent will run, or when the user says "gauntlet loop".
---

# Fable adapter

Field guidance for running this workflow on Fable 5.2. It comes from one
practitioner's report (see SOURCES.md), not from measurements in this package, so
treat each rule as a default that session evidence can overturn. It changes how
work is briefed and shaped. `core/WORKFLOW.md` still sets the tests, review budgets,
model choice and permissions.

The report's summary: Fable is *literal*. It builds exactly what the words say,
reaches a higher ceiling than Opus on long work, and needs earlier steering.

## Shape of the work

- **One thread first.** A bounded task goes to one agent on one thread, even when
  that takes longer. This is the shape core already uses: one implementer per ticket.
- **Parallel agents share nothing.** Fan out only where each agent has its own
  files, worktree and goal (independent ready tickets, or a side task that must
  leave the main work alone). Agents whose work interlinks go back on one thread.
- **Two fan-out shapes.** Let the model run its own fan-out (a native workflow,
  only when the human has opted into that spend), or run a gauntlet loop (below).
  Hand-built lanes of cooperating agents are the shape the report saw fail.
- **Narrow, then widen.** When the whole goal comes out mediocre everywhere, get
  one vertical slice to the bar, then scale out from it.

## Writing a brief (a ticket, a subagent prompt, a factory brief)

A brief is a *wish*: the agent grants the words, not the intent. When a result
comes back wrong, rewrite the wish before rerunning it.

1. **Say the thing itself**, in plain exact words: the outcome, the files in
   scope, the public seam to test at. A short precise brief beats a long clever one.
2. **Show it.** Attach the reference: an existing file to match, a screenshot, a
   failing test, sites or modules the human likes. Ask for the patterns across the
   examples, then for work in that league.
3. **Make done a proof.** Name the evidence that must come back: the command and
   its output, a reviewer's verdict, or a blind comparison against a reference.
   This is ew-verification-before-completion written into the brief.
4. **Give ownership.** Write "you own this" and name what is owned: the ticket's
   scope, inside the permissions the agent already has.
5. **Give reasons when steering.** Feedback names what is wrong and why. A bare
   "no" returns more of the same.

Brief is ready when a reader with no other context could say what is in scope,
what the reference is, and what proof ends the work.

## Steering

- **Look early.** Check a long run after its first stretch (about 20 minutes).
  If it is drifting, stop it, state the direction, and continue from there.
- **Ceremony.** Fable tends to add checks nobody asked for. The checks in core
  (TDD, one reviewer, one fix round, the gate) are the whole process; add a step
  only when the human or a brief asks for it. When a run slows, ask it: "is there
  a bottleneck, or a process you created that I didn't ask for?" and remove what
  it names.
- **Bottlenecks sit outside the model too**: build slots, a slow gate, a render
  or test queue. Find the queue before changing the prompt.

## Gauntlet loop

A gauntlet loop is ew-hill-climb for a goal a program cannot score (visual
quality, realism, "in the same league as X"). The metric is a blind judge.

1. Fix the **reference**: real examples of the target. Lock it and the judge
   prompt as ew-hill-climb locks a harness.
2. Each round, a fresh subagent that has seen none of the work gets our output
   and a reference, unlabelled, and answers: which is the real one, and what is
   the biggest gap in the other?
3. The next round fixes that one gap. Log each round (gap, verdict, kept or
   reverted) in the hill-climb log, and plot verdicts per round.
4. **Stalled** (three rounds with no kept change, or a flat plot): stop the loop
   and start a fresh one from the committed state and the log. A new context
   often moves where the old one could not. Two stalled loops in a row is a
   plateau: report it.
5. If one element sinks every verdict, split it out: judge the rest without it
   and give that element its own loop.

Done when the judge cannot tell ours from the reference across the reference
set, or on a plateau, or when the budget is spent. Interactive sessions only: the
factory's climb needs a command metric.
