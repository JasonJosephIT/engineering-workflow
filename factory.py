"""Factory mode: build a feature's tickets unattended, one Orca worker per ticket."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from workflow import encoded, find_project, git, read_json, write_atomic

ROOT = Path(__file__).resolve().parent
STATE = ".engineering-workflow-state"
GATES = Path(".engineering-workflow") / "gates.sh"
PROTECTED = ("main", "master")
BYPASS_REASON = ("Orca launched in bypass mode; remove it from Orca's Claude arguments "
                 "or reinstall with --allow-bypass")
HEARTBEAT_PROMPT = "Run `workflow.py factory tick` for this project, report its output, do nothing else."


def now(): return datetime.now(timezone.utc).isoformat()
def save(path, value): write_atomic(path, encoded(value))
def command(*argv): return " ".join(shlex.quote(str(a)) for a in argv)
def workflow_command(*args): return command(sys.executable, ROOT / "workflow.py", "factory", *args)


# --- Orca adapter: the only code that calls the orca CLI -------------------------

def orca_executable():
    name = os.environ.get("ORCA_CLI_COMMAND") or ("orca-ide" if sys.platform.startswith("linux") else "orca")
    path = shutil.which(name)
    if not path: raise ValueError(f"Orca CLI not found ({name})")
    return path


def orca(*args, check=True):
    result = subprocess.run([orca_executable(), *args, "--json"], text=True, capture_output=True, timeout=60)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        data = {"ok": False, "error": "unreadable reply"}
    if check and not data.get("ok"):
        error = data.get("error")
        detail = error.get("message") or error.get("code") if isinstance(error, dict) else error
        raise ValueError(f"orca {' '.join(args[:2])} failed: {detail or result.stderr.strip() or 'no detail'}")
    return data.get("result") or {}


def repo_registered(checkout):
    try: orca("repo", "show", "--repo", f"path:{checkout}")
    except ValueError: return False
    return True


def register_heartbeat(state):
    checkout = state["integration_checkout"]
    result = orca("automations", "create", "--name", f"factory {state['feature']}", "--trigger", "hourly",
                  "--provider", "claude", "--workspace", f"path:{checkout}",
                  "--precheck", workflow_command("precheck", "--project", checkout),
                  "--extra-agent-args=--model sonnet", "--prompt", HEARTBEAT_PROMPT, "--enabled")
    return (result.get("automation") or {}).get("id") or result.get("id")


def launch_worker(worktree, prompt):
    result = orca("agent", "launch", "--agent", "claude", "--worktree", f"path:{worktree}",
                  "--surface", "terminal", "--prompt", prompt)
    return result["launch"]["outcome"]["handle"]


def worker_alive(handle):
    return bool(orca("terminal", "show", "--terminal", handle).get("terminal", {}).get("connected"))


def stop_worker(handle):
    orca("terminal", "close", "--terminal", handle, check=False)  # reports ok:false even when it worked
    return not worker_alive(handle)


def worker_in_bypass(handle):
    text = json.dumps(orca("terminal", "read", "--terminal", handle, "--limit", "40")).lower()
    return "dangerously-skip-permissions" in text or "bypass permissions" in text


# --- State, ledger, tickets -------------------------------------------------------

def ticket_marker(project):
    return find_project(project) / STATE / "factory-ticket.json"


def state_dir(project):
    marker = ticket_marker(project)
    return Path(read_json(marker)["state_dir"]) if marker.is_file() else find_project(project) / STATE / "factory"


def load(directory):
    if not (directory / "state.json").is_file(): raise ValueError("No factory installed for this project")
    ledger = directory / "ledger.json"
    return read_json(directory / "state.json"), read_json(ledger) if ledger.is_file() else {}


def tickets(checkout, feature):
    found = []
    for path in sorted((Path(checkout) / ".scratch" / feature / "issues").glob("[0-9][0-9]-*.md")):
        fields = {}
        for key, value in re.findall(r"^\**([A-Z][A-Za-z ]*?):\**[ \t]*(\S.*?)[ \t]*$", path.read_text(), re.M):
            fields.setdefault(key, value)  # the header's line wins over later body lines
        found.append({"id": path.name[:2], "path": path, "status": fields.get("Status", "")})
    return found


def ready_tickets(state, ledger):
    return [t for t in tickets(state["integration_checkout"], state["feature"])
            if t["status"] == "ready-for-agent" and t["id"] not in ledger]


def move(entry, new_state, reason=None):
    entry["state"] = new_state
    if reason: entry["reason"] = reason
    entry["history"].append({"at": now(), "state": new_state})


@contextmanager
def tick_lock(directory):
    if not (directory / "state.json").is_file(): raise ValueError("No factory installed for this project")
    with open(directory / "tick.lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


# --- Gate -------------------------------------------------------------------------

def run_gate(checkout):
    script = Path(checkout) / GATES
    if not script.is_file(): return False, f"GATES: FAIL missing {GATES}"
    result = subprocess.run(["bash", str(script)], cwd=checkout, text=True, capture_output=True)
    output = result.stdout + result.stderr
    lines = result.stdout.splitlines()
    return bool(lines) and lines[-1] == "GATES: PASS", output


def starter_gate(checkout):
    checkout, checks = Path(checkout), []
    if any((checkout / "tests").glob("*.py")): checks.append(("tests", "python3 -m unittest discover -s tests"))
    if (checkout / "package.json").is_file(): checks.append(("npm-test", "npm test"))
    makefile = checkout / "Makefile"
    if makefile.is_file() and re.search(r"^test:", makefile.read_text(), re.M): checks.append(("make-test", "make test"))
    lines = ["#!/usr/bin/env bash", "# Factory gate: the last line must be exactly GATES: PASS."]
    lines += [f'{cmd} || {{ echo "GATES: FAIL {name}"; exit 1; }}' for name, cmd in checks]
    return "\n".join([*lines, 'echo "GATES: PASS"'])


# --- Tick steps -------------------------------------------------------------------

def gate_ticket(entry):
    """Return a needs-you reason, or None when the ticket branch is clean and passes its gate."""
    if git("status", "--porcelain", cwd=entry["worktree"]) != "":
        return "uncommitted changes in the worktree"
    passed, _ = run_gate(entry["worktree"])
    return None if passed else "gates failed on the ticket branch"


def merge_ticket(state, entry):
    """Merge into the integration branch; return a needs-you reason, or None when merged."""
    checkout, target = state["integration_checkout"], state["integration_branch"]
    current = git("branch", "--show-current", cwd=checkout)
    if current != target or current in PROTECTED:
        raise ValueError(f"Integration checkout is on {current!r}, not {target!r}; refusing to merge")
    if git("merge", "--no-ff", "--no-edit", entry["branch"], cwd=checkout) is None:
        git("merge", "--abort", cwd=checkout)
        return "merge conflict"
    git("worktree", "remove", "--force", entry["worktree"], cwd=checkout)
    return None


def merge_approved(state, ledger, out):
    for ticket, entry in ledger.items():
        if entry["state"] != "approved":
            continue
        reason = gate_ticket(entry) or merge_ticket(state, entry)
        if reason:
            move(entry, "needs-you", reason)
            out.append(f"{ticket} needs you: {reason}")
        else:
            move(entry, "merged")
            out.append(f"merged {ticket} into {state['integration_branch']}")


def worker_brief(state, ticket, worktree):
    path = Path(worktree) / Path(ticket["path"]).relative_to(state["integration_checkout"])
    return (f"You are a factory worker. Implement the ticket {path} on this worktree's branch only. "
            f"Run the gates with: {workflow_command('gate', '--project', worktree)} and commit your work. "
            f"Finish with: {workflow_command('report', ticket['id'], 'approved', '--project', worktree)}"
            f' --slowed-by "<one line>" (or report blocked --reason "<one line>").')


def claim(state, ledger, ticket):
    """Branch from the integration tip, add the worktree and marker, and persist a working entry."""
    checkout, directory = state["integration_checkout"], Path(state["state_dir"])
    branch = f"factory/{state['feature']}-{ticket['id']}"
    if git("branch", branch, state["integration_branch"], cwd=checkout) is None:
        return None  # already claimed
    worktree = directory / "worktrees" / f"{state['feature']}-{ticket['id']}"
    if git("worktree", "add", str(worktree), branch, cwd=checkout) is None:
        raise ValueError(f"Could not create worktree for {branch}")
    save(ticket_marker(worktree), {"ticket": ticket["id"], "state_dir": str(directory)})
    entry = ledger[ticket["id"]] = {
        "state": "working", "branch": branch, "worktree": str(worktree), "worker_handle": None,
        "started_at": now(), "turns": 0, "queue_wait_seconds": 0, "gate_seconds": 0,
        "slowed_by": None, "reason": None, "history": [{"at": now(), "state": "working"}]}
    save(directory / "ledger.json", ledger)  # a crash during launch must not lose the claim
    return entry


def launch(state, entry, ticket, out):
    """Launch the worker; park the ticket on launch failure or an unallowed bypass launch."""
    try:
        entry["worker_handle"] = launch_worker(entry["worktree"], worker_brief(state, ticket, entry["worktree"]))
    except ValueError as error:
        move(entry, "needs-you", f"worker launch failed: {error}")
        out.append(f"{ticket['id']} needs you: worker launch failed")
        return
    out.append(f"claimed {ticket['id']} on {entry['branch']}")
    if state["allow_bypass"] or not worker_in_bypass(entry["worker_handle"]):
        return
    stopped = stop_worker(entry["worker_handle"])
    move(entry, "needs-you", BYPASS_REASON)
    state["mode"] = "paused"
    out.append(f"{ticket['id']} needs you: {BYPASS_REASON}; factory paused")
    if not stopped:
        out.append(f"worker {entry['worker_handle']} did not stop; close it in Orca")


def startable(state, ledger):
    """Ready tickets this mode may start: all in running, the wave's in once, none otherwise."""
    if state["mode"] == "running": return ready_tickets(state, ledger)
    if state["mode"] == "once": return [t for t in ready_tickets(state, ledger) if t["id"] in state["wave"]]
    return []


