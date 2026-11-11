"""Factory mode: build a feature's tickets unattended, one Orca or AO worker per ticket."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import plistlib
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
PERSON_ONLY = ("install", "uninstall", "set", "pause", "resume", "cycle", "approve", "requeue", "queue")
CLIMB = "climb"  # the ledger id of the feature's hill-climb, run after every ticket merged
REVIEW = "review"  # the ledger id of the feature's final review, run last; it merges nothing
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
    if state.get("runner") == "ao": return register_launchd(state)
    checkout = state["integration_checkout"]
    result = orca("automations", "create", "--name", f"factory {state['feature']}", "--trigger", "hourly",
                  "--provider", "claude", "--workspace", f"path:{checkout}",
                  "--precheck", workflow_command("precheck", "--project", checkout),
                  "--extra-agent-args=--model sonnet", "--enabled", "--prompt",
                  f"Run `{workflow_command('tick', '--detach', '--project', checkout)}`, report its output, do nothing else.")
    return (result.get("automation") or {}).get("id") or result.get("id")


def remove_heartbeat(automation_id):
    if automation_id.startswith(HEARTBEAT_PREFIX): return remove_launchd(automation_id)
    orca("automations", "remove", automation_id)


def launch_worker(worktree, prompt):
    result = orca("agent", "launch", "--agent", "claude", "--worktree", f"path:{worktree}",
                  "--surface", "terminal", "--prompt", prompt)
    return result.get("launch", result)["outcome"]["handle"]  # Orca replies {outcome}; older builds wrapped it in launch


def worker_alive(handle):
    if is_ao(handle): return ao_alive(handle)
    return bool(orca("terminal", "show", "--terminal", handle).get("terminal", {}).get("connected"))


def stop_worker(handle):
    if is_ao(handle):
        ao("session", "kill", handle[3:], reply=False)
        return not worker_alive(handle)
    orca("terminal", "close", "--terminal", handle, check=False)  # reports ok:false even when it worked
    return not worker_alive(handle)


# --- AO adapter: the only code that calls the ao CLI or launchctl -----------------
# AO handles are "ao:<session id>"; Orca handles are bare terminal handles, so old ledgers keep working.

AO_ENV_DROP = ("AO_SESSION_ID", "AO_PROJECT_ID", "AO_ISSUE_ID")  # act as the factory, not the calling session
AO_BYPASS_REASON = ("AO runs this project's agents in bypass-permissions mode; change the project's "
                    "permission mode or reinstall with --allow-bypass")
HEARTBEAT_PREFIX = "com.engineering-workflow.factory."


def is_ao(handle): return isinstance(handle, str) and handle.startswith("ao:")


def ao_executable():
    name = os.environ.get("AO_CLI_COMMAND") or "ao"
    path = shutil.which(name)
    if not path: raise ValueError(f"AO CLI not found ({name})")
    return path


def ao(*args, reply=True):
    """Run the ao CLI; its JSON reply when `reply`, else its text. Raises ValueError on failure."""
    env = {k: v for k, v in os.environ.items() if k not in AO_ENV_DROP}
    result = subprocess.run([ao_executable(), *args, *(["--json"] if reply else [])], text=True,
                            capture_output=True, timeout=120, env=env)
    if result.returncode != 0:
        raise ValueError(f"ao {' '.join(args[:2])} failed: {(result.stderr or result.stdout).strip() or 'no detail'}")
    if not reply: return result.stdout
    try: data = json.loads(result.stdout)
    except json.JSONDecodeError: data = None
    if not isinstance(data, dict): raise ValueError(f"ao {' '.join(args[:2])} failed: unreadable reply")
    return data


def ao_project(checkout):
    """The id of the AO project registered at this checkout."""
    here = Path(checkout).resolve()
    for project in ao("project", "ls").get("projects", []):
        path = ao("project", "get", project["id"]).get("project", {}).get("path")
        if path and Path(path).resolve() == here: return project["id"]
    raise ValueError("This repo is not registered in AO")


def ao_spawn(state, name, branch=None, prompt=None, kind="worker"):
    args = ["spawn", "--project", state["ao_project"], "--kind", kind, "--harness", "claude-code", "--name", name]
    if branch: args += ["--branch", branch]
    if prompt: args += ["--prompt", prompt]
    found = re.search(r"spawned session (\S+)", ao(*args, reply=False))
    if not found: raise ValueError("ao spawn failed: no session id in its reply")
    return "ao:" + found.group(1)


def ao_send(handle, message): ao("send", "--session", handle[3:], "--message", message, reply=False)


def branch_worktree(checkout, branch):
    path = None
    for line in (git("worktree", "list", "--porcelain", cwd=checkout) or "").splitlines():
        if line.startswith("worktree "): path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}": return path
    return None


def ao_alive(handle):
    return not ao("session", "get", handle[3:]).get("session", {}).get("isTerminated", True)


def ao_bypass(handle):
    """Why this AO worker must not run without --allow-bypass, or None; fails closed like the Orca check."""
    try:
        project = ao("session", "get", handle[3:])["session"]["projectId"]
        config = ao("project", "get", project)["project"].get("config") or {}
        modes = {(config.get("agentConfig") or {}).get("permissions"),
                 ((config.get("worker") or {}).get("agentConfig") or {}).get("permissions")}
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError, AttributeError):
        return "could not confirm AO's permission mode"
    return AO_BYPASS_REASON if "bypass-permissions" in modes else None


def launchctl(*args):
    path = shutil.which("launchctl")
    if not path: raise ValueError("launchctl not found; the ao runner's heartbeat needs macOS")
    result = subprocess.run([path, *args], text=True, capture_output=True, timeout=60)
    if result.returncode != 0: raise ValueError(f"launchctl {args[0]} failed: {result.stderr.strip() or 'no detail'}")


def plist_path(label): return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def register_launchd(state):
    """An hourly launchd job: precheck, then tick. Plain Python, no agent session; returns its label."""
    checkout, label = state["integration_checkout"], f"{HEARTBEAT_PREFIX}{state['ao_project']}.{state['feature']}"
    tools = dict.fromkeys(str(Path(p).parent) for p in (ao_executable(), shutil.which("git") or "/usr/bin/git"))
    env = {"PATH": os.pathsep.join([*tools, "/usr/bin", "/bin"])}
    if os.environ.get("AO_DATA_DIR"): env["AO_DATA_DIR"] = os.environ["AO_DATA_DIR"]
    log = str(Path(state["state_dir"]) / "heartbeat.log")
    script = f"{workflow_command('precheck', '--project', checkout)} && {workflow_command('tick', '--project', checkout)}"
    path = plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": ["/bin/sh", "-c", script],
                                     "StartInterval": 3600, "EnvironmentVariables": env,
                                     "StandardOutPath": log, "StandardErrorPath": log}))
    launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
    return label


def remove_launchd(label):
    try: launchctl("bootout", f"gui/{os.getuid()}/{label}")
    finally: plist_path(label).unlink(missing_ok=True)


def close_hint(handle):
    return f"kill it with `ao session kill {handle[3:]}`" if is_ao(handle) else "close it in Orca"


def ensure_relay(state):
    """The project's live AO orchestrator, told it relays this factory; one is spawned when there is none."""
    for row in ao("orchestrator", "ls").get("data", []):
        if row.get("projectId") == state["ao_project"] and not row.get("isTerminated"):
            handle = "ao:" + row["id"]
            ao_send(handle, relay_prompt(state))
            return handle
    state["relay_spawned"] = True
    return ao_spawn(state, f"factory {state['feature']}", prompt=relay_prompt(state), kind="orchestrator")


