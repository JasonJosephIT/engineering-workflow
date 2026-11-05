---
name: ew-hill-climb
description: Turn an engineering goal into a scored check, then loop change → measure → keep or revert until the score hits a target. Use when the user says "hill climb", "keep going until it passes", "make this N× faster / smaller / cheaper", "cut the tokens / context / payload", "get the eval to 100%", or wants an agent to optimize against a number; the factory's climb brief also runs it. For design quality, which has no programmatic score, use design-critique council mode instead.
argument-hint: "<goal> [target]"
---

# Hill Climb

**Unattended (factory climb brief).** The approved climb file already holds the
score, target, guardrails and budget, so step 1 is reading it, not asking. Nobody
answers questions: where a step says "tell the user" or "stop", report blocked with
the reason instead. The factory's gate command is always a guardrail.

An agent will push up any score it can measure. Your job is to make that score honest, lock it before climbing, and stop when the top is reached, progress stalls, or the budget runs out.

## 1. Define the score

Write down, and show the user before running anything:

- **Primary metric**: one number produced by one command, such as cases passed out of N, p50 ms, bytes sent to the client, or tokens in the tool descriptions.
- **Direction and target**: for example "≥ 85/85" or "≤ ⅓ of baseline".
- **Guardrails**: checks that must not regress: the test suite, a no-regression comparison against real data, and type checks.
- **Budget**: maximum rounds (default 15) and any time or spend limit.

If no score exists yet, build one first (see step 2). If the goal can't be scored by a program, say so and offer design-critique council mode or a human-judged checklist instead.

## 2. Build the eval from real failures

When the goal is about behavior, such as an agent misusing tools or wrong outputs:

1. Collect real cases where things went wrong, from logs, thread history, bug reports, or the user's examples.
2. Group them by failure type, and add a few passing cases so a fix can't break what already works.
3. Turn each one into a case with an input and an automated pass/fail check.
4. Keep about 20% of the cases as a **held-out set** that is never shown during the climb.

Put the harness in its own commit. Run it on the unchanged code and record the **baseline**. If the metric is noisy (timing, model outputs), run it 3 to 5 times, take the median, and record the spread. Only an improvement larger than the spread counts.

## 3. Lock the harness

Once the baseline is recorded, the eval cases, scoring code and guardrails are frozen. Record their checksum or commit hash in `hill-climb/log.md`. During the climb, never edit them, weaken assertions, skip cases, or special-case inputs from the eval. If the harness itself is wrong, stop, tell the user, fix it in its own commit, and record a new baseline.

## 4. Climb

Work on a branch or worktree. Each round:

1. Form one hypothesis: "removing X from the descriptions saves Y tokens without losing cases".
2. Make the smallest change that tests it.
3. Run the metric and the guardrails.
4. If the score improved beyond noise and every guardrail passes, **keep** it and commit with the score in the message. Otherwise **revert**.
5. Append a row to `hill-climb/log.md`:

| Round | Hypothesis | Score | Guardrails | Kept |
|-------|------------|-------|------------|------|

Run independent hypotheses in parallel worktrees when the host supports subagents, and merge only the winners.

**Two-phase climbs.** When there is a correctness metric and an efficiency metric, climb them in order. First reach a perfect or target correctness score and commit it as the floor. Then shrink size, tokens or time while correctness stays at the floor every round.

## 5. Stop

Stop on the first of:

- **Target reached** on the primary metric, with every guardrail green.
- **Plateau**: three rounds in a row with no kept change.
- **Budget spent.**

Then run the held-out set once. If it scores clearly below the training cases, the climb overfit. Report that and don't call the climb done.

## 6. Report

```markdown
## Hill Climb: <goal>

Result: <target reached in round N | plateau | budget> — <baseline> → <final> (target <target>)
Held-out: <score> (training <score>)
Guardrails: <all green, or which failed and when>

| Round | Change | Score | Kept |
|-------|--------|-------|------|

What moved the number: <the 2-3 changes that mattered>
Harness: <path and commit>. Commit it so future changes can be checked against the same score.
```

Treat the result as evidence, not a guarantee. Before merging, review the final diff for changes that game the metric rather than improve the thing it measures.