def start_tickets(state, ledger, out):
    for ticket in startable(state, ledger)[:1]:  # ponytail: one per tick; ticket 03 adds concurrency
        entry = claim(state, ledger, ticket)
        if entry is None:
            out.append(f"{ticket['id']} already claimed")
        else:
            launch(state, entry, ticket, out)


def in_flight(ledger): return any(e["state"] in ("working", "approved") for e in ledger.values())


def wave_settled(state, ledger, ticket):
    """Done for this wave: finished or parked, or never claimable here (no longer ready, or claimed elsewhere)."""
    if ticket in ledger: return ledger[ticket]["state"] in ("merged", "needs-you", "capped", "interrupted")
    branch = f"refs/heads/factory/{state['feature']}-{ticket}"
    claimed = git("rev-parse", "--verify", "--quiet", branch, cwd=state["integration_checkout"]) is not None
    return claimed or ticket not in [t["id"] for t in startable(state, ledger)]


def update_mode(state, ledger, out):
    """draining -> paused once nothing is in flight; once -> paused once every wave ticket is settled."""
    if state["mode"] == "draining" and not in_flight(ledger):
        state["mode"] = "paused"
        out.append("drained; factory paused")
    elif state["mode"] == "once" and all(wave_settled(state, ledger, t) for t in state["wave"]):
        state["mode"], state["wave_ended_at"] = "paused", now()
        out.append("wave done; factory paused")


