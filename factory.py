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
import signal
import stat
import subprocess
import sys
import time

from workflow import encoded, find_project, git, read_json, write_atomic

ROOT = Path(__file__).resolve().parent
STATE = ".engineering-workflow-state"
GATES = Path(".engineering-workflow") / "gates.sh"
PROTECTED = ("main", "master")
BYPASS_REASON = ("Orca launched in bypass mode; remove it from Orca's Claude arguments "
                 "or reinstall with --allow-bypass")
BYPASS_WORDS = ("dangerously-skip-permissions", "bypass permissions", "bypasspermissions")
LEFTOVER = "claim branch exists without a ledger entry"
REQUEUABLE = ("needs-you", "capped", "interrupted")
CARDS = {"working": "in-progress", **dict.fromkeys(REQUEUABLE, "in-review"), "merged": "completed"}
FRESH_COUNTERS = {"turns": 0, "permission_needed": False}
SETTINGS = ("concurrency", "build_slots", "daily_ticket_cap", "stop_if_waiting", "max_turns", "max_minutes")
PERSON_ONLY = ("install", "uninstall", "set", "pause", "resume", "cycle", "approve", "requeue")
WORKTREES = (STATE, "factory", "worktrees")
CONTROL_DIRS = {".engineering-workflow", ".claude", ".codex", ".agents", ".gemini"}
CONTROL_FILES = {"CLAUDE.md", "AGENTS.md", "GEMINI.md", ".gitignore", ".gitattributes", ".gitmodules"}


def now(): return datetime.now(timezone.utc).isoformat()
def save(path, value): write_atomic(path, encoded(value))
def workflow_command(*args): return shlex.join(map(str, (sys.executable, ROOT / "workflow.py", "factory", *args)))


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


def set_card(worktree, status, comment=None):
    """Set the worktree's Orca card; a comment also raises the unread dot."""
    extra = ["--comment", comment, "--unread"] if comment else []
    orca("worktree", "set", "--worktree", f"path:{worktree}", "--workspace-status", status, *extra)


def register_heartbeat(state):
    checkout = state["integration_checkout"]
    result = orca("automations", "create", "--name", f"factory {state['feature']}", "--trigger", "hourly",
                  "--provider", "claude", "--workspace", f"path:{checkout}",
                  "--precheck", workflow_command("precheck", "--project", checkout),
                  "--extra-agent-args=--model sonnet", "--enabled", "--prompt",
                  f"Run `{workflow_command('tick', '--detach', '--project', checkout)}`, report its output, do nothing else.")
    return (result.get("automation") or {}).get("id") or result.get("id")


def remove_heartbeat(automation_id):
    orca("automations", "remove", automation_id)


def launch_worker(worktree, prompt):
    result = orca("agent", "launch", "--agent", "claude", "--worktree", f"path:{worktree}",
                  "--surface", "terminal", "--prompt", prompt)
    return result["launch"]["outcome"]["handle"]


def worker_alive(handle):
    return bool(orca("terminal", "show", "--terminal", handle).get("terminal", {}).get("connected"))


def stop_worker(handle):
    orca("terminal", "close", "--terminal", handle, check=False)  # reports ok:false even when it worked
    return not worker_alive(handle)


def stop(entry):
    """Stop the entry's worker; False when Orca cannot confirm it stopped."""
    try: return not entry["worker_handle"] or stop_worker(entry["worker_handle"])
    except (ValueError, OSError, subprocess.SubprocessError): return False  # what the adapter can raise


def bypass_problem(handle):
    """Why this agent must not run without --allow-bypass, or None; a terminal Orca cannot show fails closed."""
    try: text = json.dumps(orca("terminal", "read", "--terminal", handle, "--limit", "40")).lower()
    except (ValueError, OSError, subprocess.SubprocessError): return "could not confirm Orca's permission mode"
    return BYPASS_REASON if any(word in text for word in BYPASS_WORDS) else None


# --- State, ledger, tickets -------------------------------------------------------

def ticket_marker(project):
    return find_project(project) / STATE / "factory-ticket.json"


def in_ticket_worktree(path):
    """Inside a ticket worktree, by its marker or by where it lies (a worker can delete its marker)."""
    parts = Path(path).resolve().parts
    return ticket_marker(path).is_file() or any(parts[i:i + 3] == WORKTREES for i in range(len(parts)))