def relay(state, message):
    if not ao_alive(state["relay_handle"]): state["relay_handle"] = ensure_relay(state)
    ao_send(state["relay_handle"], message)


def ao_attach(state, entry, ticket):
    """Give the entry a live AO session in a worktree on its claim branch, and mark that worktree.
    Reuses a live session, restores a dead one, spawns one when it has none; ValueError when it cannot."""
    handle = entry.get("worker_handle")
    if is_ao(handle):
        if not ao_alive(handle): ao("session", "restore", handle[3:], reply=False)
    else:
        entry["worker_handle"] = ao_spawn(state, f"factory {state['feature']} {ticket}", entry["branch"])
    worktree = branch_worktree(state["integration_checkout"], entry["branch"])
    if not worktree: raise ValueError(f"AO made no worktree on {entry['branch']}")
    entry["worktree"] = worktree
    save(ticket_marker(worktree), {"ticket": ticket, "state_dir": state["state_dir"]})


def relay_prompt(state):
    checkout = state["integration_checkout"]
    return (f"You relay the engineering-workflow factory for feature {state['feature']} in {checkout}. "
            "Messages that start with 'Ticket NN NEEDS YOU' or 'NEEDS YOU' come from the factory; reports from "
            "factory workers may also arrive. For each one that needs the person, tell them in one or two plain "
            "sentences what is waiting and the exact next command, run from that checkout: "
            f"`{workflow_command('status', '--project', checkout)}`, then `factory approve NN` or "
            "`factory requeue NN`. Messages that start with 'BUILT' are tickets of a queued feature the person "
            "asked to hear about: pass each on in one plain sentence. Ignore other routine progress. "
            "Never edit files, merge, push, open PRs or run "
            "factory commands yourself. Reply OK to this message and wait.")


def ping(state, message, out):
    """Tell the person something that needs no answer: the integration checkout's Orca card (unread dot),
    or the AO relay. A failure prints a line; the ping is not retried."""
    try:
        if state.get("runner") == "ao": relay(state, message)
        else: set_card(state["integration_checkout"], "in-progress", message)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        out.append(f"ping not sent: {error}")


def stop(entry):
    """Stop the entry's worker; False when Orca cannot confirm it stopped."""
    try: return not entry["worker_handle"] or stop_worker(entry["worker_handle"])
    except (ValueError, OSError, subprocess.SubprocessError): return False  # what the adapter can raise


def bypass_problem(handle):
    """Why this agent must not run without --allow-bypass, or None; a terminal Orca cannot show fails closed."""
    if is_ao(handle): return ao_bypass(handle)
    try: text = json.dumps(orca("terminal", "read", "--terminal", handle, "--limit", "40")).lower()
    except (ValueError, OSError, subprocess.SubprocessError): return "could not confirm Orca's permission mode"
    return BYPASS_REASON if any(word in text for word in BYPASS_WORDS) else None


# --- State, ledger, tickets -------------------------------------------------------

def ticket_marker(project):
    return find_project(project) / STATE / "factory-ticket.json"


def in_ticket_worktree(path):
    """Inside a ticket worktree, by its marker, by where it lies, or (AO) by its claim branch;
    a worker can delete its marker."""
    parts = Path(path).resolve().parts
    return (ticket_marker(path).is_file() or any(parts[i:i + 3] == WORKTREES for i in range(len(parts)))
            or ao_ticket_branch(path))


