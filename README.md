# Engineering workflow

One versioned process for Claude Code, Codex and Gemini CLI. Version **0.2.0**.
Matt Pocock planning/TDD/review + personal SDD + Ponytail, with Claude Guard,
portable Autopilot and docs-health. Optional Headroom startup support. No Runpod,
entertainment, or required TypeSafe dependency.

## Install

Requires Git, Python **3.11+**, and access to this private repository. Clone a
release, verify it, explicitly select the platform, then install:

```sh
git clone --branch v0.2.0 https://github.com/JasonJosephIT/engineering-workflow.git
cd engineering-workflow
python3 -B workflow.py verify --expected 0.2.0
python3 -B workflow.py install --scope user --platform codex --dry-run
python3 -B workflow.py install --scope user --platform codex
```

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
User defaults may advance while projects retain their committed older pins.

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

## Develop and release

```sh
python3 -B -m unittest discover -s tests -v
python3 -B workflow.py freeze
python3 -B workflow.py verify
```

Bump VERSION and release references, regenerate the lock, review changes, commit,
then tag that commit. `workflow.lock.json` pins package content and upstream source
revisions. Native project build commands belong in that project's instructions.
See [core/WORKFLOW.md](core/WORKFLOW.md), [SOURCES.md](SOURCES.md), and `adapters/`.