def read_regular(path):
    """read_json that never blocks: a FIFO or any other non-regular file raises ValueError."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError(f"{Path(path).name} is not a regular file")
        return json.loads(stream.read())


def lock_within(handle, mode, seconds=1.0):
    """flock that gives up: TimeoutError once the lock has stayed busy for `seconds`."""
    deadline = time.monotonic() + seconds
    while True:
        try: return fcntl.flock(handle, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() > deadline: raise TimeoutError("factory counters are locked")
            time.sleep(0.05)


def state_dir(project):
    marker = ticket_marker(project)
    return Path(read_json(marker)["state_dir"]) if marker.is_file() else find_project(project) / STATE / "factory"


def counters(worktree, change=None, reset=False):
    """The worktree's hook counters; `change` edits them, `reset` starts them fresh without reading.
    Kept out of the ledger so hooks never wait on the tick lock, which tick holds through pre-merge gates.
    Raises ValueError for a file that is not valid counters: the worker can write it, so callers fail closed.
    Never blocks: a busy lock raises TimeoutError, a FIFO or other non-regular file ValueError."""
    path = Path(worktree) / STATE / "factory-turns.json"
    fd = os.open(path.with_name("factory-turns.lock"), os.O_RDWR | os.O_CREAT | os.O_NONBLOCK, 0o644)
    with os.fdopen(fd, "r+") as lock:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError("factory-turns.lock is not a regular file")
        lock_within(lock, fcntl.LOCK_EX if change or reset else fcntl.LOCK_SH)
        data = dict(FRESH_COUNTERS) if reset or not os.path.lexists(path) else read_regular(path)
        if not (isinstance(data, dict) and type(data.get("turns")) is int and data["turns"] >= 0
                and type(data.get("permission_needed")) is bool):
            raise ValueError("unreadable factory counters")
        if change: change(data)
        if change or reset: save(path, data)
    return data


def worker(project):
    """(ticket, turns, max_turns) for a hook in a ticket worktree; raises when the marker, state or lock is unreadable."""
    ticket = read_regular(ticket_marker(project))
    max_turns = int(read_regular(Path(ticket["state_dir"]) / "state.json")["max_turns"])
    try: turns = counters(project)["turns"]
    except ValueError: turns = max_turns  # a bad counters file never loosens the cap
    return str(ticket["ticket"]), turns, max_turns


def count_turn(project): counters(project, lambda c: c.update(turns=c["turns"] + 1))
def flag_permission(project): counters(project, lambda c: c.update(permission_needed=True))


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
        radius = fields.get("Blast radius")
        found.append({"id": path.name[:2], "path": path, "status": fields.get("Status", ""),
                      "radius": radius if radius in ("low", "medium") else "high",
                      "blocked_by": re.findall(r"(?:^|,)\s*(\d\d)\b", fields.get("Blocked by", ""))})
    return found


def ready_tickets(state, ledger):
    found = tickets(state["integration_checkout"], state["feature"])
    status = {t["id"]: t["status"] for t in found}

    def merged(blocker):  # a blocker outside the ledger is a manual ticket: resolved/done counts
        return ledger[blocker]["state"] == "merged" if blocker in ledger else status.get(blocker) in ("resolved", "done")

    def fresh(ticket):
        return ticket["status"] == "ready-for-agent" and all(merged(b) for b in ticket["blocked_by"])

    return [t for t in found if (ledger[t["id"]]["state"] == "ready" if t["id"] in ledger else fresh(t))]


def move(entry, new_state, reason=None):
    entry["state"] = new_state
    if reason: entry["reason"] = reason
    entry["history"].append({"at": now(), "state": new_state})


def card(ticket, entry, out):
    """Bring the entry's Orca card up to date; a failure prints a line and is retried next time."""
    status = CARDS.get(entry["state"])
    label = "" if entry["state"] == "needs-you" else f"{entry['state']}: "
    comment = f"NEEDS YOU: {label}{entry['reason']}" if entry["state"] in REQUEUABLE else None
    if not status or entry.get("card") == [status, comment]:
        return
    if not Path(entry["worktree"]).exists():  # Orca's card went with the worktree; never retry
        entry["card"] = [status, comment]
        return
    try:
        set_card(entry["worktree"], status, comment)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        out.append(f"card for {ticket} not updated: {error}")
        return
    entry["card"] = [status, comment]