def ao_ticket_branch(path):
    """A linked worktree on a claim branch of the AO factory installed in its main checkout."""
    found = git("rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir", "--abbrev-ref", "HEAD", cwd=path)
    lines = (found or "").splitlines()
    if len(lines) != 3 or lines[0] == lines[1] or not lines[2].startswith("factory/"): return False
    try: state = read_regular(Path(lines[1]).parent / STATE / "factory" / "state.json")
    except (OSError, ValueError): return False
    return (state.get("runner") == "ao" and isinstance(state.get("feature"), str)
            and re.fullmatch(re.escape(f"factory/{state['feature']}-") + r"(?:[0-9]+|climb|review)", lines[2]) is not None)


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
            if time.monotonic() > deadline: raise TimeoutError("factory lock is busy")
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


def header_fields(path):
    fields = {}
    for key, value in re.findall(r"^\**([A-Z][A-Za-z ]*?):\**[ \t]*(\S.*?)[ \t]*$", path.read_text(), re.M):
        fields.setdefault(key, value)  # the header's line wins over later body lines
    return fields


def radius_of(fields):
    radius = fields.get("Blast radius")
    return radius if radius in ("low", "medium") else "high"


def tickets(checkout, feature):
    found = []
    for path in sorted((Path(checkout) / ".scratch" / feature / "issues").glob("[0-9][0-9]-*.md")):
        fields = header_fields(path)
        found.append({"id": path.name[:2], "path": path, "status": fields.get("Status", ""),
                      "radius": radius_of(fields),
                      "blocked_by": re.findall(r"(?:^|,)\s*(\d\d)\b", fields.get("Blocked by", ""))})
    return found


def approved_climb(checkout, feature):
    """(path, header fields) of the feature's climb file when it is approved (ready-for-agent), else None."""
    path = Path(checkout) / ".scratch" / feature / "climb.md"
    fields = header_fields(path) if path.is_file() else {}
    return (path, fields) if fields.get("Status") == "ready-for-agent" else None


def climb_spec(fields):
    """(metric command, lower is better, harness paths) from a climb file's header; ValueError says what it lacks."""
    metric = re.match(r"`([^`]+)`(.*)", fields.get("Metric", ""))
    if not metric: raise ValueError("climb.md needs **Metric:** `command` (lower|higher is better)")
    if "Harness" not in fields:  # the worker may change anything else, so leaving it out must be a choice
        raise ValueError("climb.md needs **Harness:** the paths that produce the score, or none")
    harness = [p.strip(" `") for p in fields["Harness"].split(",") if p.strip(" `").lower() not in ("", "none")]
    note, target = metric.group(2).lower(), fields.get("Target", "").strip()
    for lower, higher in (("lower" in note, "higher" in note),  # the Metric line's note, else the Target's operator
                          (target.startswith(("<", "≤")), target.startswith((">", "≥")))):
        if lower != higher: return metric.group(1), lower, harness
    raise ValueError("climb.md must say whether lower or higher is better, on its Metric or Target line")


def check_climb(checkout, feature):
    """Refuse (ValueError) an approved climb file the factory could not score."""
    found = approved_climb(checkout, feature)
    if found: climb_spec(found[1])


def climb_ticket(state):
    """The feature's approved climb file as a ticket (read on the integration branch), or None."""
    found = approved_climb(state["integration_checkout"], state["feature"])
    if not found: return None
    path, fields = found
    return {"id": CLIMB, "path": path, "status": fields["Status"], "radius": radius_of(fields), "blocked_by": []}


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


def card(state, ticket, entry, out):
    """Bring the entry's Orca card (AO: the relay's NEEDS YOU message) up to date; a failure prints a line
    and is retried next time."""
    status = CARDS.get(entry["state"])
    label = "" if entry["state"] == "needs-you" else f"{entry['state']}: "
    comment = f"NEEDS YOU: {label}{entry['reason']}" if entry["state"] in REQUEUABLE else None
    if not status or entry.get("card") == [status, comment]:
        return
    ao_runner = state.get("runner") == "ao"
    if not ao_runner and not Path(entry["worktree"]).exists():  # Orca's card went with the worktree; never retry
        entry["card"] = [status, comment]
        return
    try:
        if ao_runner:
            if is_ao(entry.get("worker_handle")):  # the board card: its title says NEEDS YOU while it waits
                title = f"factory {state['feature']} {ticket}"
                ao("session", "rename", entry["worker_handle"][3:], f"NEEDS YOU: {title}" if comment else title,
                   reply=False)
            if comment: relay(state, f"Ticket {ticket} {comment} (branch {entry['branch']})")
        else: set_card(entry["worktree"], status, comment)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        out.append(f"card for {ticket} not updated: {error}")
        return
    entry["card"] = [status, comment]


def file_report(entry, result, reason, slowed_by):
    entry["slowed_by"], entry["reported"] = slowed_by, result
    if result == "approved": move(entry, "approved")
    else: move(entry, "needs-you", reason or "blocked")


def report_file(directory, ticket): return Path(directory) / "reports" / f"{ticket}.json"


