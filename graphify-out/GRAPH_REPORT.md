# Graph Report - wt-engineering-workflow  (2026-11-22)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1056 nodes · 2482 edges · 62 communities (54 shown, 8 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 35 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `743fc1c6`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58

## God Nodes (most connected - your core abstractions)
1. `FactoryTests` - 149 edges
2. `files` - 137 edges
3. `skills` - 46 edges
4. `WorkflowTests` - 38 edges
5. `AoRunnerTests` - 26 edges
6. `git()` - 24 edges
7. `ReviewFlowTests` - 20 edges
8. `save()` - 20 edges
9. `feedback()` - 20 edges
10. `upsert()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `credential_check()` --calls--> `scan_file()`  [INFERRED]
  workflow.py → vendor/claude-guard/guard/packs/credentials.py
- `add_worktree()` --calls--> `git()`  [EXTRACTED]
  factory.py → workflow.py
- `make_branch()` --calls--> `git()`  [EXTRACTED]
  factory.py → workflow.py
- `relaunch()` --calls--> `git()`  [EXTRACTED]
  factory.py → workflow.py
- `start_extra()` --calls--> `git()`  [EXTRACTED]
  factory.py → workflow.py

## Import Cycles
- None detected.

## Communities (62 total, 8 thin omitted)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (137): files, adapters/agy.md, adapters/claude.md, adapters/codex.md, adapters/gemini.md, core/REVIEW_CONTRACT.md, core/WORKFLOW.md, factory.py (+129 more)

### Community 2 - "Community 2"
Cohesion: 0.04
Nodes (46): skills, ew-autopilot, ew-deploy-checklist, ew-docs-health, ew-fable, ew-factory, ew-finishing-a-development-branch, ew-hill-climb (+38 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (29): advance(), approve(), close_hint(), enforce_caps(), gate(), go(), in_ticket_worktree(), load() (+21 more)

### Community 5 - "Community 5"
Cohesion: 0.21
Nodes (33): bound_record(), bundle_root(), clean(), configure(), discovery_status(), encode(), feedback(), get_standard() (+25 more)

### Community 6 - "Community 6"
Cohesion: 0.14
Nodes (32): spawn_tick(), context_output(), credential_check(), credential_paths(), default_hook_output(), digest(), disable_codex_plugins(), docs() (+24 more)

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (15): main(), segments(), main(), normalize(), scan_file(), should_skip(), allowlist_rules(), load_all() (+7 more)

### Community 8 - "Community 8"
Cohesion: 0.10
Nodes (23): ao_executable(), ao_project(), check_climb(), climb_spec(), install(), launch_worker(), launchctl(), orca() (+15 more)

### Community 9 - "Community 9"
Cohesion: 0.12
Nodes (6): refresh_in_background(), install_args(), main(), newest_tag(), run(), self_test()

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (16): add_worktree(), branch_name(), claim(), free_room(), held(), launch(), make_branch(), move() (+8 more)

### Community 11 - "Community 11"
Cohesion: 0.11
Nodes (15): climb_baseline(), climb_hold(), control_files(), current_climb(), gate_ticket(), integration_checkout(), land(), measure() (+7 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (13): _base(), build(), _build(), _git(), handoff(), identity(), _link(), render() (+5 more)

### Community 14 - "Community 14"
Cohesion: 0.14
Nodes (16): ao(), ao_alive(), ao_attach(), ao_bypass(), ao_send(), ao_spawn(), branch_worktree(), bypass_problem() (+8 more)

### Community 16 - "Community 16"
Cohesion: 0.22
Nodes (18): ask(), ask_secret(), banner(), _clear(), _existing(), finish(), note(), open_url() (+10 more)

### Community 17 - "Community 17"
Cohesion: 0.12
Nodes (10): ao_ticket_branch(), cap_verdict(), count_turn(), counters(), file_report(), flag_permission(), lock_within(), read_regular() (+2 more)

### Community 18 - "Community 18"
Cohesion: 0.14
Nodes (10): approved_climb(), built(), climb_due(), climb_ticket(), final_review(), header_fields(), radius_of(), review_due() (+2 more)

### Community 19 - "Community 19"
Cohesion: 0.15
Nodes (8): check_execution_bridges(), _extract_argument(), find_comment_start(), find_quoted_regions(), get_effective_command(), is_safe_wrapper_arg(), _preceding_context(), _preceding_word()

### Community 20 - "Community 20"
Cohesion: 0.12
Nodes (15): bin, ares-workflow, description, engines, node, files, license, name (+7 more)

### Community 21 - "Community 21"
Cohesion: 0.28
Nodes (4): register_allowlist(), register_tier1(), register_tier2(), tier2_rules()

### Community 22 - "Community 22"
Cohesion: 0.15
Nodes (12): jobs, test, name, on, permissions, contents, run, uses (+4 more)

### Community 23 - "Community 23"
Cohesion: 0.18
Nodes (11): dependencies, headroom, mattpocock-skills, personal-sdd, mode, adapted, repository, revision (+3 more)

### Community 24 - "Community 24"
Cohesion: 0.29
Nodes (4): path, result, script, { spawnSync }

### Community 25 - "Community 25"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 26 - "Community 26"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 27 - "Community 27"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 28 - "Community 28"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 29 - "Community 29"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 30 - "Community 30"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 31 - "Community 31"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 32 - "Community 32"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 33 - "Community 33"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 34 - "Community 34"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 35 - "Community 35"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 36 - "Community 36"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 37 - "Community 37"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 38 - "Community 38"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 39 - "Community 39"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 40 - "Community 40"
Cohesion: 0.33
Nodes (5): interface, display_name, short_description, policy, allow_implicit_invocation

### Community 41 - "Community 41"
Cohesion: 0.33
Nodes (5): name, release, repository, schema, version

### Community 42 - "Community 42"
Cohesion: 0.33
Nodes (6): i-have-adhd, adapted, install_record_sha, mode, repository, version

### Community 43 - "Community 43"
Cohesion: 0.40
Nodes (3): in_flight(), update_mode(), wave_settled()

### Community 44 - "Community 44"
Cohesion: 0.50
Nodes (4): ready_tickets(), fresh(), merged(), status_line()

### Community 46 - "Community 46"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 47 - "Community 47"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 48 - "Community 48"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 49 - "Community 49"
Cohesion: 0.83
Nodes (3): capture(), hitl-loop.template.sh script, step()

### Community 50 - "Community 50"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 51 - "Community 51"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 52 - "Community 52"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 53 - "Community 53"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 54 - "Community 54"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 55 - "Community 55"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 56 - "Community 56"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 57 - "Community 57"
Cohesion: 0.50
Nodes (3): interface, display_name, short_description

### Community 58 - "Community 58"
Cohesion: 0.50
Nodes (4): install_record_sha, repository, version, claude-guard

## Knowledge Gaps
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `FactoryTests` connect `Community 0` to `Community 9`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.06334959916347159 - nodes in this community are weakly interconnected._
- **Why does `WorkflowTests` connect `Community 3` to `Community 9`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.014598540145985401 - nodes in this community are weakly interconnected._
- **Why does `AoRunnerTests` connect `Community 12` to `Community 9`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.043478260869565216 - nodes in this community are weakly interconnected._
- **Should `Community 3` be split into smaller, more focused modules?**
  _Cohesion score 0.0859465737514518 - nodes in this community are weakly interconnected._