@contextmanager
def tick_lock(directory):
    if not (directory / "state.json").is_file(): raise ValueError("No factory installed for this project")
    with open(directory / "tick.lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield load(directory)  # (state, ledger), read under the lock


# --- Gate -------------------------------------------------------------------------

def run_gate(cwd, script, minutes):
    """Run `script` in cwd, in its own process group, killed and failed after `minutes`."""
    if not script.is_file(): return False, f"GATES: FAIL missing {GATES}"
    gate = subprocess.Popen(["bash", str(script)], cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = gate.communicate(timeout=minutes * 60)
    except subprocess.TimeoutExpired:
        os.killpg(gate.pid, signal.SIGKILL)
        stdout, stderr = gate.communicate()
        stdout += "GATES: FAIL timeout\n"
    lines = stdout.splitlines()
    return bool(lines) and lines[-1] == "GATES: PASS", stdout + stderr


def queued_gate(directory, cwd, script=None):
    """Run the gate (default: cwd's own script) inside one of build_slots slot locks;
    return (passed, output, waited, ran) seconds."""
    state_file = Path(directory) / "state.json"
    state = read_json(state_file) if state_file.is_file() else {"build_slots": 1, "max_minutes": 90}
    slots, script = state["build_slots"], script or Path(cwd) / GATES
    (Path(directory) / "slots").mkdir(parents=True, exist_ok=True)
    begin = time.monotonic()
    while True:
        for number in range(slots):
            handle = open(Path(directory) / "slots" / f"{number}.lock", "a")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the kernel frees it if we die
            except BlockingIOError:
                handle.close(); continue
            with handle:
                started = time.monotonic()
                passed, output = run_gate(cwd, script, state["max_minutes"])
                return passed, output, started - begin, time.monotonic() - started
        time.sleep(0.1)  # ponytail: polling; a fair FIFO queue only if starvation shows up


def record_gate(entry, waited, ran):
    entry["queue_wait_seconds"] = round(entry.get("queue_wait_seconds", 0) + waited, 3)
    entry["gate_seconds"] = round(ran, 3)


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

def gate_ticket(state, entry):
    """Return a needs-you reason, or None when the ticket branch is clean and passes its gate."""
    if git("status", "--porcelain", cwd=entry["worktree"]) != "":
        return "uncommitted changes in the worktree"
    # the integration branch's script: the worker can rewrite the ticket branch's copy
    passed, output, waited, ran = queued_gate(state["state_dir"], entry["worktree"],
                                              Path(state["integration_checkout"]) / GATES)
    record_gate(entry, waited, ran)
    if passed: return None
    return "gate timed out on the ticket branch" if "GATES: FAIL timeout" in output else "gates failed on the ticket branch"


def control_files(state, entry):
    """A needs-you reason when the ticket changes files that steer the factory or later agents, else None."""
    changed = git("diff", "--name-only", f"{state['integration_branch']}...{entry['branch']}",
                  cwd=state["integration_checkout"])
    if changed is None: return "could not list the ticket's changes"
    hits = [p for p in changed.splitlines() if CONTROL_DIRS & set(Path(p).parts) or Path(p).name in CONTROL_FILES
            or p.startswith(f".scratch/{state['feature']}/")]
    return f"changes workflow control files: {', '.join(hits[:3])}" if hits else None


def integration_checkout(state):
    checkout, target = state["integration_checkout"], state["integration_branch"]
    current = git("branch", "--show-current", cwd=checkout)
    if current != target or current in PROTECTED:
        raise ValueError(f"Integration checkout is on {current!r}, not {target!r}; refusing to merge")
    return checkout


def merge_ticket(state, entry):
    """Merge into the integration branch; return a needs-you reason, or None when merged."""
    checkout = integration_checkout(state)
    try:
        merged = git("merge", "--no-ff", "--no-edit", entry["branch"], cwd=checkout, timeout=300)
    except subprocess.TimeoutExpired:
        git("merge", "--abort", cwd=checkout)
        return "merge timed out"
    if merged is None:
        git("merge", "--abort", cwd=checkout)
        return "merge conflict"
    return None


def valid(state, ticket, entry):
    """The ledger is worker-writable: act only on this ticket's own worktree and branch."""
    worktree = Path(entry["worktree"]).resolve()
    return (worktree.parent == (Path(state["state_dir"]) / "worktrees").resolve()
            and entry["branch"] == branch_name(state, ticket))


def land(state, ticket, entry, out, hold=None):
    """Gate, then merge; a failure or a hold reason leaves the ticket in needs-you. Returns True when merged."""
    reason = ((None if valid(state, ticket, entry) else "ledger entry failed validation")
              or gate_ticket(state, entry) or hold or merge_ticket(state, entry))
    if reason:
        move(entry, "needs-you", reason)
        out.append(f"{ticket} needs you: {reason}")
        return False
    move(entry, "merged")
    card(ticket, entry, out)  # before the worktree, and with it the Orca card, goes away
    try: git("worktree", "remove", "--force", entry["worktree"], cwd=state["integration_checkout"], timeout=300)
    except subprocess.TimeoutExpired: out.append(f"worktree for {ticket} not removed: git timed out")
    out.append(f"merged {ticket} into {state['integration_branch']}")
    return True


def merge_approved(state, ledger, out):
    for ticket, entry in ledger.items():
        if entry["state"] == "approved":
            # ticket files are only trustworthy on the integration branch
            radius = next((t["radius"] for t in tickets(integration_checkout(state), state["feature"])
                           if t["id"] == ticket), "high")
            hold = control_files(state, entry) or ("high blast radius: waiting for approval" if radius == "high" else None)
            land(state, ticket, entry, out, hold)


def worker_brief(state, ticket, worktree):
    path = Path(worktree) / Path(ticket["path"]).relative_to(state["integration_checkout"])
    return (f"Use the ew-factory skill (worker brief). Ticket: {path}. Ticket id: {ticket['id']}. "
            f"Gate: {workflow_command('gate', '--ticket', ticket['id'], '--project', worktree)}. "
            f"Report: {workflow_command('report', ticket['id'], 'approved', '--detach', '--project', worktree)}"
            f' --slowed-by "<one line>" (blocked instead of approved, plus --reason "<one line>", if stuck).')


def branch_name(state, ticket): return f"factory/{state['feature']}-{ticket}"


def new_entry(state, ticket, status, started_at):
    return {"state": status, "branch": branch_name(state, ticket),
            "worktree": str(Path(state["state_dir"]) / "worktrees" / f"{state['feature']}-{ticket}"),
            "worker_handle": None, "started_at": started_at, "turns": 0, "queue_wait_seconds": 0, "gate_seconds": 0,
            "slowed_by": None, "reason": None, "history": [{"at": now(), "state": status}]}


def make_branch(state, branch):
    """Branch from the integration tip, pushed when a remote exists; False when someone else has it."""
    checkout = state["integration_checkout"]
    if git("branch", branch, state["integration_branch"], cwd=checkout) is None:
        return False
    remote = git("remote", cwd=checkout)
    if remote and git("push", remote.splitlines()[0], branch, cwd=checkout) is None:
        git("branch", "-D", branch, cwd=checkout)
        return False  # push rejected: someone else claimed it
    return True


def add_worktree(state, entry, ticket):
    try: added = git("worktree", "add", entry["worktree"], entry["branch"], cwd=state["integration_checkout"], timeout=300)
    except subprocess.TimeoutExpired: added = None
    if added is None: raise ValueError(f"Could not create worktree for {entry['branch']}")
    save(ticket_marker(entry["worktree"]), {"ticket": ticket, "state_dir": state["state_dir"]})


def claim(state, ledger, ticket):
    """Make the claim branch, persist the entry, add the worktree and marker; None when already claimed."""
    entry = new_entry(state, ticket["id"], "working", now())
    if not make_branch(state, entry["branch"]):
        return None
    ledger[ticket["id"]] = entry
    save(Path(state["state_dir"]) / "ledger.json", ledger)  # persist before the worktree so a crash cannot strand the claim
    add_worktree(state, entry, ticket["id"])
    return entry


def refuse(state, ticket, entry, reason, out):
    """Stop a worker Orca runs in bypass (or cannot show us), park its ticket and pause the factory."""
    stopped = stop(entry)
    move(entry, "needs-you", reason)
    state["mode"] = "paused"
    out.append(f"{ticket} needs you: {reason}; factory paused")
    if not stopped: out.append(f"worker {entry['worker_handle']} did not stop; close it in Orca")


def launch(state, entry, ticket, out, started=None):
    """Launch the worker; park the ticket on launch failure or an unallowed bypass launch."""
    try:
        entry["worker_handle"] = launch_worker(entry["worktree"], worker_brief(state, ticket, entry["worktree"]))
    except ValueError as error:
        move(entry, "needs-you", f"worker launch failed: {error}")
        out.append(f"{ticket['id']} needs you: worker launch failed")
        return
    out.append(started or f"claimed {ticket['id']} on {entry['branch']}")
    reason = None if state["allow_bypass"] else bypass_problem(entry["worker_handle"])
    if reason: refuse(state, ticket["id"], entry, reason, out)


def relaunch(state, entry, ticket, out):
    """Start a fresh worker for a requeued ticket in its existing branch and worktree; False when it is gone.
    A leftover claim gets its worktree now: on its branch, or on a fresh claim when the branch is gone."""
    if entry.get("leftover"):
        branch = entry["branch"]
        gone = git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=state["integration_checkout"]) is None
        if gone and not make_branch(state, branch):
            move(entry, "needs-you", "already claimed")
            out.append(f"{ticket['id']} needs you: already claimed")
            return False
        add_worktree(state, entry, ticket["id"])
        del entry["leftover"]
    try:
        counters(entry["worktree"], reset=True)
    except OSError:  # nothing to relaunch into
        move(entry, "needs-you", "worktree missing")
        out.append(f"{ticket['id']} needs you: worktree missing")
        return False
    entry.update(started_at=now(), turns=0, queue_wait_seconds=0)  # caps count this run only
    move(entry, "working")
    launch(state, entry, ticket, out, started=f"relaunched {ticket['id']} in its worktree")
    return True


def startable(state, ledger):
    """Ready tickets this mode may start: all in running, the wave's in once, none otherwise."""
    if state["mode"] == "running": return ready_tickets(state, ledger)
    if state["mode"] == "once": return [t for t in ready_tickets(state, ledger) if t["id"] in state["wave"]]
    return []


def held(state, ledger):
    """Back-pressure: enough tickets wait on the person (needs-you or capped) that nothing new starts."""
    return sum(e["state"] in ("needs-you", "capped") for e in ledger.values()) >= state["stop_if_waiting"]


def free_room(state, ledger):
    """How many tickets may start now: concurrency minus working, within the UTC daily cap; none when held."""
    if held(state, ledger): return 0
    today = now()[:10]
    working = sum(e["state"] == "working" for e in ledger.values())
    started = sum(e["started_at"][:10] == today for e in ledger.values())
    return min(state["concurrency"] - working, state["daily_ticket_cap"] - started)


def start_tickets(state, ledger, out):
    state["held"] = held(state, ledger)
    mode, room = state["mode"], free_room(state, ledger)
    for ticket in startable(state, ledger):
        if room <= 0 or state["mode"] != mode:  # launch() may pause the factory (bypass)
            break
        if ticket["id"] in ledger:  # requeued: its branch and worktree already exist
            if relaunch(state, ledger[ticket["id"]], ticket, out): room -= 1
            continue
        if git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name(state, ticket['id'])}",
               cwd=state["integration_checkout"]) is not None:  # a crashed or foreign claim: show it, once
            ledger[ticket["id"]] = {**new_entry(state, ticket["id"], "needs-you", ""), "reason": LEFTOVER, "leftover": True}
            out.append(f"{ticket['id']} needs you: {LEFTOVER}")
            continue
        entry = claim(state, ledger, ticket)
        if entry is None:
            out.append(f"{ticket['id']} already claimed")
        else:
            room -= 1
            launch(state, entry, ticket, out)