def take_reports(directory, ledger):
    """File the reports workers left while a tick held the lock. Workers can write these files:
    one that is unreadable, or not for a working ticket, is dropped."""
    paths = sorted((Path(directory) / "reports").glob("*.json"))
    for path in paths:
        try:
            data, entry = read_regular(path), ledger.get(path.stem)
            words = (data["result"], data.get("reason"), data.get("slowed_by"))
            if (entry and entry["state"] == "working" and words[0] in ("approved", "blocked")
                    and all(isinstance(w, (str, type(None))) for w in words)):
                file_report(entry, *words)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    if paths: save(Path(directory) / "ledger.json", ledger)  # before the files go, so a crash cannot lose one
    for path in paths:
        try: path.unlink(missing_ok=True)
        except OSError: shutil.rmtree(path, ignore_errors=True)  # a directory planted there must not wedge the lock


@contextmanager
def tick_lock(directory, wait=None):
    """Hold the factory's lock; `wait` seconds at most (TimeoutError), else for as long as it takes."""
    if not (directory / "state.json").is_file(): raise ValueError("No factory installed for this project")
    with open(directory / "tick.lock", "a") as handle:
        if wait is None: fcntl.flock(handle, fcntl.LOCK_EX)
        else: lock_within(handle, fcntl.LOCK_EX, wait)
        state, ledger = load(directory)  # read under the lock
        take_reports(directory, ledger)
        yield state, ledger


# --- Gate -------------------------------------------------------------------------

