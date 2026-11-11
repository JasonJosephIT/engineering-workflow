# Engineering workflow

One versioned process for Claude Code, Codex, Gemini CLI and Antigravity. Version **0.9.0**.
Matt Pocock planning/TDD/review + personal SDD + Ponytail, with Claude Guard,
portable Autopilot and docs-health. Optional Headroom startup support. No Runpod,
entertainment, or required TypeSafe dependency.

## Install

Requires Git, Python **3.11+**, and access to this private repository. Clone a
release, verify it, explicitly select the platform, then install:

```sh
git clone --branch v0.9.0 https://github.com/JasonJosephIT/engineering-workflow.git
cd engineering-workflow
python3 -B workflow.py verify --expected 0.9.0
python3 -B workflow.py install --scope user --platform codex --dry-run
python3 -B workflow.py install --scope user --platform codex
```

Or install the same files from npm as `ares-workflow` (Ares Workflow), with no
login and no repository access. This needs Node 18+ and Python 3.11+. Run any
`workflow.py` command through `ares-workflow`:

```sh
npx ares-workflow verify --expected 0.9.0
npx ares-workflow install --scope user --platform codex
```

An npm install has no Git checkout, so its receipt records no source commit and
`doctor --check-upstream` cannot compare the release tag against it.

Choose `claude`, `codex`, `gemini`, or `all`. This is confirmation of the actual
target, not inference from whichever CLIs happen to be installed. Repeated
installation is idempotent. Installs preserve existing instruction text and
unrelated settings; changes get dated backups under `.workflow-backups/`.
The installer refuses unmanaged file/skill conflicts. No shell downloads, API
keys, or background service installation occurs.

For this user's migration, use `--replace-overlap`: it disables the old
Guard/Headroom/autopilot/docs-health plugins, retired Superpowers/engineering/
Taskmaster, Runpod and entertainment in the selected platform configuration.
It removes old Headroom startup/shell registrations. It leaves other plugins,
MCP configurations, permission rules and credentials alone. Skill files from
older installations are not deleted; managed instructions select `ew-` skills.
Review any remaining manual/custom duplicates with the platform's plugin UI.

Add `--headroom` only where the external `headroom` CLI is already installed and
configured. Exactly one workflow startup hook calls `headroom init hook ensure`;
there is no repeated PreToolUse Headroom hook or second Headroom plugin. This
does not install the Headroom proxy/MCP service or establish that compression is
active. Native Codex tools may have their own context management; do not add
another proxy by default. TypeSafe's installed plugin supplies semantic AI APIs,
not computer control. Keep it separate unless a project actually uses it.

Add `--adhd` to load the vendored i-have-adhd ruleset (`ew-i-have-adhd`) at every
session start. The same single startup hook injects it; only Claude has session
evidence so far. Without the flag the skill
stays installed but runs only when invoked. `--replace-overlap` disables the
standalone i-have-adhd plugin so the ruleset is not loaded twice.

## Pin each project

A user install covers future local sessions. A **project install** commits the
runtime, skills and bootstrap files so cloud sessions get the same bytes:

```sh
python3 /path/to/engineering-workflow/workflow.py install \
  --scope project --project /path/to/git-project --platform all
git -C /path/to/git-project add .engineering-workflow .agents .claude .codex .gemini AGENTS.md CLAUDE.md GEMINI.md
```

Review and commit only the intended generated files if those config directories
already contain other material. Never commit credentials or global backups.
Project hook commands resolve the Git root at runtime, so cloned paths can differ.
Project pins take precedence over the user default. Where user and project hooks
both run, the global workflow handler verifies the project pin then yields; the
project handler owns the event. Unrelated native/plugin hooks are not suppressed.

## Every session

Bootstrap instructions require this even when the platform cannot run hooks:

```sh
python3 .engineering-workflow/workflow.py session --project . --platform codex
```

For a user-only installation use `~/.engineering-workflow/workflow.py` instead.
The report identifies the chosen runtime, version, source commit, integrity,
documentation health and capabilities. Failure means stop and report the mismatch.
To verify the installed revision against the upstream immutable release tag:

```sh
python3 ~/.engineering-workflow/workflow.py doctor --platform codex --check-upstream
```

Offline checks verify local checksums, not whether a newer release exists. The
release tag/commit is the trust anchor; checksums detect drift, not a malicious
replacement of the entire source plus its receipt. Obtain code through trusted
GitHub authentication and compare the expected release commit when bootstrapping.

