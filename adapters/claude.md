# Claude adapter

Load the user/project CLAUDE.md bootstrap and shared WORKFLOW.md. Discover the
ew- skills under .claude/skills. Use native Skill/Agent tools where available;
fresh implementer prompts must not inherit the full controller history.
Use Sonnet for mechanical tickets and ticket review; Opus for judgment/integration.
When the session model or a delegated agent is Fable 5.2, load ew-fable before
briefing or steering it. Respect installed model availability. Resolve
`<SDD_SKILL_DIR>` to the actual directory containing
ew-subagent-driven-development/SKILL.md before running helpers.

Hooks: SessionStart performs version/docs checks, optional Headroom startup and
the optional always-on i-have-adhd ruleset;
PreToolUse owns Guard; PostToolUse scans changed tracked files without printing
matched secret text; Stop provides bounded continuation for a user-set active goal.
Do not additionally enable the original Guard/Headroom/autopilot/docs-health/i-have-adhd plugins
for the same functions. The portable docs-health and autopilot skills replace the
Claude TSX modules; their special status panes/buttons are not reproduced.

Factory workers and the final reviewer are Claude agents launched by Orca or Agent
Orchestrator. Inside ticket worktrees, the reviewer's included, a Guard ask becomes
deny and parks the ticket as needs-you ("permission needed").

At implementation checkpoints, use ew-implementation-review to show the short
human review in chat and queue it with the producer CLI using `--platform claude`.
Keep the existing capture path once; private narratives/feedback sync only to the
local Daydreamer bundle. Existing private Git transport stays external. Hook
reminders cannot establish completion, approval or a reason to start paid calls.
Project `public_facing` status is independent of publication visibility.
