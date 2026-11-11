# Provenance and adaptations

Snapshot audited 2026-10-20. No user settings, tokens, account metadata, machine
history, or private project content is included.

| Component | Source | Installed snapshot |
|---|---|---|
| Matt Pocock skills | https://github.com/mattpocock/skills | 1.3.1, 49dd158d1076134a641b33efb035946536778336 |
| Guard | https://github.com/hex/claude-guard | 2026.6.0, marketplace install record 028c97dcabbaa92b3da817fd512e95226cf6e700 |
| Personal SDD | User customization of https://github.com/obra/Superpowers | vendored 6.1.0 on 2026-10-14; later personal changes retained |
| Receiving review / verification / finishing | Personal copies adapted from Superpowers | exact installed bytes except discovery/path adaptations |
| Ponytail family | User's synced skills; identical Ponytail entrypoint in anthropic-skills 1.0.0 | no independent Git revision established |
| Deploy / incident support | Personal copies of engineering plugin skills | vendored 2026-10-14; individual revision unavailable |
| Autopilot / docs-health | New stdlib implementation of requested behavior | package version; no dependency on Claude TSX runtime |
| Headroom | https://github.com/headroomlabs-ai/headroom | external optional runtime; not vendored or auto-updated |
| i-have-adhd | https://github.com/ayghri/i-have-adhd | 0.4.1, marketplace install record 1ecea1993b7fce257ffbd686c070948b5e07eda6; SKILL.md only, renamed ew-i-have-adhd |
| Fable adapter (`ew-fable`) | Matt Shumer, "You're Prompting Fable 5.2 Wrong", https://www.youtube.com/watch?v=M--oC9_5HI8 | video dated 2026-11-11; one practitioner's report, paraphrased and mapped to this workflow, not measured here |
| Implementation review | Original workflow integration | v0.2.0 producer guidance; private Daydreamer bundle and outbox |
| Portfolio discovery standard | Open Thoughts `standards/portfolio-enrichment.json` and `docs/adr/ADR-002-eight-section-enrichment.md` | external versioned contract 1.0.0; source/version/hash pinned per project, not vendored |

Upstream source SHA is provenance, not an assertion that adapted files still have
the upstream checksum. workflow.lock.json records the actual distributed hashes.
The Guard install record may identify a marketplace commit rather than a commit
in the component repository. Source branches of cache snapshots are unknown.

Matt Pocock promoted skills and support resources retain their relative layout.
Only discovery names change to ew-matt-*. The core maps original references to
the installed names. Its user-only invocation policies are preserved.
Personal skills use ew-*. SDD has portable skill-directory resolution, GLOSSARY
naming, native merge-conflict handling, platform-aware models, and the newer
bounded agent budget. Its helper scratch directory is .engineering-workflow-state.
The shared core settles conflicting historical prose; it takes precedence within
this package, subordinate to user and platform instructions.

Implementation-review guidance preserves the existing test and reviewer budgets.
It consumes the external eight-section standard without redefining it: explicit
grilling addresses every section, individual reviews discuss relevant sections.
Human review, completeness and publication approval remain distinct, as required
by ADR-002. Private feedback may propose a standard change; only human adoption
in the source Git repository makes it shared guidance. No private source content
or machine-specific path is bundled here.

Guard's Python source is included with MIT attribution. The adapter translates
tool/event protocols and redacts decision output; it never prints command text or
matched credentials. It uses Guard's existing credential rules for changed files.
No claim is made that its rules cover every execution mechanism.

Superpowers' MIT license is retained in vendor/licenses/SUPERPOWERS-MIT.txt.
Matt Pocock's MIT license is vendor/mattpocock/LICENSE.
Guard's MIT license is vendor/claude-guard/LICENSE.
i-have-adhd's MIT license is vendor/i-have-adhd/LICENSE.
Ponytail declares MIT. The other personal support copies did not supply a separate
license header; this private package preserves their provenance and does not
assert a new license for third-party material. Confirm rights before public release.

Protocol sources:
- https://code.claude.com/docs/en/hooks
- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/build-skills
- https://geminicli.com/docs/hooks/reference/
- https://geminicli.com/docs/cli/skills/
