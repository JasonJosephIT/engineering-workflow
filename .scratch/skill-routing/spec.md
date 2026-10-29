# Spec: Skill routing, add-ons, domain packs and ticket state (engineering-workflow v0.4.0)

Status: ready-for-agent
Design: `docs/skill-routing.md` (decisions dated 2026-10-28 in `STATUS.md`). Ships after
factory mode (v0.3.0).

## Problem Statement

The engineering workflow only knows its own `ew-` skills. Tools the developer relies
on (graphify, codebase-explainer, multi-model-review, design-genius) are wired into no
stage, so whether they get used depends on the agent remembering them. About 150
skills load into every Claude session; that is over the listing budget, so around 65
load with no description and can't be picked automatically, including core workflow
skills. Domain skills that matter to one kind of project (web design, ad production,
personal tasks) load everywhere. And there is no single view of which tickets are in
progress across sessions, projects and factory runs.

## Solution

The workflow names, for each stage, which skill to use and when, and uses an add-on
only when it is installed, reporting anything missing instead of pretending. EW gains
an `addon` command that installs those tools pinned and verified like its own skills,
and a `pack` command that links a domain pack into one project instead of loading it
everywhere. The session report says which add-ons were found and offers, once, to
build a graph in an engineering repo that has none. EW writes one small state file per
ticket in progress (from SDD and from factory mode), which the separate `ew-flightdeck`
dashboard reads.

## User Stories

1. As a developer, I want each workflow stage to name the skill it uses, so that graphify, multi-model-review, codebase-explainer and design-genius are used at the right moment without me remembering.
2. As a developer, I want a routed skill used only when it is installed, so that the workflow still works on a machine without it.
3. As a developer, I want the session report to list which routed add-ons were found and which are missing, so that I know what the agent can and can't use this session.
4. As a developer, I want a missing add-on reported, never faked, so that I can trust what the agent says it ran.
5. As a developer, I want sessions in a repo with a graph to read the graph report before broad exploration, so that agents spend fewer tokens finding their way.
6. As a developer, I want to be offered, once, a code-only graph (no LLM) in an engineering repo that has none, so that new repos get navigation cheaply.
7. As a developer, I want a "no" to that offer remembered for that repo, so that I am not asked every session.
8. As a developer, I want planning stages to run a graph query before reading code for a question, so that exploration starts from structure.
9. As a developer, I want codebase-explainer offered for an unfamiliar repo or when I ask for an explanation, so that I get a map before decisions.
10. As a developer, I want SDD context packs to start from the graph neighbours of a ticket's files, so that implementers get the right context first.
11. As a developer, I want anything broken, throwing or slow routed to diagnosing-bugs, so that bugs get a real diagnosis loop.
12. As a developer, I want multi-model-review to run at every branch review when Orca is available, replacing code-review plus ponytail-review, so that one review covers both axes with several models.
13. As a developer, I want code-review then ponytail-review at branch review when Orca is not available, with multi-model-review only when I ask, so that reviews still happen without Orca.
14. As a developer, I want any spec or ticket that changes UI routed to design-genius `design-director` before the build, so that UI work starts with a direction.
15. As a developer, I want design-genius `critique` run at branch review when UI changed, so that UI gets a design review next to the code review.
16. As a developer, I want design asks outside a ticket left to me to prompt, so that design-genius isn't forced into unrelated work.
17. As a developer, I want the graph refreshed and committed after merge when graphify is installed, so that later and cloud sessions see the current graph.
18. As a developer, I want factory workers and the factory's final review to follow the same routing, so that unattended work meets the same bar.
19. As a developer, I want `workflow.py addon install <name>` to fetch a tagged release of a known add-on, so that I install tools one way.
20. As a developer, I want each add-on pinned to a tag, a commit and the hashes of its files, so that what runs is exactly what I installed.
21. As a developer, I want add-ons verified at every session start like EW's own skills, so that tampering or drift is caught.
22. As a developer, I want a tampered or drifted add-on reported and not used, so that a changed skill never runs silently.
23. As a developer, I want `addon remove <name>` to unlink and delete one add-on and nothing else, so that removal is safe.
24. As a developer, I want `addon install <name> <ref>` to install a specific tag, so that I can pin or roll back.
25. As a developer, I want a Claude-only add-on (ew-flightdeck) skipped on Codex and Gemini with a report, so that other platforms don't break.
26. As a developer, I want add-on installs to refuse to overwrite unmanaged skill folders, so that my own skills are never clobbered.
27. As a developer, I want add-on installs to work for a user install and for a project pin, so that cloud sessions can get the same add-ons.
28. As a developer, I want `workflow.py pack add <pack>` to link a domain pack's skills into one project, so that domain skills load only where they are useful.
29. As a developer, I want `pack remove <pack>` to remove only that pack's links from the project, so that I can undo it cleanly.
30. As a developer, I want packs defined in my own user configuration, not in the workflow repo, so that no machine paths are committed.
31. As a developer, I want `pack add` to refuse when a skill name in the pack collides with an existing skill in the project, so that nothing is shadowed silently.
32. As a developer, I want `workflow.py ticket start|update|done` to write one small state file per ticket in progress, so that dashboards and later sessions can see live work.
33. As a developer, I want factory mode to write the same ticket state files as SDD, so that one dashboard shows both.
34. As a developer, I want permission checks (Guard ask or deny) inside a ticket's worktree recorded in that ticket's state file, so that the dashboard shows which tickets are waiting on a permission.
35. As a developer, I want ticket state files kept in my local workflow state folder, outside any repo, so that nothing private is committed and every project shows in one place.
36. As a developer, I want a finished ticket's state file removed (or marked done and pruned after a day), so that the dashboard shows only live work.
37. As a developer, I want the ticket state file format documented and versioned, so that ew-flightdeck can rely on it.
38. As a workflow maintainer, I want the routing table in the core workflow text for every platform, so that Claude, Codex, Gemini and Antigravity follow the same routes.
39. As a workflow maintainer, I want add-on and pack code to use the standard library only and the existing CLI-subprocess test style, so that it matches the package.
40. As a workflow maintainer, I want the add-on registry (known names and their repositories) in the package, so that `addon install graphify` needs no URL.