def tick(directory):
    with tick_lock(directory):
        state, ledger = load(directory)
        out = []
        try:
            merge_approved(state, ledger, out)
            start_tickets(state, ledger, out)
            update_mode(state, ledger, out)
            state["last_tick"] = now()
        finally:  # keep merges and claims made before any failure
            save(directory / "ledger.json", ledger)
            save(directory / "state.json", state)
    print("\n".join(out) or "nothing to do")


# --- CLI actions ------------------------------------------------------------------

def install(args):
    orca_executable()
    checkout = find_project(args.project)
    directory = checkout / STATE / "factory"
    if (directory / "state.json").is_file(): raise ValueError("A factory is already installed for this project")
    if not args.feature: raise ValueError("--feature is required")
    branch = args.integration_branch or git("branch", "--show-current", cwd=checkout)
    if not branch or git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=checkout) is None:
        raise ValueError(f"Integration branch {branch!r} does not exist")
    if branch in PROTECTED: raise ValueError(f"The integration branch cannot be {branch}")
    if not tickets(checkout, args.feature): raise ValueError(f"No ticket files in .scratch/{args.feature}/issues/")
    if not (checkout / GATES).is_file():
        raise ValueError(f"No gate script at {GATES}. Save and commit this starter, then install again:\n"
                         f"{starter_gate(checkout)}")
    if not repo_registered(checkout): raise ValueError("This repo is not registered in Orca")
    if git("check-ignore", "-q", STATE + "/", cwd=checkout) is None:
        exclude = (checkout / git("rev-parse", "--git-common-dir", cwd=checkout)).resolve() / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        with open(exclude, "a") as stream: stream.write(f"\n{STATE}/\n")
    state = {"mode": "paused" if args.paused else "running", "feature": args.feature,
             "integration_branch": branch, "integration_checkout": str(checkout), "state_dir": str(directory),
             "allow_bypass": args.allow_bypass, "concurrency": 3, "build_slots": 1, "daily_ticket_cap": 10,
             "stop_if_waiting": 5, "max_turns": 100, "max_minutes": 90, "automation_id": None, "wave": [],
             "final_review": "not-started", "last_tick": None}
    state["automation_id"] = register_heartbeat(state)
    save(directory / "state.json", state)
    print(f"Factory installed for {args.feature} on {branch} ({state['mode']})")


