# 02: Tracer: one ticket from ready to merged

**What to build:** A person installs a factory for a feature with one ready ticket and, through `tick`, sees that ticket claimed on its own branch, built in its own worktree by an Orca-launched agent, reported approved, gated, and merged into the integration branch. This is the thinnest complete path through the new `factory` CLI, its on-disk state, the Orca adapter and git, and it wires the new module into the CLI and the package lock.

**Blocked by:** 01

**Status:** ready-for-agent

**Blast radius:** medium

- [ ] `workflow.py factory install --feature <slug>` refuses when `orca` is missing, the integration branch is missing or is main/master, the feature has no ticket files, or the project has no gate script (printing a starter); otherwise it writes factory state, makes sure the state dir is git-ignored, and registers an hourly heartbeat through the Orca adapter
- [ ] `factory status` prints a one-line summary and the details
- [ ] `factory tick` claims the first ready ticket by creating its `factory/<feature>-<NN>` branch from the integration tip, creates its worktree with `git worktree add`, writes the marker file, and launches `claude` there through the adapter
- [ ] `factory gate` runs the project's gate script and exits 0 only when its last line is exactly `GATES: PASS`; a missing script fails
- [ ] `factory report <ticket> approved` records the result and runs `tick`, which re-runs the gate on the ticket branch and merges it (no fast-forward) into the integration branch, removes the worktree and keeps the branch
- [ ] `--allow-bypass` is recorded in factory state; without it, a worker that Orca started with `--dangerously-skip-permissions` (seen in the first lines of its terminal) is stopped, its ticket goes to needs-you with that reason, and the factory pauses
- [ ] The factory never touches main
- [ ] Tests drive the CLI as a subprocess against a temp git repo with a fake `orca` on PATH that logs calls, following the existing reviews tests
- [ ] The new module is in the package file list and lock; the full test suite and `verify` pass
