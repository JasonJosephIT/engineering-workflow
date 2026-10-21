# Codex adapter

Load the user/project AGENTS.md bootstrap and shared WORKFLOW.md. Discover ew-
skills under .agents/skills. Use native skill invocation, or read SKILL.md directly.
Delegate with fresh contexts when the platform provides subagents; do not use
another chat as an agent without explicit authorization. Use available Codex model
IDs and suitable effort, not Sonnet/Opus aliases. Resolve `<SDD_SKILL_DIR>` from the
installed skill path. If subagents are unavailable, report that limitation and use
explicit implement/review passes; this is reduced capability, not verified parity.

Local CLI hooks use .codex/hooks.json: SessionStart, PreToolUse, PostToolUse, Stop.
Current documentation maps exec_command to Bash; the adapter also recognizes raw
exec_command payloads. Hook failures are not a complete enforcement boundary.
Cloud orchestration may not support local command hooks even with local tools.
Use explicit session checks, guard checks, and verification when hooks are absent;
report Guard as advisory rather than enforced and continuation as manual.

Use ew-implementation-review at implementation checkpoints: show the short human
review in chat and queue it with `review upsert --platform codex`. Full Codex
transcripts are deferred; preserve available session references without claiming
complete capture. Local `review sync` writes the private Daydreamer bundle; cloud
outboxes require explicit local import and existing private Git transport remains
external. There is no public API for private writes. Hook reminders cannot infer
completion or start paid calls. Project `public_facing` describes the audience
independently of publication visibility. None of these mappings establishes live
platform parity; report actual session evidence and missing capabilities.

Sources checked 2026-10-20:
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://learn.chatgpt.com/docs/build-skills
- https://learn.chatgpt.com/docs/hooks