def run_bash(args, cwd, minutes):
    """Run bash in cwd, in its own process group; (stdout, stderr, exit code), killed after `minutes` (code None)."""
    bash = subprocess.Popen(["bash", *args], cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    try:
        return (*bash.communicate(timeout=minutes * 60), bash.returncode)
    except subprocess.TimeoutExpired:
        os.killpg(bash.pid, signal.SIGKILL)
        return (*bash.communicate(), None)


def run_gate(cwd, script, minutes):
    """Run `script` in cwd, failed after `minutes`."""
    if not script.is_file(): return False, f"GATES: FAIL missing {GATES}"
    stdout, stderr, code = run_bash([str(script)], cwd, minutes)
    if code is None: stdout += "GATES: FAIL timeout\n"
    lines = stdout.splitlines()
    return bool(lines) and lines[-1] == "GATES: PASS", stdout + stderr


def run_metric(cwd, command, minutes):
    """Run a climb's metric command; (it exited 0, its stdout)."""
    stdout, _, code = run_bash(["-c", command], cwd, minutes)
    return code == 0, stdout


def queued_gate(directory, cwd, script=None, run=run_gate):
    """Run the gate (default: cwd's own script) inside one of build_slots slot locks;
    return (passed, output, waited, ran) seconds. `run=run_metric` runs a metric command in a slot instead."""
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
                passed, output = run(cwd, script, state["max_minutes"])
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

def measure(state, command, commit):
    """The climb's score at `commit`: the metric command run in a build slot, in a throwaway checkout (the worker
    can write its own tree and the ledger). The one number on the last line it prints; None when it fails,
    times out or prints anything else.
    ponytail: one run; repeat and take the median if a noisy metric holds good climbs (a hold costs one approve)."""
    checkout, tree = state["integration_checkout"], Path(state["state_dir"]) / "measure"
    try:
        git("worktree", "remove", "--force", str(tree), cwd=checkout, timeout=300)  # left by a tick that died
        if git("worktree", "add", "--detach", str(tree), commit, cwd=checkout, timeout=300) is None: return None
        ran, stdout, *_ = queued_gate(state["state_dir"], tree, command, run_metric)
        git("worktree", "remove", "--force", str(tree), cwd=checkout, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = stdout.strip().splitlines()
    numbers = re.findall(r"-?\d+(?:\.\d+)?", lines[-1]) if ran and lines else []
    return float(numbers[0]) if len(numbers) == 1 else None


def current_climb(state):
    """climb_spec of the approved climb file on the integration branch; ValueError when it cannot score a climb."""
    found = approved_climb(state["integration_checkout"], state["feature"])
    return climb_spec(found[1] if found else {})


def climb_baseline(state, entry):
    """Before a climb's worker starts: check the factory can score it at the integration tip. A needs-you reason
    when the climb file or its command cannot; a requeue then tries again at the new tip."""
    if "baseline" in entry: return None  # checked when this climb first started
    try:
        command = current_climb(state)[0]
        # A climb requeued after a fix on the integration branch starts from that fix; a no-op otherwise.
        git("merge", "--ff-only", state["integration_branch"], cwd=entry["worktree"], timeout=300)
    except (ValueError, subprocess.TimeoutExpired) as error:
        return str(error)
    score = measure(state, command, state["integration_branch"])
    if score is None: return f"climb metric gave no number on {state['integration_branch']}"
    entry["baseline"] = score  # for `status`; climb_hold measures again and never reads it
    return None


def climb_hold(state, entry):
    """A needs-you reason when the climb touched its harness, or the factory's own runs of the metric (where
    the climb branched off, then at its tip) show no gain; never the worker's word or the ledger's."""
    checkout, shown = state["integration_checkout"], lambda score: "no number" if score is None else f"{score:g}"
    try: command, lower, harness = current_climb(state)
    except ValueError as error: return str(error)
    base = git("merge-base", state["integration_branch"], entry["branch"], cwd=checkout)
    changed = git("diff", "--name-only", "--no-renames", base, entry["branch"], "--", *harness, cwd=checkout) if base and harness else ""
    if not base or changed is None: return "could not compare the climb with the integration branch"
    if changed: return f"climb changed its harness: {', '.join(changed.splitlines()[:3])}"
    entry["baseline"], entry["final"] = before, after = measure(state, command, base), measure(state, command, entry["branch"])
    if None not in (before, after) and (after < before if lower else after > before): return None
    return (f"climb did not improve its metric: {shown(before)} -> {shown(after)} "
            f"({'lower' if lower else 'higher'} is better)")


def gate_ticket(state, entry):
    """Return a needs-you reason, or None when the ticket branch, brought up to the integration tip, is clean
    and passes its gate. The tree that is gated is then the tree that merges: tickets that each pass alone
    cannot break the integration branch together."""
    worktree, target = entry["worktree"], state["integration_branch"]
    if git("status", "--porcelain", cwd=worktree) != "":
        return "uncommitted changes in the worktree"
    if git("branch", "--show-current", cwd=worktree) != entry["branch"]:  # the gate would test a tree that never merges
        return f"worktree is not on {entry['branch']}"
    try: joined = git("merge", "--no-edit", target, cwd=worktree, timeout=300)
    except subprocess.TimeoutExpired: joined = None
    if joined is None:  # the conflict merge_ticket would hit, found before the gate is paid for
        conflict = git("diff", "--name-only", "--diff-filter=U", cwd=worktree)
        git("merge", "--abort", cwd=worktree)
        return "merge conflict" if conflict else f"could not merge {target} into the ticket branch"
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
    if git("merge-base", "--is-ancestor", state["integration_branch"], entry["branch"], cwd=checkout) is None:
        return f"{state['integration_branch']} moved during the gate"  # approve or requeue gates the new tip
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
    if entry["branch"] != branch_name(state, ticket): return False
    if state.get("runner") == "ao":
        actual = branch_worktree(state["integration_checkout"], entry["branch"])
        return (actual is not None and Path(actual).resolve() == worktree
                and worktree != Path(state["integration_checkout"]).resolve())
    return worktree == Path(new_entry(state, ticket, "", "")["worktree"]).resolve()


def land(state, ticket, entry, out, hold=None):
    """Gate, then merge; a failure or a reason from `hold()` leaves the ticket in needs-you. Returns True when merged."""
    review = ticket == REVIEW  # nothing to gate or merge: its findings are a file in the state dir
    reason = ((None if valid(state, ticket, entry) else "ledger entry failed validation")
              or (None if review else gate_ticket(state, entry) or (hold and hold()) or merge_ticket(state, entry)))
    if reason:
        move(entry, "needs-you", reason)
        out.append(f"{ticket} needs you: {reason}")
        return False
    move(entry, "merged")
    card(state, ticket, entry, out)  # before the worktree, and with it the Orca card, goes away
    if state.get("runner") == "ao" and not stop(entry):
        out.append(f"worker {entry['worker_handle']} did not stop; {close_hint(entry['worker_handle'])}")
    try: git("worktree", "remove", "--force", entry["worktree"], cwd=state["integration_checkout"], timeout=300)
    except subprocess.TimeoutExpired: out.append(f"worktree for {ticket} not removed: git timed out")
    if state.get("runner") == "ao" or review:  # merged work lives on the integration branch; drop the local claim branch
        git("branch", "-D" if review else "-d", entry["branch"], cwd=state["integration_checkout"])
    out.append(f"final review done: {review_file(state)}" if review else f"merged {ticket} into {state['integration_branch']}")
    if state.get("ping_merges") and not review:  # a queued feature: the person asked to hear about each ticket it builds
        ping(state, f"BUILT: {state['feature']} {ticket} merged into {state['integration_branch']}", out)
    return True


def merge_approved(state, ledger, out):
    for ticket, entry in ledger.items():
        if entry["state"] == "approved" and ticket == REVIEW:  # the reviewer found nothing that needs the person
            if land(state, ticket, entry, out):
                ping(state, f"BUILT: final review of {state['feature']} is in, nothing needs you: {review_file(state)}", out)
        elif entry["state"] == "approved":
            # ticket files are only trustworthy on the integration branch
            found = (climb_ticket(state) if ticket == CLIMB
                     else next((t for t in tickets(integration_checkout(state), state["feature"]) if t["id"] == ticket), None))
            radius = found["radius"] if found else "high"
            land(state, ticket, entry, out, lambda: (  # run once the entry is validated and its gate has passed
                control_files(state, entry) or (climb_hold(state, entry) if ticket == CLIMB else None)
                or ("high blast radius: waiting for approval" if radius == "high" else None)))


def worker_brief(state, ticket, worktree):
    path = Path(worktree) / Path(ticket["path"]).relative_to(state["integration_checkout"])
    kind = ("climb brief). Climb file" if ticket["id"] == CLIMB else "worker brief). Ticket")
    return (f"Use the ew-factory skill ({kind}: {path}. Ticket id: {ticket['id']}. "
            f"Gate: {workflow_command('gate', '--ticket', ticket['id'], '--project', worktree)}. "
            f"Report: {workflow_command('report', ticket['id'], 'approved', '--detach', '--project', worktree)}"
            f' --slowed-by "<one line>" (blocked instead of approved, plus --reason "<one line>", if stuck).')


def review_brief(state, entry):
    """The reviewer's prompt, pinned to the commit its worktree is at: the next feature may merge on top meanwhile."""
    worktree = entry["worktree"]
    try:  # a requeued review sees the fixes; its branch is throwaway, so whatever the last reviewer left goes
        tip = (git("reset", "--hard", state["integration_branch"], cwd=worktree, timeout=300) is not None
               and git("rev-parse", "HEAD", cwd=worktree))
    except subprocess.TimeoutExpired: tip = None
    if not tip: raise ValueError(f"could not bring the review worktree to {state['integration_branch']}")
    return (f"Use the ew-factory skill (final review brief) for {state['feature']} on {state['integration_branch']} "
            f"up to commit {tip}; write findings to {review_file(state)}. "
            f"Gate: {workflow_command('gate', '--ticket', REVIEW, '--project', worktree)}. "
            f"Report: {workflow_command('report', REVIEW, 'approved', '--detach', '--project', worktree)}"
            f' --slowed-by "<one line>" (blocked instead of approved, plus --reason "<one line>", '
            "when a finding needs the person).")


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
    if state.get("runner") != "ao": add_worktree(state, entry, ticket["id"])  # AO makes it in launch()
    return entry


def refuse(state, ticket, entry, reason, out):
    """Stop a worker Orca runs in bypass (or cannot show us), park its ticket and pause the factory."""
    stopped = stop(entry)
    move(entry, "needs-you", reason)
    state["mode"] = "paused"
    out.append(f"{ticket} needs you: {reason}; factory paused")
    if not stopped: out.append(f"worker {entry['worker_handle']} did not stop; {close_hint(entry['worker_handle'])}")


def launch(state, entry, ticket, out, started=None):
    """Launch the worker; park the ticket on launch failure or an unallowed bypass launch."""
    try:
        ao_runner = state.get("runner") == "ao"
        if ao_runner: ao_attach(state, entry, ticket["id"])  # AO makes the worktree; its session waits for the brief
        reason = climb_baseline(state, entry) if ticket["id"] == CLIMB else None
        if reason:
            move(entry, "needs-you", reason)
            out.append(f"{ticket['id']} needs you: {reason}")
            return
        brief = review_brief(state, entry) if ticket["id"] == REVIEW else worker_brief(state, ticket, entry["worktree"])
        if ao_runner: ao_send(entry["worker_handle"], brief)
        else: entry["worker_handle"] = launch_worker(entry["worktree"], brief)
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
        if state.get("runner") != "ao": add_worktree(state, entry, ticket["id"])
        del entry["leftover"]
    try:
        if state.get("runner") == "ao": ao_attach(state, entry, ticket["id"])  # restore its session, or a new one
        counters(entry["worktree"], reset=True)
    except (OSError, ValueError):  # nothing to relaunch into
        move(entry, "needs-you", "worktree missing")
        out.append(f"{ticket['id']} needs you: worktree missing")
        return False
    entry.update(started_at=now(), turns=0, queue_wait_seconds=0, reported=None)  # caps count this run only
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


def started_today(state, ledger):
    """Tickets started today (UTC), with those of the features this factory finished earlier today."""
    today = now()[:10]
    return ((state.get("carried_starts") or {}).get(today, 0)
            + sum(e["started_at"][:10] == today for t, e in ledger.items() if t != REVIEW))


def free_room(state, ledger):
    """How many tickets may start now: concurrency minus working, within the UTC daily cap; none when held."""
    if held(state, ledger): return 0
    working = sum(e["state"] == "working" for e in ledger.values())
    return min(state["concurrency"] - working, state["daily_ticket_cap"] - started_today(state, ledger))


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
        if (entry["state"] != "working" or not entry["worker_handle"]
                or report_file(state["state_dir"], ticket).is_file()):  # reported since this tick began: file it next tick
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
        if not stop(entry): out.append(f"worker {entry['worker_handle']} did not stop; {close_hint(entry['worker_handle'])}")
        move(entry, new, reason)
        out.append(f"{ticket} {new}: {reason}; {entry['branch']} and its worktree are kept")


def update_cards(state, ledger, out):
    for ticket, entry in ledger.items():
        card(state, ticket, entry, out)


def in_flight(ledger): return any(e["state"] in ("working", "approved") for e in ledger.values())


def wave_settled(state, ledger, ticket):
    """Done for this wave: finished or parked (a leftover claim included), or no longer ready."""
    if ticket in ledger: return ledger[ticket]["state"] in ("merged", *REQUEUABLE)
    return ticket not in [t["id"] for t in startable(state, ledger)]


def built(state, ledger):
    """Every started ticket (not the climb or the review) merged, and nothing startable."""
    started = [e for t, e in ledger.items() if t not in (CLIMB, REVIEW)]
    return (state["mode"] == "running" and state["final_review"] == "not-started" and bool(started)
            and all(e["state"] == "merged" for e in started) and not startable(state, ledger))


def climb_due(state, ledger):
    """Every ticket merged and the feature has an approved climb file it has not run yet (or one requeued)."""
    return (built(state, ledger) and ledger.get(CLIMB, {"state": "ready"})["state"] == "ready"
            and climb_ticket(state) is not None)


def start_extra(state, ledger, ticket, out, started):
    """Start the climb or the final review like a ticket: its own claim branch, worktree, caps and report."""
    key = ticket["id"]
    if key in ledger:  # requeued
        relaunch(state, ledger[key], ticket, out)
        return
    if git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name(state, key)}",
           cwd=state["integration_checkout"]) is not None:
        ledger[key] = {**new_entry(state, key, "needs-you", ""), "reason": LEFTOVER, "leftover": True}
        out.append(f"{key} needs you: {LEFTOVER}")
        return
    entry = claim(state, ledger, ticket)
    if entry is None: out.append(f"{key} already claimed")
    else: launch(state, entry, ticket, out, started=started.format(branch=entry["branch"]))