An upgrade is explicit: inspect a new release, check out its tag in this package
repository and rerun install. No startup pull or silent upstream skill updates.
`ew-workflow-update` does those steps on request: tests, install with the recorded
flags, verify; for the user install or, with `--project`, a project's pin.
User defaults may advance while projects retain their committed older pins.

## Factory mode (opt-in, Orca or Agent Orchestrator)

After `/to-tickets` is approved, an Orca- or AO-hosted loop builds the ready tickets in
parallel into an integration branch. `workflow.py factory tick` owns the
sequencing, caps, merges and modes. The factory never merges or pushes to
main, deploys, or publishes issues. A ticket that needs you shows on its Orca
card, or (AO) arrives as a NEEDS YOU message to the project's AO orchestrator session.

With `--runner ao`, workers are `claude-code` sessions that AO spawns on each
ticket's claim branch, in worktrees AO owns. A launchd job (no agent session)
runs `factory precheck && factory tick` hourly. The factory reuses a live AO
orchestrator for the project, or spawns one, and sends it each NEEDS YOU; it only
relays. A ticket that needs you also has its AO board card renamed
"NEEDS YOU: factory <feature> NN". After a merge, the ticket's worktree and local
claim branch are removed (the work lives on the integration branch); a ticket that
needs you keeps both until it merges. Needs the `ao` CLI, the repo registered as an AO project and macOS. The
factory refuses a worker when the AO project's permission mode is
`bypass-permissions` unless installed with `--allow-bypass`.

The Orca runner needs the Orca CLI, the repo registered in Orca, an integration branch that is
not main/master, and a committed `.engineering-workflow/gates.sh` whose last
line is `GATES: PASS`.

Defaults: concurrency 3, build_slots 1, daily_ticket_cap 10, stop_if_waiting 5,
max_turns 100, max_minutes 90. The heartbeat runs hourly on `--model sonnet`.
`daily_ticket_cap` counts every ticket started that UTC day, across queued features.
Before a ticket merges, the factory merges the integration tip into the ticket branch
and runs the gate on that: the tree it gates is the tree it merges, so two tickets that
each pass alone cannot break the integration branch together. A conflict or a failed
gate parks the ticket; a requeued worker then continues from the joined branch.
A worker's `report` never waits on a running tick: when the tick holds the factory
lock (through a merge gate, say) the report is left in `reports/` and filed by the next tick.
Orca launches Claude in bypass mode by default, so the factory refuses to keep
such a worker unless installed with `--allow-bypass`. In bypass mode Guard is the
only safety net and it is not a sandbox: a worker can still edit any file it can
reach. Use --allow-bypass only for repos and machines you trust the agent with.

```sh
python3 -B workflow.py factory install --feature NAME [--runner orca|ao] [--integration-branch BRANCH] [--paused] [--allow-bypass]
python3 -B workflow.py factory status | set SETTING VALUE | pause [--now] | resume
python3 -B workflow.py factory cycle | approve TICKET | requeue TICKET | queue [FEATURE] | uninstall
```

**Climb, then the next feature.** A feature may commit `.scratch/<feature>/climb.md`
with `**Status:** ready-for-agent` (approved with the tickets), a `**Blast radius:**`
line, and the goal: metric command, target, guardrails and round budget. Once every
ticket has merged, the factory runs one climb worker (`ew-hill-climb`, through the
ew-factory climb brief) on `factory/<feature>-climb`. Its id is `climb`, and it is
gated, capped, merged, approved and requeued like a ticket. The final review runs
after the climb merges.

The factory scores the climb itself. `**Metric:**` must hold the command in backticks
and say which way is better (`lower is better`, `higher is better`, or a target that
starts with `<=` / `>=`). `**Harness:**` must list the paths that produce the score,
comma-separated, or say `none`. `install` and `queue` refuse a climb file without them.
The command runs in a fresh checkout of committed code, so it must set itself up and
print exactly one number on its last line. The factory runs it at the integration tip
before the worker starts, and again before merging: once where the climb branched off
and once at its tip. No gain, or a change to a harness path, holds the climb for you;
`factory approve climb` still merges it. `factory status` shows
`metric <baseline> -> <final>`. A climb whose metric gives no number waits for you
before any worker starts: fix it on the integration branch, then `factory requeue climb`. 