def reconcile(state, ledger, out):
    """Tick step 1: a working ticket whose worker is gone without reporting is interrupted;
    without --allow-bypass, one Orca now shows in bypass (or cannot show) is stopped and the factory pauses."""
    for ticket, entry in ledger.items():
        if entry["state"] != "working" or not entry["worker_handle"]:
            continue
        try: alive = worker_alive(entry["worker_handle"])
        except (ValueError, OSError, subprocess.SubprocessError): continue  # check again next tick
        if not alive:
            move(entry, "interrupted", "worker exited without reporting")
            out.append(f"interrupted {ticket}: worker exited without reporting")
        elif not state["allow_bypass"] and (reason := bypass_problem(entry["worker_handle"])):
            refuse(state, ticket, entry, reason, out)


def cap_verdict(state, entry):
    """(new state, reason) when a working ticket must stop, else None."""
    if not Path(entry["worktree"]).is_dir(): return "needs-you", "worktree missing"
    started = datetime.fromisoformat(entry["started_at"])
    working = (datetime.now(timezone.utc) - started).total_seconds() - entry["queue_wait_seconds"]
    if working > state["max_minutes"] * 60: return "capped", "time cap"
    try: hooks = counters(entry["worktree"])
    except TimeoutError: return None  # the worker holds its counters lock: read the turns next tick
    except ValueError: hooks = {"turns": state["max_turns"], "permission_needed": False}  # fail closed
    entry["turns"] = max(entry["turns"], hooks["turns"])  # only relaunch lowers it
    if hooks["permission_needed"]: return "needs-you", "permission needed"
    if entry["turns"] >= state["max_turns"]: return "capped", "turn cap"
    return None


