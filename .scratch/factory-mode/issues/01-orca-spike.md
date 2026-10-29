# 01: Orca spike: confirm unattended Claude on this host

**What to build:** A person runs a short manual check on this machine and records exactly which Orca commands and behaviours the factory can rely on, so the Orca adapter is built on facts rather than guesses. Spec: `.scratch/factory-mode/spec.md` (Further Notes).

**Blocked by:** None (can start immediately)

**Status:** resolved

**Blast radius:** low

- [x] An Orca automation with a precheck runs Claude unattended in the current permission mode, and a failing precheck records a skipped run with no agent started
- [x] The heartbeat accepts a cheap-model extra agent argument (or the alternative that works is recorded)
- [x] An agent launched with `orca agent launch` into an existing `git worktree` checkout (not created by Orca) starts with a given prompt
- [x] The engineering-workflow hooks (SessionStart, PreToolUse, PostToolUse) fire inside that Orca-launched agent
- [x] A worker can run a `workflow.py` command as its last step without a permission prompt blocking it
- [x] The commands for setting a card's status, comment and unread dot on that worktree, for checking whether its agent is alive, and for stopping it are confirmed
- [x] Findings, with the exact command shapes and JSON fields, are appended under `## Comments` in this file, and any spec change they force is noted in STATUS.md

## Comments

### 2026-10-29: spike results (Orca 1.4.238, Claude Code 2.1.312, run by the controller)

Throwaway repo registered in Orca, one automation, one agent. Automation, Orca-made
run worktrees, git worktree and the empty `~/orca/workspaces/orca-spike` folder were
removed afterwards. The repo entry `orca-spike` stays registered: Orca has no CLI to
remove repos, so remove it in Orca's UI.

Confirmed:
- `orca automations create ... --repo id:<id> --precheck <cmd> --extra-agent-args="--model sonnet" --disabled`
  works. A **scheduled** run with a failing precheck is recorded as
  `status: skipped_precheck`, `precheckResult.exitCode: 1`, and starts no agent.
- A **manual** `orca automations run <id>` ignores the precheck (`precheckResult: null`)
  and always dispatches. So `factory cycle` must call `tick` directly, as the spec says.
- `--repo` automations create a new worktree per run under `~/orca/workspaces/<repo>/`.
  The heartbeat must use `--workspace <integration worktree>` instead.
- `--extra-agent-args="--model haiku"` is accepted but the run fails with
  `API Error: 400 system.4.type: Input should be 'text'`. `--model sonnet` works and
  replied unattended. Use sonnet for the heartbeat.
- `orca agent launch --agent claude --worktree path:<abs> --model sonnet --surface terminal --prompt <brief> --json`
  starts an agent in a worktree made by plain `git worktree add` (Orca lists it when
  the repo's external worktree visibility is `show`, which `repo add` set). Result:
  `launch.outcome.kind: terminal`, `launch.outcome.handle: term_...`,
  `prompt.outcome: handed-to-terminal`.
- Workflow hooks fire in Orca-launched agents: the agent quoted the SessionStart
  report (version 0.2.2); PreToolUse (Guard) fired on a risky command. PostToolUse was
  not observed directly; it is registered in the same settings, so assumed.
- The worker ran `python3 ~/.engineering-workflow/workflow.py session ...` as its last
  step with no prompt (exit 0).
- Card: `orca worktree set --worktree path:<abs> --workspace-status in-review --comment "NEEDS YOU: ..." --unread --json`
  returns the new `workspaceStatus`, `comment`, `isUnread`.
- Liveness: `orca terminal show --terminal <handle> --json` → `result.terminal.connected`
  (bool) and `exitCause` (e.g. `{"kind": "operator_close"}`) once stopped.
- Stop: `orca terminal close --terminal <handle> --json` stopped the agent
  (`exitCause: operator_close`) but returned `ok: false, runtime_error tab_not_found`.
  The adapter must confirm with `terminal show`, not trust close's result.

Spec impact (needs a human decision):
- **Orca launches Claude with `--dangerously-skip-permissions`** by default, for both
  automation runs and `agent launch` (status bar shows "bypass"). This contradicts
  the spec guard rail "never uses bypass permissions; install refuses if unattended
  runs would need bypass mode".
- **Guard still enforces in bypass mode**: its PreToolUse `ask` showed a confirmation
  prompt ("Claude Guard requires local review of this command"). Unattended, that
  prompt waits forever, so the worker would stall until the 90-minute cap.