## Implementation Decisions

**Routing (instructions, not code)**

- The core workflow gains a stage-to-skill routing table matching the design: session
  start (graph report; one-time graph offer), planning (graph query; codebase-explainer
  for unfamiliar repos or on request), build (graph-neighbour context packs), bugs
  (diagnosing-bugs), branch review (multi-model-review with Orca, otherwise code-review
  then ponytail-review), UI work (design-genius `design-director` before build,
  `critique` at review), after merge (graph update). Every routed add-on carries "only
  when installed; report when missing". Adapters keep only platform mappings.
- The SDD skill's context-pack step and the factory worker/final-review briefs follow
  the same table.

**Add-ons (new `addon` module, wired like the reviews module)**

- `workflow.py addon install <name> [<ref>] | remove <name>`, with the same
  `--scope user|project` and `--project` handling as install.
- A small **registry** in the package maps add-on names to repository URL, skill
  folder(s) inside the repo, and supported platforms: graphify, multi-model-review,
  codebase-explainer, design-genius, ew-flightdeck (Claude only).
- **Fetch**: shallow git clone of the requested tag (default: newest `v*` tag) into a
  temp folder; copy the skill folder(s) into the runtime's add-ons area; record name,
  ref, commit, platforms and a hash per file in an add-ons lock beside the install
  receipt. Skills are then linked into each installed platform's skill folder the same
  way EW skills are, refusing unmanaged conflicts.
- **Verify**: session start re-hashes every installed add-on; a mismatch marks that
  add-on `tampered` in the report and its links are not trusted (the report says so);
  EW's own integrity check is unchanged.
- **Platforms**: an add-on not supporting a platform is not linked there; the result
  and the session report say "skipped on <platform>".
- Add-ons survive an EW reinstall/update: install preserves the add-ons area and lock.
- Add-on repos that need their own setup (graphify's CLI, ew-flightdeck's mod
  registration) print their next step; EW does not run third-party installers.

**Domain packs (new `pack` module)**

