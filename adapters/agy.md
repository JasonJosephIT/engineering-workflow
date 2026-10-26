# Antigravity (AGY) adapter

Load user/project `GEMINI.md` or `AGENTS.md` and shared `core/WORKFLOW.md`.
Workspace/user `.agents/skills` provides AGY skill discovery. Preserve explicit
invocation restrictions in `WORKFLOW.md`. Read `SKILL.md` files directly when
activating skills. Use available native AGY subagent models (`inherit`,
`flash_lite`, `flash`, `pro`); never pass Claude aliases (`sonnet`/`opus`).
Resolve `<SDD_SKILL_DIR>` from `~/.agents/skills/ew-subagent-driven-development`
or the project `.agents/skills/ew-subagent-driven-development`.

Hooks are registered under the `engineering-workflow` named entry in
`~/.gemini/config/hooks.json` (user scope) or `.agents/hooks.json` (project
scope) for `SessionStart`, `PreToolUse`, `PostInvocation` and `Stop`.
`PreToolUse` checks `run_command` (`toolCall.args.CommandLine`) with Claude
Guard: `deny`/`ask` returns `{"decision": "deny", ...}` without printing command
contents, while allowed commands return `{"decision": "ask"}` so native AGY
permissions and the "Always Allow" cache remain active. `PostInvocation` scans
changed files for credentials and injects an `ephemeralMessage` warning via
`injectSteps`. `Stop` returns `{"decision": "continue", "reason": ...}` only for
an explicitly active goal (bounded to 30 continuations and skipped on
`USER_CANCELED` or `ERROR`), and `{"decision": ""}` otherwise.

Use `ew-implementation-review` at implementation checkpoints: show the short
human review in chat and queue it with `review upsert --platform agy` (or
`gemini`). Sync writes only to the local private Daydreamer bundle; private Git
transport stays external.