**The final review is supervised.** It is ledger entry `review` on
`factory/<feature>-review`, in a worktree of its own at the integration tip, with the
same liveness check, turn and time caps and Guard rules as a ticket worker. It merges
nothing: findings go to `final-review.md` in the factory state folder, and the branch
and worktree are dropped once it reports. `approved` means nothing needs you, and the
factory pauses or moves on. `blocked` parks it as needs-you with its reason: fix the
findings on the integration branch and `factory requeue review` to review again at
the new tip, or `factory approve review` to accept them.

`factory queue FEATURE` lines up another feature whose
tickets are approved: once the final review is in, clean or accepted by you, the
factory archives the ledger and starts building that feature on the same integration
branch, instead of pausing. Nothing queued starts on unreviewed code. Each ticket a queued feature merges pings you with a `BUILT:` line on the
integration checkout's Orca card, or through the AO relay. The review for each
queued feature goes to `final-review-<feature>.md`.

`--integration-branch` defaults to the branch checked out in the project. `set`
takes one of `concurrency`, `build_slots`, `daily_ticket_cap`, `stop_if_waiting`,
`max_turns` or `max_minutes` and a positive integer. A ticket whose changes touch
workflow control files (`.engineering-workflow/`, `.claude/`, `CLAUDE.md`,
`AGENTS.md`, the feature's `.scratch/` folder and similar) waits for `approve`.
`uninstall` stops the workers and keeps the ledger as `ledger-<feature>-<time>.json`.

`tick`, `precheck`, `gate` and `report` are run by the heartbeat and the workers;
run the person-only commands from the integration checkout, not a ticket worktree.

## Project discovery and implementation reviews

Configure project identity independently of the installed runtime. During explicit
grilling, address all eight sections of Open Thoughts' portfolio standard 1.0.0;
record evidence, open questions and reasoned non-applicability. Load the external
source contract and ADR-002; this package does not carry a replacement standard.
A missing source leaves discovery incomplete.

The discovery JSON is keyed by each canonical section key. Each entry contains
`implications`, `evidence` and `tradeoffs` strings, or a `not_applicable_reason`
string. These entries mean the section was addressed, not factually verified.
Select the source explicitly with `--standards-source`; the producer does not
fetch a remote standard, and an unavailable source remains pending.

```sh
python3 ~/.engineering-workflow/workflow.py project configure --project . \
  --public-facing unknown --audience "Project maintainers" \
  --goal "Make implementation decisions reviewable" \
  --standards-source /path/to/Open-Thoughts/standards/portfolio-enrichment.json \
  --discovery /path/to/discovery.json
python3 ~/.engineering-workflow/workflow.py project status --project .
```

Repeat `--goal` for additional goals; `--public-facing` accepts `true`, `false` or
`unknown`. `.engineering-workflow-project.json` records the project UUID,
audience/goals, public-facing status, standards source/version/hash, discovery
entries and stable implementation key to UUID mappings. Reinstallation preserves
this file. Public-facing describes project audience independently of publication
visibility; it grants no publishing permission. Review configured metadata before
committing it, especially source locations and discovery content.

At a meaningful checkpoint or handoff, use `ew-implementation-review` to present
a short human review in chat and queue it for Open Thoughts. Review only relevant
standard sections and state gaps. Existing mandatory tests and review budgets
remain; this narrative summarizes evidence and never substitutes for approval.

```sh
python3 ~/.engineering-workflow/workflow.py review upsert --project . \
  --implementation private-review-producer --file /path/to/review.json \
  --base-revision 0 --platform codex
python3 ~/.engineering-workflow/workflow.py review show --project . \
  --implementation private-review-producer
python3 ~/.engineering-workflow/workflow.py review feedback --project . \
  --implementation private-review-producer --file /path/to/feedback.json
python3 ~/.engineering-workflow/workflow.py review sync --project . \
  --bundle /path/to/private/daydream
```

A review file contains `title`, `status` (`checkpoint` or `complete`), `sections`
with `outcome`, `purpose_decisions`, `evidence_limits`, `standards_implications`
and `your_attention`, and `references` with `implementation` strings and
`sessions` entries containing `platform` and `id`. Use the current revision for
updates; zero means a new record. Read and reconcile a revision conflict.
Feedback contains `text`, `attribution` (`human` or `agent_interpretation`) and
`classification` (`feedback`, `local_clarification` or
`shared_standard_proposal`), with optional `standard_proposal`. Proposals stay
private and unadopted until human adoption through Git in the standards source.
See [the shared review contract](core/REVIEW_CONTRACT.md) for JSON examples,
historical feedback references and idempotent delivery behavior.

Canonical narratives and feedback live in the Daydreamer private bundle; the CLI
queues them in a private outbox outside the project. Project/review commands accept
`--state-dir` for an explicit private state location. Sync writes to the local
bundle selected by `--bundle`, `DAYDREAMER_BUNDLE`, or the existing home-relative
`Projects/Open Thoughts/daydream` convention. The bundle must already be a private
Git bundle; sync does not push. Existing Daydreamer capture/push handles private Git
transport externally. Cloud outboxes require explicit import into the local
private workflow. There is no public API for private writes. Existing capture is
preserved once; full Codex/Gemini transcripts are deferred. Hooks may report a
missing checkpoint; they never infer completion or initiate paid calls.

## Goals and docs-health

```sh
python3 ~/.engineering-workflow/workflow.py goal set "Finish the approved tickets" --project .
python3 ~/.engineering-workflow/workflow.py goal status --project .
python3 ~/.engineering-workflow/workflow.py goal pause --project .
python3 ~/.engineering-workflow/workflow.py goal complete --project . --evidence "test command: observed result"
python3 ~/.engineering-workflow/workflow.py docs --project .
```

Goals are project-local, explicit, and capped at 30 automatic continuations.
Stop hooks are dormant until a goal is set. Pausing/resuming is explicit. Native
permissions remain active. Add `.engineering-workflow-state/` to a consumer's
gitignore; it holds scratch goals/ledgers, not committed project tickets.
There are no Claude-specific status panes or entertainment controls.

## Compatibility status

| Feature | Claude Code | Codex local | Gemini CLI | Codex cloud orchestration |
|---|---|---|---|---|
| Shared instructions / skills | Generated | Generated | Generated | Commit project install |
| Version/integrity check | Script + startup hook | Script + startup hook | Script + startup hook | Explicit script check |
| Guard shell check | PreToolUse | PreToolUse | BeforeTool adapter | Explicit/advisory if local hooks unsupported |
| Credential warning | PostToolUse | PostToolUse | AfterTool adapter | Explicit check required |
| Goal continuation | Stop | Stop | AfterAgent | Manual/native alternative |
| Independent SDD agents | Native if available | Native if available | Capability-dependent | Capability-dependent |

Generated configuration and protocol tests are **not live platform parity**.
No consumer-project two-ticket build has yet verified these adapters end to end.
Cloud orchestration can reject local command hooks. Report that limitation rather
than claiming enforcement. Guard is an additional check, not a sandbox: supported
shell calls are covered, but interactive input and specialized tool paths may not
be. Credential detection warns after writes; it is not pre-publication DLP.

## Claude plugin (claude.ai upload or marketplace)

The repository root is also a Claude Code plugin (`.claude-plugin/plugin.json`,
`hooks/hooks.json`). Hooks run this repository's `workflow.py` from
`${CLAUDE_PLUGIN_ROOT}`; a project pin still takes precedence. Skills appear
as `engineering-workflow:<name>` instead of `ew-<name>`, and the plugin adds no
CLAUDE.md block, Headroom startup or always-on ADHD ruleset. Build the upload zip
from a release tag with only the package files:

```sh
git archive --format=zip -o engineering-workflow-$(cat VERSION).zip HEAD -- \
  .claude-plugin hooks workflow.py reviews.py factory.py VERSION README.md \
  SOURCES.md LICENSE workflow.lock.json core adapters skills vendor
```

Or add it as a marketplace in Claude Code:
`/plugin marketplace add JasonJosephIT/engineering-workflow`, then
`/plugin install engineering-workflow@engineering-workflow`.

## Develop and release

```sh
python3 -B -m unittest discover -s tests -v
python3 -B workflow.py freeze
python3 -B workflow.py verify
```

Bump VERSION, `package.json` and release references, regenerate the lock, review
changes, commit, then tag that commit. Publish that tag to npm with `npm publish`
(public; needs an npm login). `workflow.lock.json` pins package content and upstream source
revisions. Native project build commands belong in that project's instructions.
See [core/WORKFLOW.md](core/WORKFLOW.md), [SOURCES.md](SOURCES.md), and `adapters/`.