def enforce_caps(state, ledger, out):
    """Tick step 2: stop a worker that needs a permission or is over its turn or time cap; keep its work."""
    for ticket, entry in ledger.items():
        if entry["state"] != "working":
            continue
        try:
            verdict = cap_verdict(state, entry)
        except (OSError, ValueError, KeyError, TypeError) as error:  # one bad entry never blocks the tick
            out.append(f"caps for {ticket} not checked: {error}")
            continue
        if not verdict:
            continue
        new, reason = verdict
        if not stop(entry): out.append(f"worker {entry['worker_handle']} did not stop; close it in Orca")
        move(entry, new, reason)
        out.append(f"{ticket} {new}: {reason}; {entry['branch']} and its worktree are kept")


def update_cards(ledger, out):
    for ticket, entry in ledger.items():
        card(ticket, entry, out)


def in_flight(ledger): return any(e["state"] in ("working", "approved") for e in ledger.values())


def wave_settled(state, ledger, ticket):
    """Done for this wave: finished or parked (a leftover claim included), or no longer ready."""
    if ticket in ledger: return ledger[ticket]["state"] in ("merged", *REQUEUABLE)
    return ticket not in [t["id"] for t in startable(state, ledger)]


def review_due(state, ledger):
    """The whole feature is done: every started ticket merged (none waiting on the person) and nothing startable."""
    return (state["mode"] == "running" and state["final_review"] == "not-started" and bool(ledger)
            and all(e["state"] == "merged" for e in ledger.values()) and not startable(state, ledger))


