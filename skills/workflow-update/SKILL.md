---
name: ew-workflow-update
description: Update an installed engineering workflow to its newest release, a tag, or a branch, keeping the installed platforms and the Headroom/ADHD flags. Works on the user install or a project's pin. Use when the user says "update the workflow", "upgrade engineering workflow", "install the latest workflow release", "re-pin this project", "install from branch X", or /ew-workflow-update.
argument-hint: "[tag-or-branch] [--project PATH] [--dry-run]"
---

Run `update.py` from this skill's folder (resolve the folder this SKILL.md is in):

```bash
python3 <this skill's folder>/update.py [tag-or-branch] [--project PATH] [--dry-run]
```

No ref installs the newest `v*` tag; a branch name (a PR's head) installs that branch.
`--project PATH` updates that project's committed pin instead of the user install.
`--dry-run` runs everything except the write.

The script, in order:
1. Verifies the current runtime. A failure means someone edited the runtime by hand:
   stop and show the user, since the update would erase those edits. Changes belong
   in this package's repository first.
2. Clones the ref into a temp folder and runs the package tests.
3. Installs with the flags `install.json` records: platforms (all, or one), `--headroom`,
   `--adhd`. It never passes `--replace-overlap`, which would switch off plugins the user
   may have turned back on.
4. Verifies the new version.

An upgrade stays explicit: run this only when the user asks. If the platform refuses to
run code from the clone, don't work around it; give the user the command to run.

Afterwards report the version change and the backup folder the installer printed (the
rollback). A project update changes files in that repository: show the diff and let the
user commit it. Headroom and ADHD injection show only in a new session's start report.
Never edit `workflow.lock.json` or `install.json` in a runtime; when they disagree the
hooks fail closed.