def start_climb(state, ledger, out):
    """One climb worker on factory/<feature>-climb, like a ticket: its own worktree, gate, report and caps."""
    if not climb_due(state, ledger) or free_room(state, ledger) <= 0: return
    start_extra(state, ledger, climb_ticket(state), out, f"climbing {state['feature']} on {{branch}}")


def review_due(state, ledger):
    """The final review should start: the whole feature is done and unreviewed (every started ticket merged,
    none waiting on the person, nothing startable, its approved climb merged too), or its review was requeued."""
    if REVIEW in ledger: return state["mode"] == "running" and ledger[REVIEW]["state"] == "ready"
    climb = ledger.get(CLIMB)
    return (built(state, ledger) and (climb["state"] == "merged" if climb else climb_ticket(state) is None))


def reviewed(state, ledger):
    """The feature's review is in, clean or accepted by the person: time to move on. A factory an older
    version left at "dispatched" has no review entry: its unsupervised review counts as in."""
    if REVIEW in ledger: return state["mode"] == "running" and ledger[REVIEW]["state"] == "merged"
    return state["mode"] == "running" and state["final_review"] == "dispatched"


def review_file(state):
    """The first feature's review keeps the old name; queued features get one each."""
    name = f"final-review-{state['feature']}.md" if state.get("done_features") else "final-review.md"
    return Path(state["state_dir"]) / name