def final_review(state, ledger, out):
    """One review agent in the integration checkout once the feature is done, then pause."""
    if not review_due(state, ledger): return
    try:
        handle = launch_worker(state["integration_checkout"],
                               f"Use the ew-factory skill (final review brief) for {state['feature']} on "
                               f"{state['integration_branch']}; write findings to {Path(state['state_dir']) / 'final-review.md'}.")
    except ValueError as error:  # no retry every hour: the person resumes once Orca is fixed
        out.append(f"final review launch failed: {error}")
    else:
        reason = None if state["allow_bypass"] else bypass_problem(handle)
        if reason:  # stays not-started: resume launches it again
            if not stop({"worker_handle": handle}): out.append(f"worker {handle} did not stop; close it in Orca")
            out.append(f"final review not started: {reason}")
        else:
            state["final_review_handle"], state["final_review"] = handle, "dispatched"
            out.append("final review dispatched")
    state["mode"], state["wave_ended_at"] = "paused", now()
    out.append("factory paused")


def update_mode(state, ledger, out):
    """draining -> paused once nothing is in flight; once -> paused once every wave ticket is settled."""
    if state["mode"] == "draining" and not in_flight(ledger):
        state["mode"] = "paused"
        out.append("drained; factory paused")
    elif state["mode"] == "once" and all(wave_settled(state, ledger, t) for t in state["wave"]):
        state["mode"], state["wave_ended_at"] = "paused", now()
        out.append("wave done; factory paused")


def tick(directory):
    with tick_lock(directory) as (state, ledger):
        out = []
        try:
            reconcile(state, ledger, out)
            enforce_caps(state, ledger, out)
            merge_approved(state, ledger, out)
            start_tickets(state, ledger, out)
            final_review(state, ledger, out)
            update_mode(state, ledger, out)
            state["last_tick"] = now()
        finally:  # keep merges and claims made before any failure
            update_cards(ledger, out)
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
    try: orca("repo", "show", "--repo", f"path:{checkout}")
    except ValueError: raise ValueError("This repo is not registered in Orca") from None
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


def uninstall(args):
    """Stop the workers, remove the heartbeat, keep the ledger under a dated name; worktrees and branches stay."""
    directory = state_dir(args.project)
    with tick_lock(directory) as (state, ledger):
        out = []
        stop_all(ledger, out, "stopped by uninstall")
        update_cards(ledger, out)
        try:
            if state["automation_id"]: remove_heartbeat(state["automation_id"])
        except ValueError as error:
            out.append(f"heartbeat not removed ({error}); uninstalling anyway")
        kept = directory / f"ledger-{state['feature']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json"
        save(kept, ledger)  # a new install starts with an empty ledger
        (directory / "ledger.json").unlink(missing_ok=True)
        (directory / "state.json").unlink()
    print("\n".join([*out, f"Factory uninstalled; the ledger is kept as {kept.name}; worktrees and branches are kept"]))


