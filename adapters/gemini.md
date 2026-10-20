# Gemini adapter

Load user/project GEMINI.md and shared WORKFLOW.md. Workspace/user .agents/skills
is a supported alias for Gemini skills; install there once, not a second copy in
.gemini/skills. Preserve explicit invocation restrictions even where the runtime
does not enforce OpenAI sidecar metadata. Translate Skill tool references into
Gemini skill activation or direct file reads. Use available Gemini models; never
send Sonnet/Opus aliases. Resolve `<SDD_SKILL_DIR>` from the installed skill path.
If fresh parallel subagents are unavailable, state that limit and run sequential
implementation/review contexts rather than claiming full SDD parity.

Hooks map SessionStart, BeforeTool, AfterTool, AfterAgent. Guard normalizes
run_shell_command to Bash; deny/ask becomes Gemini deny, without printing command
contents. AfterAgent continuation returns deny with a correction prompt only for
an explicitly active goal, bounded to 30 retries. Native permissions remain active.

Sources checked 2026-10-20:
- https://geminicli.com/docs/cli/skills/
- https://geminicli.com/docs/hooks/reference/
