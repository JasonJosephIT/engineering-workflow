---
name: ew-docs-health
description: Check engineering glossary, ADR, tracker and graph freshness, or refresh an existing Graphify graph when requested.
---

Run installed `workflow.py docs --project .` to report standing documentation and
graph freshness. Use GLOSSARY.md/GLOSSARY-MAP.md; old CONTEXT names need migration,
not a duplicate glossary. Read relevant ADRs and tracker configuration as needed.
Do not delete docs automatically. Specs and operational docs/agents/ are intentional.
Use `workflow.py docs --project . --refresh` only when graph refresh is requested
or authorized after implementation; it runs graphify update . if a graph exists.
Report the result and commit generated graph output with the integration change.
Graphify absence is a capability limitation, not a successful refresh.