def status_line(state, ledger):
    """One line for `status` and the session-start report; "needs you" is everything waiting on the person."""
    count = lambda *names: sum(e["state"] in names for e in ledger.values())
    return (f"factory: {state['mode']} · {len(ready_tickets(state, ledger))} ready · {count('working')} building"
            f" · {count(*REQUEUABLE)} needs you" + (" · held" if held(state, ledger) else ""))


def status(args):
    directory = state_dir(args.project)
    state, ledger = load(directory)
    print(status_line(state, ledger))
    for ticket, entry in sorted(ledger.items()):
        print(" ".join(filter(None, [ticket, entry["state"], entry["branch"], entry["reason"]])))
    if (directory / "final-review.md").is_file(): print(f"final review: {directory / 'final-review.md'}")
    for line in wave_summary(state, ledger): print(line)
    parked = sum(e["state"] in REQUEUABLE for e in ledger.values())
    if (parked and state["mode"] == "running" and state["final_review"] == "not-started"
            and all(e["state"] in ("merged", *REQUEUABLE) for e in ledger.values()) and not startable(state, ledger)):
        print(f"final review waits on {parked} parked ticket{'s' * (parked != 1)}")


def wave_summary(state, ledger):
    """The last wave (the cycle's tickets, else every ticket): merges, what waits, queue wait, slowed-by lines."""
    wave = {t: ledger[t] for t in state["wave"] or ledger if t in ledger}
    if not wave: return []
    lines = [f"last wave: {sum(e['state'] == 'merged' for e in wave.values())} merged"]
    for name, label in (("needs-you", "needs you"), ("capped", "capped")):
        lines += [f"{label}: {t} ({e['reason']})" for t, e in sorted(wave.items()) if e["state"] == name]
    waited = sum(e["queue_wait_seconds"] for e in wave.values())
    lines.append(f"queue wait: {round(waited / 60)}m" if waited >= 60 else f"queue wait: {round(waited)}s")
    slowed = [f"  {t}: {e['slowed_by']}" for t, e in sorted(wave.items()) if e.get("slowed_by")]
    if slowed: lines += ["slowed by:", *slowed]
    if state.get("wave_ended_at"): lines.append(f"wave ended: {state['wave_ended_at']}")
    return lines


def gate(args):
    directory, marker = state_dir(args.project), ticket_marker(args.project)
    ticket = args.for_ticket or (read_json(marker)["ticket"] if marker.is_file() else None)
    passed, output, waited, ran = queued_gate(directory, find_project(args.project))
    print(output, end="")
    if ticket:
        with tick_lock(directory) as (state, ledger):  # short: the gate itself ran outside the lock
            if ticket in ledger:
                record_gate(ledger[ticket], waited, ran)
                save(directory / "ledger.json", ledger)
    return 0 if passed else 1


def report(args):
    if args.result not in ("approved", "blocked"): raise ValueError("report needs <ticket> approved|blocked")
    directory = state_dir(args.project)
    with tick_lock(directory) as (state, ledger):
        entry = ledger.get(args.ticket)
        if not entry or entry["state"] != "working": raise ValueError(f"Ticket {args.ticket} is not working")
        entry["slowed_by"] = args.slowed_by
        if args.result == "approved": move(entry, "approved")
        else: move(entry, "needs-you", args.reason or "blocked")
        save(directory / "ledger.json", ledger)
    spawn_tick(directory) if args.detach else tick(directory)


def spawn_tick(directory):
    """Start tick detached from the caller (an agent's tool call has a timeout); its output goes to tick.log."""
    checkout = read_json(Path(directory) / "state.json")["integration_checkout"]
    with open(Path(directory) / "tick.log", "a") as log:
        subprocess.Popen([sys.executable, "-B", str(ROOT / "workflow.py"), "factory", "tick", "--project", checkout],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)


def approve(args):
    directory = state_dir(args.project)
    with tick_lock(directory) as (state, ledger):
        entry = ledger.get(args.ticket)
        if not entry or entry["state"] != "needs-you":
            raise ValueError(f"Ticket {args.ticket} is not waiting for you")
        if next((s["state"] for s in reversed(entry["history"]) if s["state"] != "needs-you"), None) != "approved":
            raise ValueError(f"Ticket {args.ticket} was not approved by its worker; requeue it instead")
        out = []
        try:
            merged = land(state, args.ticket, entry, out)
        finally:
            update_cards(ledger, out)
            save(directory / "ledger.json", ledger)
    print("\n".join(out))
    return 0 if merged else 1


