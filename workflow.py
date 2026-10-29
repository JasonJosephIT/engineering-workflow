#!/usr/bin/env python3
"""Portable engineering workflow installer and session checks. Python 3.11+."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPOSITORY = "https://github.com/JasonJosephIT/engineering-workflow.git"
START = "<!-- engineering-workflow:begin -->"
END = "<!-- engineering-workflow:end -->"
PLATFORMS = ("agy", "claude", "codex", "gemini")


def read_json(path):
    return json.loads(Path(path).read_text())


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".ew-write-", dir=path.parent)
    temp = Path(temp)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        if path.exists():
            shutil.copymode(path, temp)
        else:
            temp.chmod(0o644)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def git(*args, cwd=None):
    result = subprocess.run(["git", *args], cwd=cwd, text=True,
                            capture_output=True, timeout=20)
    return result.stdout.strip() if result.returncode == 0 else None


def package_paths(root=ROOT):
    for name in ("workflow.py", "reviews.py", "factory.py", "VERSION", "README.md", "SOURCES.md", "LICENSE"):
        yield root / name
    for name in ("core", "adapters", "skills", "vendor"):
        for p in sorted((root / name).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                if p.is_symlink():
                    raise ValueError("Package contains a symlink")
                yield p


def skill_map(root=ROOT):
    result = {}
    for folder in (root / "skills", root / "vendor/mattpocock/skills", root / "vendor/i-have-adhd/skills"):
        for p in sorted(folder.rglob("SKILL.md")):
            match = re.search(r"^name: ([a-z0-9-]+)$", p.read_text(), re.M)
            if not match or match[1] in result:
                raise ValueError("Invalid or duplicate skill name: " + str(p))
            result[match[1]] = str(p.parent.relative_to(root))
    return result


def freeze():
    lock = {
        "schema": 1, "name": "engineering-workflow",
        "version": (ROOT / "VERSION").read_text().strip(),
        "repository": REPOSITORY, "release": "v" + (ROOT / "VERSION").read_text().strip(),
        "skills": skill_map(),
        "files": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in package_paths()},
        "dependencies": {
            "mattpocock-skills": {"version": "1.3.1", "repository": "https://github.com/mattpocock/skills",
                "revision": "49dd158d1076134a641b33efb035946536778336", "adapted": "discovery name only"},
            "claude-guard": {"version": "2026.6.0", "repository": "https://github.com/hex/claude-guard",
                "install_record_sha": "028c97dcabbaa92b3da817fd512e95226cf6e700"},
            "personal-sdd": {"base": "superpowers 6.1.0", "adapted": "portable paths, models and bounded reviews"},
            "headroom": {"mode": "optional external CLI, one SessionStart hook only"},
            "i-have-adhd": {"version": "0.4.1", "repository": "https://github.com/ayghri/i-have-adhd",
                "install_record_sha": "1ecea1993b7fce257ffbd686c070948b5e07eda6", "adapted": "discovery name only",
                "mode": "optional always-on ruleset, one SessionStart hook only"},
        },
    }
    (ROOT / "workflow.lock.json").write_bytes(encoded(lock))
    print("Locked", len(lock["files"]), "files and", len(lock["skills"]), "skills")


def verify(root=ROOT, expected=None):
    root = Path(root).resolve()
    lock = read_json(root / "workflow.lock.json")
    receipt = root / "install.json"
    if receipt.exists() and digest((root / "workflow.lock.json").read_bytes()) != read_json(receipt)["lock_sha256"]:
        raise ValueError("Installed lock differs from installation receipt")
    if lock.get("schema") != 1:
        raise ValueError("Unsupported workflow lock schema")
    if expected and lock["version"] != expected:
        raise ValueError("Expected workflow " + expected + "; installed " + lock["version"])
    problems = []
    for name, checksum in lock["files"].items():
        p = root / name
        if Path(name).is_absolute() or ".." in Path(name).parts or p.is_symlink() or not p.resolve().is_relative_to(root):
            raise ValueError("Unsafe package path")
        if not p.is_file() or digest(p.read_bytes()) != checksum:
            problems.append(name)
    if problems:
        raise ValueError("Workflow integrity mismatch: " + ", ".join(problems[:12]))
    if (root / "VERSION").read_text().strip() != lock["version"]:
        raise ValueError("Version file does not match lock")
    return lock


def find_project(path):
    path = Path(path).resolve()
    top = git("rev-parse", "--show-toplevel", cwd=path)
    return Path(top) if top else path


def runtime_for(project):
    project = find_project(project)
    candidate = project / ".engineering-workflow"
    return candidate if (candidate / "install.json").is_file() else ROOT


def managed(text, block):
    if text.count(START) != text.count(END) or text.count(START) > 1:
        raise ValueError("Malformed managed instruction block")
    if START in text:
        a, rest = text.split(START)
        _, b = rest.split(END)
        return a + block + b
    return text.rstrip() + ("\n\n" if text.strip() else "") + block + "\n"


def hook_config(platform, runtime, scope, headroom):
    if scope == "project":
        command = 'python3 "$(git rev-parse --show-toplevel)/.engineering-workflow/workflow.py"'
    else:
        command = "python3 " + shlex.quote(str(runtime / "workflow.py"))
    command += " hook --platform " + platform
    if platform == "agy":
        return {
            "SessionStart": [{"type": "command", "command": command + " --event SessionStart", "timeout": 20}],
            "PreToolUse": [{"matcher": "run_command", "hooks": [
                {"type": "command", "command": command + " --event PreToolUse", "timeout": 20}]}],
            "PostInvocation": [{"type": "command", "command": command + " --event PostInvocation", "timeout": 20}],
            "Stop": [{"type": "command", "command": command + " --event Stop", "timeout": 20}],
        }
    events = ("SessionStart", "BeforeTool", "AfterTool", "AfterAgent") if platform == "gemini" else (
        "SessionStart", "PreToolUse", "PostToolUse", "Stop")
    hooks = {}
    for event in events:
        item = {"type": "command", "command": command, "timeout": 20_000 if platform == "gemini" else 20}
        entry = {"hooks": [item]}
        if platform == "gemini":
            entry["matcher"] = ".*"
        elif event == "PostToolUse":
            entry["matcher"] = "Bash|exec_command|Write|Edit|NotebookEdit|apply_patch"
        hooks[event] = [entry]
    return hooks


def merge_agy_hooks(data, additions):
    data = json.loads(json.dumps(data))
    data["engineering-workflow"] = additions
    return data


def merge_hooks(data, additions):
    data = json.loads(json.dumps(data))
    hooks = data.setdefault("hooks", {})
    for event, entries in list(hooks.items()):
        # Replace only our own command registrations, preserving all unrelated hooks.
        kept = []
        for entry in entries:
            entry["hooks"] = [h for h in entry.get("hooks", []) if not (
                "workflow.py" in h.get("command", "") and " hook --platform " in h.get("command", ""))]
            if entry["hooks"]:
                kept.append(entry)
        hooks[event] = kept
    for event, entries in additions.items():
        hooks.setdefault(event, []).extend(entries)
    return data


OVERLAP = {"claude-guard", "headroom", "autopilot", "docs-health", "i-have-adhd"}
ADHD_SKILL = "vendor/i-have-adhd/skills/i-have-adhd/SKILL.md"
RETIRED = {"superpowers", "engineering", "claude-taskmaster", "entertainment", "runpod"}


def prune_overlap(config):
    config = json.loads(json.dumps(config))
    for name in config.get("enabledPlugins", {}):
        if name.split("@")[0] in OVERLAP | RETIRED:
            config["enabledPlugins"][name] = False
    for event, entries in config.get("hooks", {}).items():
        kept = []
        for entry in entries:
            entry["hooks"] = [h for h in entry.get("hooks", []) if not (
                "headroom init hook ensure" in h.get("command", "") or
                ("claude-guard" in h.get("command", "") and "hooks/scripts" in h.get("command", "")))]
            if entry["hooks"]: kept.append(entry)
        config["hooks"][event] = kept
    return config


def disable_codex_plugins(text):
    import tomllib
    tomllib.loads(text)
    # Edit only exact plugin tables; leave secrets, MCP and other configuration intact.
    section = None
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        match = re.match(r'^\[plugins\.["\']([^"\']+)["\']\]\s*$', line.strip())
        if line.lstrip().startswith("["):
            section = match[1].split("@")[0] if match else None
        if section in OVERLAP | RETIRED and re.match(r"^\s*enabled\s*=", line):
            lines[i] = re.sub(r"(enabled\s*=\s*)true\b", r"\1false", line)
    result = "".join(lines)
    parsed = tomllib.loads(result)
    if any(v.get("enabled") for k, v in parsed.get("plugins", {}).items()
           if k.split("@")[0] in OVERLAP | RETIRED):
        raise ValueError("Codex plugin configuration uses an unsupported table format; review overlap manually")
    return result


def install(args):
    lock = verify(expected=args.expected)
    base = Path(args.home).expanduser().resolve() if args.scope == "user" else find_project(args.project)
    if args.scope == "project" and not git("rev-parse", "--show-toplevel", cwd=base):
        raise ValueError("Initialize the target Git repository before project installation")
    platforms = list(PLATFORMS) if args.platform == "all" else [args.platform]
    runtime = base / ".engineering-workflow"
    if runtime == ROOT:
        raise ValueError("Install into a consumer project/home, not the package itself")
    if runtime.exists():
        if not (runtime / "install.json").is_file():
            raise ValueError("Refusing to overwrite an unmanaged runtime")
        previous = read_json(runtime / "install.json")
        verify(runtime)
        platforms = sorted(set(platforms + previous["platforms"]))
    changes = {}
    links = {}
    runtime_text = str(runtime) if args.scope == "user" else ".engineering-workflow"
    for platform in platforms:
        instruction = {"agy": ".gemini/GEMINI.md" if args.scope == "user" else "GEMINI.md",
                       "claude": ".claude/CLAUDE.md" if args.scope == "user" else "CLAUDE.md",
                       "codex": ".codex/AGENTS.md" if args.scope == "user" else "AGENTS.md",
                       "gemini": ".gemini/GEMINI.md" if args.scope == "user" else "GEMINI.md"}[platform]
        block = (START + "\nThis managed engineering workflow supersedes earlier engineering-workflow rules.\n"
                 "At the start of every session, run:\n\n```sh\npython3 " + shlex.quote(runtime_text + "/workflow.py")
                 + " session --project . --platform " + platform + "\n```\n\n"
                 "Read `" + runtime_text + "/core/WORKFLOW.md` and `" + runtime_text + "/adapters/" + platform + ".md`.\n"
                 "If the session report selects a project-pinned runtime, read its core and adapter instead.\n"
                 "Resolve upstream skill references through that runtime's workflow.lock.json ew- names.\n"
                 "Report failed checks and missing hook/subagent capabilities; never silently upgrade.\n" + END)
        target = base / instruction
        if target.is_symlink():
            raise ValueError("Refusing to rewrite symlinked instructions: " + str(target))
        existing_text = changes[target].decode() if target in changes else (target.read_text() if target.exists() else "")
        changes[target] = managed(existing_text, block).encode()
        config_path = base / {"agy": ".gemini/config/hooks.json" if args.scope == "user" else ".agents/hooks.json",
                              "claude": ".claude/settings.json", "codex": ".codex/hooks.json",
                              "gemini": ".gemini/settings.json"}[platform]
        if config_path.is_symlink():
            raise ValueError("Refusing symlinked hook config")
        config = read_json(config_path) if config_path.exists() else {}
        if args.replace_overlap and platform != "agy":
            config = prune_overlap(config)
        additions = hook_config(platform, runtime, args.scope, args.headroom)
        changes[config_path] = encoded(merge_agy_hooks(config, additions) if platform == "agy" else merge_hooks(config, additions))
        skill_dir = base / (".claude/skills" if platform == "claude" else ".agents/skills")
        for name, path in lock["skills"].items():
            dest = skill_dir / name
            relative = os.path.relpath(runtime / path, dest.parent)
            if dest.is_symlink() and os.readlink(dest) == relative:
                continue
            if dest.exists() or dest.is_symlink():
                raise ValueError("Refusing unmanaged skill conflict: " + str(dest))
            links[dest] = relative
    if args.replace_overlap and "codex" in platforms:
        codex_config = base / ".codex/config.toml"
        if codex_config.exists():
            changes[codex_config] = disable_codex_plugins(codex_config.read_text()).encode()
    for p in changes:
        if not p.resolve().is_relative_to(base):
            raise ValueError("Configuration path escapes install root")
    for p in links:
        if not p.parent.resolve().is_relative_to(base):
            raise ValueError("Skill path escapes install root")
    if args.dry_run:
        print(json.dumps({"scope": args.scope, "platforms": platforms,
            "version": lock["version"], "runtime": str(runtime), "writes": [str(p) for p in changes],
            "skill_links": len(links)}, indent=2))
        return
    base.mkdir(parents=True, exist_ok=True)
    backup = base / ".workflow-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True)
    originals = {}
    for path in changes:
        originals[path] = path.read_bytes() if path.exists() else None
        if path.exists():
            dest = backup / path.relative_to(base)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    stage = Path(tempfile.mkdtemp(prefix=".ew-stage-", dir=base))
    moved_old = False
    activated = False
    applied = []
    try:
        for name in lock["files"]:
            dst = stage / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dst)
        shutil.copy2(ROOT / "workflow.lock.json", stage / "workflow.lock.json")
        state = {"version": lock["version"], "release": lock["release"], "source_commit": git("rev-parse", "HEAD", cwd=ROOT),
                 "lock_sha256": digest((ROOT / "workflow.lock.json").read_bytes()), "repository": REPOSITORY,
                 "platforms": platforms, "scope": args.scope, "headroom": args.headroom, "adhd": args.adhd,
                 "hooks": "configured; live platform execution not verified"}
        (stage / "install.json").write_bytes(encoded(state))
        if runtime.exists():
            runtime.rename(backup / "runtime")
            moved_old = True
        stage.rename(runtime)
        activated = True
        for path, content in changes.items():
            write_atomic(path, content)
            applied.append(path)
        for path, relative in links.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(relative, target_is_directory=True)
    except BaseException as original_error:
        recovery_errors = []
        for path in links:
            try:
                if path.is_symlink() and os.readlink(path) == links[path]:
                    path.unlink()
            except OSError:
                recovery_errors.append(str(path))
        for path in reversed(applied):
            try:
                content = originals[path]
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, content)
            except OSError:
                recovery_errors.append(str(path))
        # A failed config restore must never skip restoration of the old runtime.
        try:
            if activated:
                shutil.rmtree(runtime)
            if moved_old:
                (backup / "runtime").rename(runtime)
        except OSError:
            recovery_errors.append(str(runtime))
        if recovery_errors:
            raise ValueError("Install failed; manual recovery required from " + str(backup)
                             + ": " + ", ".join(recovery_errors)) from original_error
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print("Installed", lock["version"], "for", ", ".join(platforms), "at", runtime)
    print("Backup:", backup)
    print("Restart the platform; native session/hook parity still requires a live check.")


def docs(project, refresh=False):
    project = find_project(project)
    result = {"glossary": (project / "GLOSSARY.md").is_file() or (project / "GLOSSARY-MAP.md").is_file(),
              "legacy_context_names": any((project / p).exists() for p in ("CONTEXT.md", "CONTEXT-MAP.md")),
              "adrs": len(list((project / "docs/adr").glob("*.md"))),
              "tracker_configured": (project / "docs/agents/issue-tracker.md").is_file()}
    graph = project / "graphify-out/GRAPH_REPORT.md"
    result["graph"] = "absent"
    if graph.exists():
        changed = git("log", "-1", "--format=%ct", "--", ".", ":(exclude)graphify-out", cwd=project)
        result["graph"] = "stale" if changed and int(changed) > graph.stat().st_mtime else "present; freshness approximate"
    if refresh:
        if not graph.exists() or not shutil.which("graphify"):
            raise ValueError("Graph refresh requires Graphify and an existing graph")
        subprocess.run(["graphify", "update", "."], cwd=project, check=True, timeout=600)
        result["graph"] = "refreshed; commit graphify-out/ with integration change"
    return result


def session(project, platform, expected=None, check_upstream=False):
    runtime = runtime_for(project)
    lock = verify(runtime, expected)
    state_path = runtime / "install.json"
    state = read_json(state_path) if state_path.exists() else {}
    if state and digest((runtime / "workflow.lock.json").read_bytes()) != state["lock_sha256"]:
        raise ValueError("Installed lock differs from installation receipt")
    if state and platform not in state["platforms"]:
        raise ValueError("Platform not installed in selected runtime")
    result = {"workflow": lock["name"], "version": lock["version"], "release": lock["release"],
              "source_commit": state.get("source_commit", git("rev-parse", "HEAD", cwd=runtime)),
              "platform": platform, "runtime": str(runtime), "integrity": "verified",
              "selection": "project pin" if runtime == find_project(project) / ".engineering-workflow" else "user/package default",
              "hooks": "configuration is not live enforcement evidence; confirm in this platform",
              "docs": docs(project), "skill_count": len(lock["skills"])}
    import reviews
    if (find_project(project) / reviews.PROJECT_FILE).is_file():
        configuration = reviews.read_project(project)
        result["project"] = {"id": configuration["project_id"], "public_facing": configuration["public_facing"],
                             "discovery": reviews.discovery_status(configuration)}
    if check_upstream:
        remote = git("ls-remote", REPOSITORY, "refs/tags/" + lock["release"], cwd=runtime)
        if not remote:
            raise ValueError("Could not verify upstream release tag")
        sha = remote.split()[0]
        result["upstream_tag_commit"] = sha
        if state.get("source_commit") and sha != state["source_commit"]:
            raise ValueError("Upstream release tag differs from installed source commit")
    return result


def goal_path(project):
    return find_project(project) / ".engineering-workflow-state/goal.json"


def goal(args):
    p = goal_path(args.project)
    data = read_json(p) if p.exists() else None
    if args.action == "status":
        print(json.dumps(data or {"status": "none"}, indent=2)); return
    if args.action == "set":
        if not args.objective:
            raise ValueError("An explicit objective is required")
        data = {"objective": args.objective, "status": "active", "continuations": 0, "limit": 30}
    elif not data:
        raise ValueError("No goal exists")
    elif args.action in ("complete", "blocked"):
        if not args.evidence:
            raise ValueError("Completion/blocking evidence is required")
        data.update(status=args.action, evidence=args.evidence)
    else:
        data["status"] = "active" if args.action == "resume" else "paused"
        if args.action == "resume": data["continuations"] = 0
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(encoded(data))
    print(json.dumps(data, indent=2))


def guard_command(command, root):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("CLAUDE_GUARD_EXPLAIN", None)
    ran = subprocess.run([sys.executable, "-B", str(root / "vendor/claude-guard/command-guard.py")],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True, text=True, env=env, timeout=8)
    if ran.returncode:
        raise ValueError("Guard failed; command must not be considered checked")
    output = json.loads(ran.stdout) if ran.stdout.strip() else {}
    decision = output.get("hookSpecificOutput", {}).get("permissionDecision")
    # Never echo Guard's raw response: it includes the command, potentially secrets.
    return decision


def credential_paths(project, tool_input):
    project = find_project(project)
    names = git("diff", "--name-only", "HEAD", "--", cwd=project)
    paths = [(project / n) for n in (names or "").splitlines()]
    for key in ("file_path", "path", "Path", "notebook_path"):
        if isinstance(tool_input.get(key), str):
            p = Path(tool_input[key])
            paths.append(p if p.is_absolute() else project / p)
    untracked = git("ls-files", "--others", "--exclude-standard", cwd=project)
    paths.extend(project / n for n in (untracked or "").splitlines())
    return [p for p in set(paths) if p.is_file() and not p.is_symlink()
            and p.resolve().is_relative_to(project) and p.stat().st_size <= 1_000_000
            and ".engineering-workflow" not in p.resolve().relative_to(project).parts]


def credential_check(project, tool_input, root):
    sys.path.insert(0, str(root / "vendor/claude-guard"))
    from guard.packs.credentials import scan_file
    count = sum(bool(scan_file(str(p))) for p in credential_paths(project, tool_input))
    return ("Guard detected potential credential/destructive SQL content in " + str(count)
            + " changed file(s). Inspect locally; do not print or commit secret values.") if count else None


def hook_cwd(data):
    if isinstance(data.get("cwd"), str) and data["cwd"]:
        return data["cwd"]
    paths = data.get("workspacePaths")
    if isinstance(paths, list) and paths and isinstance(paths[0], str) and paths[0]:
        return paths[0]
    return "."


def factory_worker(project):
    """(ticket, turns, max_turns) inside a factory ticket worktree, else None.
    Unreadable factory files fall back to plain Guard, never to allow."""
    if not (Path(project) / ".engineering-workflow-state" / "factory-ticket.json").is_file(): return None
    try:
        import factory
        return factory.worker(project)
    except Exception:  # ponytail: broad on purpose; any failure means "not a factory worker"
        return None


def default_hook_output(platform, event):
    if platform == "agy":
        if event == "PreToolUse": return {"decision": "ask"}
        if event == "Stop": return {"decision": ""}
    return {}


def context_output(platform, event, message):
    if platform == "agy":
        if event == "SessionStart":
            return {"injectSteps": [{"systemMessage": {"systemMessage": message}}]}
        return {"injectSteps": [{"ephemeralMessage": message}]}
    if platform == "gemini":
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}


def hook(platform, data, event=None):
    event = event or data.get("hook_event_name", "")
    project = find_project(hook_cwd(data))
    runtime = runtime_for(project)
    # Verify package bytes before invoking vendored runtime code.
    verify(runtime)
    if event == "SessionStart":
        report = session(project, platform)
        state = read_json(runtime / "install.json") if (runtime / "install.json").exists() else {}
        if state.get("headroom"):
            if shutil.which("headroom"):
                subprocess.run(["headroom", "init", "hook", "ensure"], capture_output=True, timeout=15, check=True)
                report["headroom"] = "startup ensure succeeded; compression not measured"
            else:
                report["headroom"] = "requested but CLI unavailable; no compression claimed"
        rules = ""
        if state.get("adhd"):
            # Same text the upstream always-on hook injects, minus front matter.
            rules = (runtime / ADHD_SKILL).read_text().split("---", 2)[2].strip()
            rules = ("\n\nADHD MODE ACTIVE (always-on). The ruleset below applies to every response. "
                     '"stop adhd mode" turns it off for this session.\n\n' + rules)
            report["adhd"] = "always-on ruleset injected"
        p = goal_path(project)
        if p.exists(): report["goal"] = read_json(p)
        return context_output(platform, event, json.dumps(report) + rules)
    if event in ("PreToolUse", "BeforeTool"):
        tc = data.get("toolCall") if isinstance(data.get("toolCall"), dict) else {}
        inp = (tc.get("args") if isinstance(tc.get("args"), dict) else None) or data.get("tool_input") or {}
        tool = tc.get("name") or data.get("tool_name", "")
        command = inp.get("command", inp.get("cmd", inp.get("CommandLine", "")))
        worker = factory_worker(project)
        decision, reason = None, "Claude Guard requires local review of this command; command text withheld."
        if worker and worker[1] >= worker[2]:
            decision, reason = "deny", f"Factory turn cap reached; run factory report {worker[0]} blocked"
        elif tool in ("Bash", "exec_command", "shell_command", "run_shell_command", "run_command") and isinstance(command, str):
            decision = guard_command(command, runtime)
            if decision == "ask" and worker:  # nobody watches a factory worker, so a prompt would wait forever
                import factory
                factory.flag_permission(project)
                decision = "deny"
        if decision in ("deny", "ask"):
            if platform in ("gemini", "agy"): return {"decision": "deny", "reason": reason}
            return {"hookSpecificOutput": {"hookEventName": event,
                "permissionDecision": decision, "permissionDecisionReason": reason}}
        return default_hook_output(platform, event)
    if event in ("PostToolUse", "AfterTool", "PostInvocation"):
        tc = data.get("toolCall") if isinstance(data.get("toolCall"), dict) else {}
        inp = (tc.get("args") if isinstance(tc.get("args"), dict) else None) or data.get("tool_input") or {}
        message = credential_check(project, inp, runtime)
        if factory_worker(project):
            import factory
            factory.count_turn(project)
        if message: return context_output(platform, event, message)
    if event in ("Stop", "AfterAgent"):
        # Subagents must not drive the controller's standing-goal loop.
        if data.get("agent_id") or data.get("agentId"): return default_hook_output(platform, event)
        if data.get("terminationReason") in ("USER_CANCELED", "ERROR"): return default_hook_output(platform, event)
        p = goal_path(project)
        if not p.exists(): return default_hook_output(platform, event)
        current = read_json(p)
        if current["status"] != "active": return default_hook_output(platform, event)
        if current["continuations"] >= current["limit"]:
            current["status"] = "needs-attention"
            p.write_bytes(encoded(current))
            msg = "Workflow continuation budget exhausted; inspect goal status before resuming."
            return {"decision": "", "reason": msg} if platform == "agy" else {"systemMessage": msg}
        current["continuations"] += 1
        p.write_bytes(encoded(current))
        reason = ("Continue the explicitly requested workflow goal. Read .engineering-workflow-state/goal.json. "
                  "Do not broaden scope or bypass approvals. Complete with fresh evidence, or record a blocker.")
        if platform == "agy": return {"decision": "continue", "reason": reason}
        return {"decision": "deny" if platform == "gemini" else "block", "reason": reason}
    return default_hook_output(platform, event)


def main():
    import factory
    import reviews
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    reviews.add_parser(sub)
    factory.add_parser(sub)
    sub.add_parser("freeze", help="Maintainer: regenerate release checksums")
    v = sub.add_parser("verify"); v.add_argument("--expected")
    i = sub.add_parser("install")
    i.add_argument("--scope", choices=("project", "user"), default="project")
    i.add_argument("--platform", choices=(*PLATFORMS, "all"), required=True,
                   help="Confirm the platform explicitly; installation never guesses")
    i.add_argument("--project", default="."); i.add_argument("--home", default=str(Path.home()))
    i.add_argument("--headroom", action="store_true"); i.add_argument("--dry-run", action="store_true")
    i.add_argument("--adhd", action="store_true", help="Inject the vendored i-have-adhd ruleset at every session start")
    i.add_argument("--expected")
    i.add_argument("--replace-overlap", action="store_true",
                   help="Disable selected duplicate/retired plugins and old Headroom startup/shell hooks")
    for name in ("session", "doctor"):
        d = sub.add_parser(name); d.add_argument("--project", default=".")
        d.add_argument("--platform", choices=PLATFORMS, required=True)
        d.add_argument("--expected"); d.add_argument("--check-upstream", action="store_true")
    d = sub.add_parser("docs"); d.add_argument("--project", default="."); d.add_argument("--refresh", action="store_true")
    g = sub.add_parser("goal"); g.add_argument("action", choices=("set", "status", "pause", "resume", "complete", "blocked"))
    g.add_argument("objective", nargs="?"); g.add_argument("--project", default="."); g.add_argument("--evidence")
    h = sub.add_parser("hook"); h.add_argument("--platform", choices=PLATFORMS, required=True)
    h.add_argument("--event", default="")
    a = p.parse_args()
    try:
        raw_hook = None
        if a.command in ("session", "doctor", "docs", "goal", "hook", "project", "review", "factory"):
            if a.command == "hook":
                raw_hook = sys.stdin.read()
                data = json.loads(raw_hook) if raw_hook.strip() else {}
                selected = runtime_for(hook_cwd(data))
            else:
                selected = runtime_for(a.project)
            if selected.resolve() != ROOT:
                verify(selected)
                if a.command == "hook":
                    # A project install registers its own lifecycle handlers.
                    # Global hooks yield rather than running every event twice.
                    ev = a.event or data.get("hook_event_name", "")
                    print(json.dumps(default_hook_output(a.platform, ev)))
                    return 0
                # Execute the pinned implementation, not the global copy's semantics.
                return subprocess.run([sys.executable, "-B", str(selected / "workflow.py"),
                                       *sys.argv[1:]], input=raw_hook, text=True).returncode
        if a.command == "freeze": freeze()
        elif a.command in ("project", "review"): print(json.dumps(reviews.run(a), indent=2))
        elif a.command == "factory": return factory.run(a)
        elif a.command == "verify": print("Verified workflow", verify(expected=a.expected)["version"])
        elif a.command == "install": install(a)
        elif a.command in ("session", "doctor"): print(json.dumps(session(a.project, a.platform, a.expected, a.check_upstream), indent=2))
        elif a.command == "docs": print(json.dumps(docs(a.project, a.refresh), indent=2))
        elif a.command == "goal": goal(a)
        elif a.command == "hook":
            print(json.dumps(hook(a.platform, data, event=a.event)))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        # Do not echo raw tool inputs, subprocess output or credentials.
        if a.command == "hook":
            print("Engineering workflow hook failed; verification/enforcement unavailable.", file=sys.stderr)
            ev = getattr(a, "event", "") or (data.get("hook_event_name") if isinstance(locals().get("data"), dict) else "")
            if ev in ("Stop", "AfterAgent"):
                if a.platform == "agy":
                    print(json.dumps({"decision": "", "reason": "Workflow verification failed; inspect installation before resuming."}))
                else:
                    print(json.dumps({"continue": False, "stopReason": "Workflow verification failed; inspect installation before resuming."}))
                return 0
            return 2
        print("Error:", error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