def advance(state, ledger, out):
    """The feature is done and its review is in: start the next queued feature, else pause."""
    queue = state.get("next_features") or []
    if queue and tickets(state["integration_checkout"], queue[0]):
        done = state["feature"]
        save(Path(state["state_dir"]) / f"ledger-{done}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json", ledger)
        state["carried_starts"] = {now()[:10]: started_today(state, ledger)}  # the daily cap outlives the ledger
        ledger.clear()  # tick saves the emptied ledger for the next feature
        state["done_features"] = [*state.get("done_features", []), done]
        state.update(feature=queue[0], next_features=queue[1:], final_review="not-started", wave=[],
                     ping_merges=True)
        out.append(f"{done} done; now building {queue[0]}")
        ping(state, f"BUILT: feature {done} built, climbed and reviewed; now building {queue[0]}", out)
        return True
    if queue: out.append(f"next feature {queue[0]} has no ticket files; it stays queued")
    state["mode"], state["wave_ended_at"] = "paused", now()
    out.append("factory paused")
    return False


def final_review(state, ledger, out):
    """One review agent in a worktree of its own at the integration tip, supervised like a ticket worker:
    alive or interrupted, capped, and done only when it reports. Nothing queued starts before that."""
    if not review_due(state, ledger): return
    ticket = {"id": REVIEW, "path": None, "status": "ready-for-agent", "radius": "low", "blocked_by": []}
    try: start_extra(state, ledger, ticket, out, f"reviewing {state['feature']} on {{branch}}")
    finally:  # even when the claim was persisted and its worktree then failed
        if REVIEW in ledger: state["final_review"] = "dispatched"


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
            start_climb(state, ledger, out)
            final_review(state, ledger, out)
            if reviewed(state, ledger) and advance(state, ledger, out): start_tickets(state, ledger, out)  # the next feature, now
            update_mode(state, ledger, out)
            state["last_tick"] = now()
        finally:  # keep merges and claims made before any failure
            update_cards(state, ledger, out)
            save(directory / "ledger.json", ledger)
            save(directory / "state.json", state)
    print("\n".join(out) or "nothing to do")


# --- CLI actions ------------------------------------------------------------------

def install(args):
    runner = args.runner or "orca"
    ao_executable() if runner == "ao" else orca_executable()
    checkout = find_project(args.project)
    directory = checkout / STATE / "factory"
    if (directory / "state.json").is_file(): raise ValueError("A factory is already installed for this project")
    if not args.feature: raise ValueError("--feature is required")
    branch = args.integration_branch or git("branch", "--show-current", cwd=checkout)
    if not branch or git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=checkout) is None:
        raise ValueError(f"Integration branch {branch!r} does not exist")
    if branch in PROTECTED: raise ValueError(f"The integration branch cannot be {branch}")
    if not tickets(checkout, args.feature): raise ValueError(f"No ticket files in .scratch/{args.feature}/issues/")
    check_climb(checkout, args.feature)
    if not (checkout / GATES).is_file():
        raise ValueError(f"No gate script at {GATES}. Save and commit this starter, then install again:\n"
                         f"{starter_gate(checkout)}")
    if runner == "ao": project = ao_project(checkout)
    else:
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
             "final_review": "not-started", "last_tick": None, "runner": runner}
    if runner == "ao":
        state.update(ao_project=project, relay_spawned=False)
        state["relay_handle"] = ensure_relay(state)
    try: state["automation_id"] = register_heartbeat(state)
    except ValueError:
        if state.get("relay_spawned"): stop({"worker_handle": state["relay_handle"]})
        raise
    save(directory / "state.json", state)
    print(f"Factory installed for {args.feature} on {branch} ({state['mode']})")


