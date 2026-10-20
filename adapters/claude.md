# Claude adapter

Load the user/project CLAUDE.md bootstrap and shared WORKFLOW.md. Discover the
ew- skills under .claude/skills. Use native Skill/Agent tools where available;
fresh implementer prompts must not inherit the full controller history.
Use Sonnet for mechanical tickets and ticket review; Opus for judgment/integration.
Respect installed model availability. Resolve `<SDD_SKILL_DIR>` to the actual
directory containing ew-subagent-driven-development/SKILL.md before running helpers.

Hooks: SessionStart performs version/docs checks and optional Headroom startup;
PreToolUse owns Guard; PostToolUse scans changed tracked files without printing
matched secret text; Stop provides bounded continuation for a user-set active goal.
Do not additionally enable the original Guard/Headroom/autopilot/docs-health plugins
for the same functions. The portable docs-health and autopilot skills replace the
Claude TSX modules; their special status panes/buttons are not reproduced.