def status(args):
    state, ledger = load(state_dir(args.project))
    count = lambda name: sum(e["state"] == name for e in ledger.values())
    print(f"factory: {state['mode']} · {len(ready_tickets(state, ledger)) + count('ready')} ready"
          f" · {count('working')} building · {count('needs-you')} needs you")
    for ticket, entry in sorted(ledger.items()):
        print(" ".join(filter(None, [ticket, entry["state"], entry["branch"], entry["reason"]])))


def gate(args):
    passed, output = run_gate(find_project(args.project))
    print(output, end="")
    return 0 if passed else 1


def report(args):
    if args.result not in ("approved", "blocked"): raise ValueError("report needs <ticket> approved|blocked")
    directory = state_dir(args.project)
    with tick_lock(directory):
        state, ledger = load(directory)
        entry = ledger.get(args.ticket)
        if not entry or entry["state"] != "working": raise ValueError(f"Ticket {args.ticket} is not working")
        entry["slowed_by"] = args.slowed_by
        if args.result == "approved": move(entry, "approved")
        else: move(entry, "needs-you", args.reason or "blocked")
        save(directory / "ledger.json", ledger)
    tick(directory)


def precheck(args):
    # ponytail: no free-capacity check; full capacity means working tickets, which already count as work.
    state, ledger = load(state_dir(args.project))
    work = in_flight(ledger) or startable(state, ledger)
    return 0 if state["mode"] != "paused" and work else 1


def set_mode(directory, mode):
    with tick_lock(directory):
        state, ledger = load(directory)
        if mode == "draining" and not in_flight(ledger): mode = "paused"
        if mode == "once":
            state["wave"] = [t["id"] for t in ready_tickets(state, ledger)]
            state.pop("wave_ended_at", None)
        state["mode"] = mode
        save(directory / "state.json", state)
    return mode


def pause(args):
    directory = state_dir(args.project)
    if not args.now:
        print(f"factory {set_mode(directory, 'draining')}")
        return
    with tick_lock(directory):
        state, ledger = load(directory)
        for ticket, entry in ledger.items():
            if entry["state"] != "working":
                continue
            try: stopped = not entry["worker_handle"] or stop_worker(entry["worker_handle"])
            except (ValueError, subprocess.SubprocessError): stopped = False  # what the adapter can raise
            if not stopped: print(f"worker {entry['worker_handle']} did not stop; close it in Orca")
            move(entry, "interrupted")
            print(f"interrupted {ticket}; {entry['branch']} and its worktree are kept")
        state["mode"] = "paused"
        save(directory / "ledger.json", ledger)
        save(directory / "state.json", state)
    print("factory paused")


def resume(args):
    set_mode(state_dir(args.project), "running")
    tick(state_dir(args.project))


def cycle(args):
    set_mode(state_dir(args.project), "once")
    tick(state_dir(args.project))  # a manual Orca automation run ignores the precheck, so tick directly


def add_parser(sub):
    f = sub.add_parser("factory", help="Unattended per-ticket builds through Orca")
    f.add_argument("action", choices=("install", "status", "tick", "gate", "report", "precheck",
                                      "pause", "resume", "cycle"))
    f.add_argument("ticket", nargs="?"); f.add_argument("result", nargs="?")
    f.add_argument("--project", default="."); f.add_argument("--feature")
    f.add_argument("--integration-branch", help="Default: the branch checked out in the project")
    f.add_argument("--paused", action="store_true"); f.add_argument("--allow-bypass", action="store_true")
    f.add_argument("--slowed-by"); f.add_argument("--reason")
    f.add_argument("--now", action="store_true", help="pause: stop every worker now (keeps their worktrees)")


def run(args):
    actions = {"install": install, "status": status, "gate": gate, "report": report, "precheck": precheck,
               "tick": lambda a: tick(state_dir(a.project)),
               "pause": pause, "resume": resume, "cycle": cycle}
    return actions[args.action](args) or 0