- Packs are defined in a user-level packs file in the workflow's local state folder:
  pack name → list of skill folder paths. EW ships no machine paths. (ponytail: no `pack list`;
  the packs file and the project's skill links already show it.)
- `pack add <pack>` symlinks each skill into the project's platform skill folders and
  records the pack in the project's workflow identity file; `pack remove` removes
  exactly those links. Collisions with existing skills refuse before any write.
- Moving the developer's current global skills into packs (web-design, output-engine,
  personal) and removing frontend-team is a one-off machine step, documented in the
  Further Notes, not code.

**Session report**

- Adds `addons`: each routed add-on as `installed <version>`, `missing`, `tampered`, or
  `skipped on <platform>`.
- Adds the graph offer: when the repo is an engineering repo (has source files tracked
  by git), has no graph, and the developer has not declined, the report includes
  `graph_offer: true`. `workflow.py docs --decline-graph` records the "no" in the
  project's local state; after that the offer is absent.

**Ticket state files (new `ticket` command; contract for ew-flightdeck)**

- `workflow.py ticket start <id> --title <t> [--feature <f>] [--source sdd|factory] [--worktree <path>]`,
  `ticket update <id> [--step <s>] [--agent <a>]`, `ticket done <id>`.
- One JSON file per live ticket in the user-level workflow state folder, keyed by the
  project id and ticket id. Format version 1:

  ```
  { "format": 1, "project_id", "project_path", "ticket", "title", "feature",
    "source": "sdd" | "factory", "step", "agents": [..], "worktree",
    "permission": { "decision": "ask" | "deny", "at" } | null,
    "started_at", "updated_at" }
  ```
  (Shape decided here; ew-flightdeck reads exactly this.)
- The PreToolUse hook, when it returns ask or deny inside a worktree that has a ticket
  marker, writes `permission` into that ticket's file. Guard behaviour is unchanged.
- `ticket done` deletes the file. Files not updated for 24 hours are pruned by
  `ticket start`/`update` calls.
- SDD's skill text calls `ticket start/update/done`; factory mode calls the same code
  internally at claim, step changes and merge/needs-you.

**Release**: v0.4.0.

## Testing Decisions

- Tests drive only the `workflow.py` CLI as a subprocess (`addon`, `pack`, `ticket`,
  `session`, `docs`, `hook`) with a temporary git project and a temporary HOME, and
  assert on stdout/exit codes, files and symlinks created, the add-ons lock, ticket
  state files, and the session report. No test imports internals.
- Fake add-on sources are small local git repos with tagged releases and a skill
  folder; the registry is pointed at them by an override for tests.
- Covered: install default and specific tag; pinning recorded; tampered add-on reported
  and not trusted; remove leaves everything else; Claude-only add-on skipped on other
  platforms; unmanaged conflict refused; add-ons survive EW reinstall; pack add/remove
  touches one project only and refuses collisions; session report lists found/missing
  add-ons; graph offer appears once and disappears after decline; ticket start/update/
  done lifecycle and stale pruning; PreToolUse ask inside a ticket worktree records the
  permission while the hook's own output stays the same.
- Prior art: install tests in `tests/test_workflow.py` (temp projects with spaces,
  refusing unmanaged conflicts, idempotent installs, tamper detection) and CLI tests in
  `tests/test_reviews.py`.
- The routing table (instructions) is checked by review, not unit tests.

## Out of Scope

- Building ew-flightdeck itself (separate fork repo, its own tests) beyond pinning the
  ticket state file contract it reads.
- Creating the multi-model-review repo and the design-genius repo themselves.
- Running third-party installers (graphify CLI, FlightDeck mod registration).
- Automatically moving or deleting the developer's existing global skills/plugins.
- Ticket views on a phone over Remote Control.
- Any change to factory mode beyond calling the shared ticket state code.

## Further Notes

- One-off machine steps (from the skills audit, not code): disable the duplicate
  `mattpocock-skills` plugin and `anthropic-skills:ponytail*`; remove stale personal
  copies of `ew-*` skills; move web-design, output-engine and personal skills into
  packs; remove frontend-team once design-genius is installed. This is what brings the
  skill listing back under budget.
- Settled here that the design left open: add-ons are fetched by git tag and pinned by
  tag + commit + file hashes; Claude-only add-ons are skipped on other platforms with a
  report; the release is v0.4.0.
- The ticket marker file is the one introduced by factory mode's tracer ticket; SDD
  writes the same marker when it creates a ticket worktree.
