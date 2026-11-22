# Branch Consolidation Report — 2026-11-22

- **Integration branch:** `consolidate/2026-11-22`
- **Base:** `origin/main` (`3e735359938172a88a2758dd9c847d9ea4a34eb6`)
- **Summary:** 1 branch merged, 1 branch skipped (`SKIP-SUPERSEDED`), 0 branches deleted, `main` untouched.

## Branch Decisions

| branch | decision | reason | conflicts resolved (files) | tests |
| --- | --- | --- | --- | --- |
| `origin/claude/npm-package-check-cf8fd4` (`7389e99`) | `SKIP-SUPERSEDED` | PR #7 (`028bdb6`) already merged the npm packaging work into `origin/main`. The sole remaining commit (`7389e99`: `STATUS: keep v0.5.0 tag, publish npm from 028bdb6`) only edited `STATUS.md` (+3/-1) to record a `v0.5.0` publish workaround (`git checkout 028bdb6`, keep `v0.5.0` at `4eeffbc`). `origin/main` is now at `v0.9.1` (`package.json` = `0.9.1`; tags `v0.6.0`–`v0.9.1` all contain `028bdb6`) and `STATUS.md` Next #3 already supersedes it (`npm login`, then `npm publish` from the latest tag). | None (skipped) | N/A (skipped) |
| `origin/feature/linux-systemd-heartbeat` (`5ba7541`) | `MERGE` (`1cb9a75`, `--no-ff`) | Complete, tested feature adding a Linux `systemd` user timer heartbeat backend for `factory install --runner ao` (with `EW_FACTORY_HEARTBEAT=launchd\|systemd` override, unit-file-driven uninstall, 3 new `AoRunnerTests` tests, and `README.md` / `core/WORKFLOW.md` updates). Not yet in `origin/main`, which only supported `launchd`. | `workflow.lock.json` — regenerated with `python3 -B workflow.py freeze` (136 files, 45 skills) to preserve all `origin/main` (`v0.9.1` + wool-mode/graphmap) hashes while updating hashes for `README.md`, `core/WORKFLOW.md`, and `factory.py`. `README.md`, `core/WORKFLOW.md`, `factory.py`, and `tests/test_factory.py` auto-merged cleanly. | PASS (`179/179` unit tests, `workflow.py verify` OK) |

## Additional Post-Integration Updates

- Refreshed the Graphify code map (`docs/map/MAP.md`, commit `3a4877d`) via `python3 -B workflow.py graph --project .` after merging `origin/feature/linux-systemd-heartbeat`.

## Test Results (Before vs After)

### Before (`origin/main` at `3e73535`)

- `python3 -B workflow.py verify`: **PASS** (`Verified workflow 0.9.1`)
- `unittest` suite: **176/176 PASS** (0 failures, 0 errors)
  - `tests/test_reviews.py` + `tests/test_workflow.py` + `tests.test_factory.AoRunnerTests`: 61/61 OK
  - `tests.test_factory.FactoryTests`: 115/115 OK (4 shards: 42 + 21 + 29 + 23)

### After (`consolidate/2026-11-22` after merge `1cb9a75` + graph refresh `3a4877d`)

- `python3 -B workflow.py verify`: **PASS** (`Verified workflow 0.9.1`)
- `python3 -B workflow.py session --project . --platform gemini`: **PASS** (`integrity: verified`, `graph: fresh`, `skill_count: 45`)
- `python3 -B -m py_compile` (all Python modules & tests) + `node --check bin/ares-workflow.js`: **PASS**
- `unittest` suite: **179/179 PASS** (+3 new systemd heartbeat tests; 0 failures, 0 errors)
  - `tests/test_reviews.py` + `tests/test_workflow.py`: 44/44 OK
  - `tests.test_factory.AoRunnerTests`: 20/20 OK (includes `test_ao_install_on_linux_writes_an_hourly_systemd_user_timer`, `test_ao_uninstall_disables_the_systemd_timer_even_after_a_platform_switch`, `test_ao_heartbeat_backend_rejects_an_unknown_setting`)
  - `tests.test_factory.FactoryTests`: 115/115 OK (3 shards: 39 + 38 + 38)

## Reviewer Notes

- `origin/claude/npm-package-check-cf8fd4` (`7389e99`) was skipped only because its npm packaging PR (#7) is already on `main` and its remaining `STATUS.md` note is for `v0.5.0`; if you specifically want the historical `2026-11-10` decision bullet about keeping tag `v0.5.0` at `4eeffbc` preserved in `STATUS.md`, it can be cherry-picked into `STATUS.md`'s Decisions section without restoring the obsolete `028bdb6` Next step.
- Neither remote nor local branches were deleted, and `main` was not modified or pushed.
