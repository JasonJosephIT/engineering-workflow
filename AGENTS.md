# Workflow package development

This repository packages a portable workflow; it is not a product project.
Read core/WORKFLOW.md for consumer behavior. Keep platform-specific assumptions
in adapters. Preserve upstream licenses and document adaptations in SOURCES.md.
Use Python's standard library. Run `python3 -B -m unittest discover -s tests -v`
and `python3 -B workflow.py verify` before publishing. After changing package files,
run `python3 -B workflow.py freeze` and commit workflow.lock.json with the change.
Do not claim platform parity without actual session evidence. No secrets or
machine-specific home paths belong in this repository. Independent review of
installer, version verification and hook behavior may use a fresh subagent.
