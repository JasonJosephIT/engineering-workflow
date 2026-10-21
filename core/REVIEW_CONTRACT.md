# Private review contract (schema 1)

This contract is shared by Claude, Codex and Gemini. It contains no standards
definitions: the project's configured external source remains authoritative.

## Producer input

`review upsert` takes this shape; every narrative section is required:

```json
{
  "title": "Observable implementation outcome",
  "status": "checkpoint",
  "sections": {
    "outcome": "What someone can do now.",
    "purpose_decisions": "Stated goal, decisions and consequences.",
    "evidence_limits": "Checks, results and what remains unverified.",
    "standards_implications": "Relevant pinned standards and unresolved implications.",
    "your_attention": "The human decision or feedback needed, or none."
  },
  "references": {
    "implementation": ["spec:identifier", "commit:revision"],
    "sessions": [{"platform": "codex", "id": "available-session-id"}]
  }
}
```

`status` is `checkpoint` or `complete`; it never expresses human approval.
References may be empty when unavailable; describe that limit in the narrative.
The CLI assigns UUIDs, timestamps, revision, agent attribution and the project pin.
Use the same implementation key across sessions. `--base-revision 0` creates the
review; later updates require the exact latest revision. Interrupted identical
writes recover their existing revision; different drafts conflict without replacing
immutable history. Never invent a session ID, check result or personal goal.

The canonical bundle layout is `reviews/<project UUID>/<implementation UUID>/`:
`review.json` holds the current record, `revisions/<integer>.json` its immutable
history, and `feedback/<UUID>.json` immutable events. The producer stages the same
layout in private user state outside the product checkout. The locator metadata
in the project carries IDs only, not these private narratives.

## Feedback

`review feedback` accepts `text`, explicit `attribution` (`human` or
`agent_interpretation`), and `classification` (`feedback`, `local_clarification`,
`shared_standard_proposal`). Optional `review_revision` targets a historical review;
the default is current. Optional UUID `id` makes retries idempotent. A changed
event with that ID is refused. Preserve human wording except necessary redaction;
enriched interpretation is separate evidence, never a replacement for the source.

A shared proposal additionally requires `standard_proposal` containing
`standard_key`, `standard_version`, `proposed_wording`, `evidence` (nonempty string
list), `rationale`, and `expected_effect`. Its key/version must belong to the
targeted review's immutable standard pin. `adoption_status` remains `proposed`.
Adoption happens only through the human-reviewed standards-source Git change.

## Delivery and privacy

Sync is idempotent local delivery to the existing private Daydreamer repository.
It does not push, call a model, publish records, or change standards. Offline or
conflicting delivery leaves the outbox intact. Sync requires the destination to
exist; existing private Git transport remains responsible for replication.
Known token/contact patterns are redacted; detection does not establish that all
personal or confidential information is safe. Review files stay private. Public
records may include only facts deliberately accepted through existing app gates;
raw review metadata and feedback never enter the public snapshot contract.
