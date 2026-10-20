---
name: ew-autopilot
description: Persist an explicitly requested engineering goal and continue approved work with a bounded retry budget. Use when the user requests autopilot or sustained execution.
---

Use the installed workflow.py path in bootstrap instructions. Create an active goal
only when requested: `workflow.py goal set "objective" --project .`.
Work through approved tickets without routine check-ins. Report blockers honestly.
`goal pause`, `goal resume`, and `goal status` control persistence. When achieved,
run fresh checks then `goal complete --evidence "command and observed result"`.
Use `goal blocked --evidence "specific missing decision/access"` when progress
requires the human. Completion is never inferred from a final response.
The stop hook permits at most 30 continuations per activation; at the limit the
goal becomes needs-attention. Resume requires explicit user direction. Without
supported hooks persistence is instruction-driven within the turn and on resume.
Never alter permissions, silently expand scope, or create a native platform goal
as well as this portable goal. Native goals are an alternative, not a second loop.