def requeue(args):
    directory = state_dir(args.project)
    with tick_lock(directory) as (_, ledger):
        entry = ledger.get(args.ticket)
        if not entry or entry["state"] not in REQUEUABLE:
            raise ValueError(f"Ticket {args.ticket} cannot be requeued (only {', '.join(REQUEUABLE)})")
        move(entry, "ready")
        save(directory / "ledger.json", ledger)
    print(f"requeued {args.ticket}; the next tick relaunches it on {entry['branch']}")


def precheck(args):
    state, ledger = load(state_dir(args.project))
    if any(e["state"] == "working" for e in ledger.values()): return 0  # supervise them in any mode
    work = (in_flight(ledger) or (free_room(state, ledger) > 0 and startable(state, ledger))
            or review_due(state, ledger))
    return 0 if state["mode"] != "paused" and work else 1


def set_setting(args):
    name, value = args.ticket, args.result
    if name not in SETTINGS: raise ValueError(f"set needs one of: {', '.join(SETTINGS)}")
    if not re.fullmatch(r"[1-9][0-9]*", value or ""): raise ValueError(f"{name} needs a positive integer")
    directory = state_dir(args.project)
    with tick_lock(directory) as (state, _):
        state[name] = int(value)
        save(directory / "state.json", state)
    print(f"{name} = {value}")


def set_mode(directory, mode):
    with tick_lock(directory) as (state, ledger):
        if mode == "draining" and not in_flight(ledger): mode = "paused"
        if mode in ("once", "running"):  # running's wave is every ticket, so its list is empty
            state["wave"] = [t["id"] for t in ready_tickets(state, ledger)] if mode == "once" else []
            state.pop("wave_ended_at", None)
        state["mode"] = mode
        save(directory / "state.json", state)
    return mode


def pause(args):
    directory = state_dir(args.project)
    if not args.now:
        print(f"factory {set_mode(directory, 'draining')}")
        return
    with tick_lock(directory) as (state, ledger):
        out = []
        stop_all(ledger, out, "stopped by pause --now")
        update_cards(ledger, out)
        state["mode"] = "paused"
        save(directory / "ledger.json", ledger)
        save(directory / "state.json", state)
    print("\n".join([*out, "factory paused"]))


def stop_all(ledger, out, reason):
    """Stop every working worker; its ticket is interrupted and keeps its branch and worktree."""
    for ticket, entry in ledger.items():
        if entry["state"] != "working":
            continue
        if not stop(entry): out.append(f"worker {entry['worker_handle']} did not stop; close it in Orca")
        move(entry, "interrupted", reason)
        out.append(f"interrupted {ticket}; {entry['branch']} and its worktree are kept")


def go(args, mode):
    """resume (running) or cycle (once); a manual Orca automation run ignores the precheck, so tick directly."""
    directory = state_dir(args.project)
    set_mode(directory, mode)
    tick(directory)


def add_parser(sub):
    f = sub.add_parser("factory", help="Unattended per-ticket builds through Orca")
    f.add_argument("action", choices=("install", "uninstall", "status", "set", "tick", "gate", "report", "precheck",
                                      "pause", "resume", "cycle", "approve", "requeue"))
    f.add_argument("ticket", nargs="?", help="the ticket id, or set's setting")
    f.add_argument("result", nargs="?", help="report: approved|blocked; set: the value")
    f.add_argument("--project", default="."); f.add_argument("--feature")
    f.add_argument("--integration-branch", help="Default: the branch checked out in the project")
    f.add_argument("--paused", action="store_true"); f.add_argument("--allow-bypass", action="store_true")
    f.add_argument("--slowed-by"); f.add_argument("--reason")
    f.add_argument("--now", action="store_true", help="pause: stop every worker now (keeps their worktrees)")
    f.add_argument("--ticket", dest="for_ticket", help="gate: record queue wait and run time on this ticket")
    f.add_argument("--detach", action="store_true", help="tick, report: run the tick in the background")


def run(args):
    if in_ticket_worktree(args.project):  # a worker runs only gate, report and status
        if args.action in PERSON_ONLY: raise ValueError("Run this from the integration checkout, not a ticket worktree")
        if args.action == "report" and read_regular(ticket_marker(args.project)).get("ticket") != args.ticket:
            raise ValueError("A ticket worktree reports only its own ticket")
    actions = {"install": install, "uninstall": uninstall, "status": status, "set": set_setting, "gate": gate,
               "report": report, "precheck": precheck,
               "tick": lambda a: (spawn_tick if a.detach else tick)(state_dir(a.project)),
               "pause": pause, "resume": lambda a: go(a, "running"), "cycle": lambda a: go(a, "once"),
               "approve": approve, "requeue": requeue}
    return actions[args.action](args) or 0
