# Graphify overlay: brainstorm (2026-11-13)

Goal: every project gets graph-backed docs without copying the Graphify plugin/skill or committing the heavy graph.

## Today
- Graphify skill installed globally; `graphify` CLI on PATH.
- Open Thoughts commits `graphify-out/`: 229 files, ~18 MB (graph.json 3.8 MB, graph.html 3.9 MB, cache 6.3 MB, dated snapshots 4.2 MB).
- WORKFLOW.md: read `graphify-out/GRAPH_REPORT.md` first, refresh after integration. Graph went stale 2026-10-18 because refresh is a manual step.
- Wool mode keeps Graphify mandatory.

## Idea
The workflow owns the graph, not the project. `workflow.py graph` (new subcommand):
1. Builds or updates the graph with the CLI (`graphify extract . --code-only && graphify cluster-only . --no-label` first time, `graphify update .` after). No LLM.
2. Keeps the heavy output outside the repo: `~/.graphify/projects/<repo-id>/`.
3. Writes a thin, committed overlay: `docs/map/MAP.md` (hubs → files, god nodes, entry points, built-from commit) plus `docs/map/<community>.md` stubs only for big communities.

## Options
- **A. Thin overlay (recommended).** Commit `docs/map/` only (~50 KB). Heavy graph local. Cloud agents read MAP.md; local agents can also `graphify explain/path` against the central graph.
- **B. A + inline marks.** Also inject `<!-- graph:begin --> … <!-- graph:end -->` blocks into GLOSSARY.md and ADRs: which files/communities each term or decision touches. Hand-written text untouched.
- **C. No repo files.** Everything central. Fails in cloud sessions and for other agents; not recommended.

## Refresh trigger
- SessionStart already detects `stale`. Since Graphify is mandatory: run `workflow.py graph` automatically when stale (code-only takes ~1 min), or at least tell the agent to run it before broad exploration.
- After integration: `ew-finishing-a-development-branch` runs it and commits `docs/map/`.

## Migration
- Per project: move `graphify-out/` to the central store, add it to `.gitignore`, commit `docs/map/`.
- Point WORKFLOW.md at `docs/map/MAP.md` instead of `graphify-out/GRAPH_REPORT.md`.
- `/graphify` with docs/papers still works; it just writes to the central store.

## Decisions for Jason
1. Stop committing `graph.json`/cache/html? (Recommend yes.)
2. Overlay A or B?
3. Auto-refresh at SessionStart when stale, or agent step only?

Effort: A about half a day (subcommand, renderer, tests, migration of Open Thoughts). B adds ~2 hours.
