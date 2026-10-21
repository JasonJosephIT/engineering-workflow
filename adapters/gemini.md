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

Use ew-implementation-review at implementation checkpoints: show the short human
review in chat and queue it with `review upsert --platform gemini`. Full Gemini
transcripts are deferred; keep available session references without claiming
complete capture. Sync writes only to the local private Daydreamer bundle; cloud
outboxes require explicit local import and private Git transport stays external.
No public API accepts private writes. Hook reminders never infer completion or
start paid calls. Project `public_facing` status is independent of publication
visibility. Report observed capabilities; generated configuration is not live
parity evidence.

Sources checked 2026-10-20:
- https://geminicli.com/docs/cli/skills/
- https://geminicli.com/docs/hooks/reference/