def uninstall(args):
    """Stop the workers, remove the heartbeat, keep the ledger under a dated name; worktrees and branches stay."""
    directory = state_dir(args.project)
    with tick_lock(directory) as (state, ledger):
        out = []
        stop_all(ledger, out, "stopped by uninstall")
        update_cards(state, ledger, out)
        try:
            if state["automation_id"]: remove_heartbeat(state["automation_id"])
        except ValueError as error:
            out.append(f"heartbeat not removed ({error}); uninstalling anyway")
        if state.get("relay_spawned") and not stop({"worker_handle": state["relay_handle"]}):
            out.append(f"relay {state['relay_handle']} did not stop; {close_hint(state['relay_handle'])}")
        for review in [*state.get("past_reviews", []), state.get("final_review_handle")]:
            if is_ao(review) and not stop({"worker_handle": review}):
                out.append(f"final review {review} did not stop; {close_hint(review)}")
        if state.get("runner") == "ao":
            for feature in [*state.get("done_features", []), state["feature"]]:
                git("branch", "-D", f"factory/{feature}-final-review", cwd=state["integration_checkout"])
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
        score = (f"metric {entry['baseline']:g} -> {entry['final']:g}"
                 if type(entry.get("baseline")) is float and type(entry.get("final")) is float else None)
        print(" ".join(filter(None, [ticket, entry["state"], entry["branch"], entry["reason"], score])))
    for path in sorted(directory.glob("final-review*.md")): print(f"final review: {path}")
    if state.get("next_features"): print(f"next: {', '.join(state['next_features'])}")
    for line in wave_summary(state, ledger): print(line)
    parked = sum(e["state"] in REQUEUABLE for e in ledger.values())
    if (parked and state["mode"] == "running" and state["final_review"] == "not-started"
            and all(e["state"] in ("merged", *REQUEUABLE) for e in ledger.values()) and not startable(state, ledger)):
        print(f"final review waits on {parked} parked ticket{'s' * (parked != 1)}")


def wave_summary(state, ledger):
    """The last wave (the cycle's tickets, else every ticket): merges, what waits, queue wait, slowed-by lines."""
    wave = {t: ledger[t] for t in state["wave"] or ledger if t in ledger and t != REVIEW}
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
    try:
        with tick_lock(directory, wait=1.0) as (state, ledger):
            entry = ledger.get(args.ticket)
            if not entry or entry["state"] != "working": raise ValueError(f"Ticket {args.ticket} is not working")
            file_report(entry, args.result, args.reason, args.slowed_by)
            save(directory / "ledger.json", ledger)
    except TimeoutError:  # a tick holds the lock, maybe through a long gate: leave the report for the next one
        if (load(directory)[1].get(args.ticket) or {}).get("state") != "working":  # also keeps the name a ticket id
            raise ValueError(f"Ticket {args.ticket} is not working") from None
        save(report_file(directory, args.ticket),
             {"result": args.result, "reason": args.reason, "slowed_by": args.slowed_by})
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
        if args.ticket == REVIEW:  # the reviewer's findings are the person's to accept, once it has reported them
            if entry.get("reported") != "blocked":
                raise ValueError("The review reported no findings to accept; requeue it instead")
        elif next((s["state"] for s in reversed(entry["history"]) if s["state"] != "needs-you"), None) != "approved":
            raise ValueError(f"Ticket {args.ticket} was not approved by its worker; requeue it instead")
        out = []
        try:
            merged = land(state, args.ticket, entry, out)
        finally:
            update_cards(state, ledger, out)
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
            or climb_due(state, ledger) or review_due(state, ledger) or reviewed(state, ledger))
    return 0 if state["mode"] != "paused" and work else 1


def queue(args):
    """Queue an approved feature to build once this one is built, climbed and sent to final review."""
    directory = state_dir(args.project)
    with tick_lock(directory) as (state, _):
        queued = state.get("next_features") or []
        if args.ticket:
            name = args.ticket
            if name == state["feature"] or name in queued or name in state.get("done_features", []):
                raise ValueError(f"{name} is already in this factory")
            if not tickets(state["integration_checkout"], name):
                raise ValueError(f"No ticket files in .scratch/{name}/issues/ on {state['integration_branch']}")
            check_climb(state["integration_checkout"], name)
            state["next_features"] = queued = [*queued, name]
            save(directory / "state.json", state)
    print(f"next: {', '.join(queued) or 'nothing queued'}")


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
        update_cards(state, ledger, out)
        state["mode"] = "paused"
        save(directory / "ledger.json", ledger)
        save(directory / "state.json", state)
    print("\n".join([*out, "factory paused"]))


def stop_all(ledger, out, reason):
    """Stop every working worker; its ticket is interrupted and keeps its branch and worktree."""
    for ticket, entry in ledger.items():
        if entry["state"] != "working":
            continue
        if not stop(entry): out.append(f"worker {entry['worker_handle']} did not stop; {close_hint(entry['worker_handle'])}")
        move(entry, "interrupted", reason)
        out.append(f"interrupted {ticket}; {entry['branch']} and its worktree are kept")


def go(args, mode):
    """resume (running) or cycle (once); a manual Orca automation run ignores the precheck, so tick directly."""
    directory = state_dir(args.project)
    set_mode(directory, mode)
    tick(directory)


def add_parser(sub):
    f = sub.add_parser("factory", help="Unattended per-ticket builds through Orca or AO")
    f.add_argument("action", choices=("install", "uninstall", "status", "set", "tick", "gate", "report", "precheck",
                                      "pause", "resume", "cycle", "approve", "requeue", "queue"))
    f.add_argument("ticket", nargs="?", help="the ticket id, set's setting, or queue's feature")
    f.add_argument("result", nargs="?", help="report: approved|blocked; set: the value")
    f.add_argument("--project", default="."); f.add_argument("--feature")
    f.add_argument("--integration-branch", help="Default: the branch checked out in the project")
    f.add_argument("--paused", action="store_true"); f.add_argument("--allow-bypass", action="store_true")
    f.add_argument("--runner", choices=("orca", "ao"), help="install: who runs the workers (default: orca)")
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
               "approve": approve, "requeue": requeue, "queue": queue}
    return actions[args.action](args) or 0
