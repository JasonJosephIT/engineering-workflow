#!/usr/bin/env python3
"""Update an installed engineering workflow to a tag or branch, keeping its install flags.

usage: update.py [ref] [--project PATH] [--dry-run]
       ref defaults to the newest v* tag; --project updates that project's pin instead of the user install
       update.py --self-test
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PLATFORMS = {"agy", "claude", "codex", "gemini"}


def install_args(state, version, project=None):
    """The install flags that reproduce the current install, for `version`."""
    scope = "project" if project else "user"
    if state.get("scope") != scope:
        raise SystemExit(f"Expected a {scope}-scope install, found {state.get('scope')}")
    platforms = set(state.get("platforms", []))
    if platforms == PLATFORMS:
        platform = "all"
    elif len(platforms) == 1:
        platform = platforms.pop()
    else:
        # install takes one platform or all; a partial set can't be reproduced in one run.
        raise SystemExit("Installed for " + ", ".join(sorted(platforms)) + ": pick 'all' or one platform by hand")
    args = ["install", "--scope", scope, "--platform", platform, "--expected", version]
    args += ["--project", str(project)] * bool(project)
    args += ["--headroom"] * bool(state.get("headroom")) + ["--adhd"] * bool(state.get("adhd"))
    # Never --replace-overlap: it switches off plugins the user may have turned back on.
    return args


def newest_tag(repo):
    out = subprocess.run(["git", "-c", "versionsort.suffix=-", "ls-remote", "--tags", "--refs", "--sort=-v:refname", repo, "v*"],
                         check=True, capture_output=True, text=True).stdout
    return out.split()[1].removeprefix("refs/tags/")


def run(cmd, cwd=None):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def main(argv):
    dry = "--dry-run" in argv
    project = Path(argv[argv.index("--project") + 1]).resolve() if "--project" in argv else None
    refs = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--project")]
    runtime = (project or Path.home()) / ".engineering-workflow"
    state = json.loads((runtime / "install.json").read_text())
    # Local edits in the runtime would be overwritten silently; they belong in the repo first.
    run(["python3", str(runtime / "workflow.py"), "verify"])
    ref = refs[0] if refs else newest_tag(state["repository"])
    print(f"Installed {state['version']} ({state['source_commit'][:7]}); updating to {ref}")
    src = Path(tempfile.mkdtemp(prefix="ew-update-")) / "src"
    run(["git", "clone", "-q", "--branch", ref, state["repository"], str(src)])
    version = (src / "VERSION").read_text().strip()
    run(["python3", "-B", "-m", "unittest", "discover", "-s", "tests"], cwd=src)
    run(["python3", "workflow.py", *install_args(state, version, project), *(["--dry-run"] if dry else [])], cwd=src)
    if not dry:
        run(["python3", str(runtime / "workflow.py"), "verify", "--expected", version])


def self_test():
    full = {"scope": "user", "platforms": sorted(PLATFORMS), "headroom": True, "adhd": True}
    assert install_args(full, "0.2.1") == ["install", "--scope", "user", "--platform", "all", "--expected", "0.2.1", "--headroom", "--adhd"]
    assert install_args({**full, "platforms": ["claude"], "adhd": False}, "1.0")[4] == "claude"
    assert "--adhd" not in install_args({**full, "adhd": False}, "1.0")
    pinned = install_args({**full, "scope": "project", "headroom": False}, "1.0", Path("/repo"))
    assert pinned[:3] == ["install", "--scope", "project"] and pinned[-3:] == ["--project", "/repo", "--adhd"]
    for bad, project in (({**full, "scope": "project"}, None), (full, Path("/repo")), ({**full, "platforms": ["claude", "codex"]}, None)):
        try:
            install_args(bad, "1.0", project)
        except SystemExit:
            continue
        raise AssertionError(bad)
    print("self-test ok")


if __name__ == "__main__":
    self_test() if "--self-test" in sys.argv else main(sys.argv[1:])
