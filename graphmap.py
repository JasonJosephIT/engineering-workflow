"""Graphify overlay: heavy graph in a central store, thin committed docs/map/MAP.md."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

MAP = Path("docs/map/MAP.md")
LABELS = Path("docs/map/labels.json")  # {"<area main file>": "<plain name>"}, written by a labeling worker
OUT = "graphify-out"
EXCLUDE = (":(exclude)docs/map", ":(exclude)" + OUT, ":(exclude).gitignore")
LOCK_AGE = 900  # seconds before a background refresh lock counts as abandoned


def _git(project, *args):
    r = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, timeout=20)
    return r.stdout.strip() if r.returncode == 0 else ""


WORKSPACE_FILE = ".engineering-workflow-workspace.json"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-") or "project"


def _base():
    return Path(os.environ.get("EW_GRAPH_STORE") or Path.home() / ".graphify/projects")


def identity(root):
    """A workspace is the folder the workflow runs in. A project groups one or more workspaces.
    Without a workspace file the folder is a project with a single workspace of the same name."""
    root = Path(root)
    path = root / WORKSPACE_FILE
    data = json.loads(path.read_text()) if path.is_file() else {}
    workspace = slug(data.get("workspace") or root.resolve().name)
    project = slug(data.get("project") or workspace)
    return {"project": project, "workspace": workspace, "declared": path.is_file()}


def set_identity(root, project, workspace=None):
    root = Path(root)
    data = {"project": slug(project), "workspace": slug(workspace or root.resolve().name)}
    (root / WORKSPACE_FILE).write_text(json.dumps(data, indent=2) + "\n")
    return data


def store(root):
    """Heavy graph home: <base>/<project>/<workspace>/ (EW_GRAPH_STORE overrides <base>)."""
    ident = identity(root)
    return _base() / ident["project"] / ident["workspace"]


def siblings(root):
    """Other workspaces of the same project that have built a graph on this machine."""
    ident = identity(root)
    folder = _base() / ident["project"]
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.is_dir() and p.name != ident["workspace"])


def status(project):
    """absent | legacy | stale | fresh. Freshness is commit-based, so a fresh clone is judged correctly."""
    project = Path(project)
    out, path = project / OUT, project / MAP
    if out.exists() and not out.is_symlink():
        return "legacy graphify-out/ committed; run workflow.py graph --migrate"
    if not path.is_file():
        return "absent"
    m = re.search(r"^Built from commit: `([0-9a-f]{7,40})`", path.read_text(), re.M)
    if not m:
        return "stale"
    if subprocess.run(["git", "cat-file", "-e", m.group(1) + "^{commit}"], cwd=project,
                      capture_output=True).returncode != 0:
        return "stale"  # built commit unknown here (rebased away or never existed)
    changed = _git(project, "rev-list", "--count", m.group(1) + "..HEAD", "--", ".", *EXCLUDE)
    return "fresh" if changed == "0" else "stale"


def _link(project, migrate):
    """Point project/graphify-out at the central store and keep it out of git."""
    out, home = project / OUT, store(project)
    if out.is_symlink():
        if out.resolve() != home.resolve():
            raise ValueError(f"{OUT} links somewhere other than the workflow store")
    elif out.exists():
        if not migrate:
            raise ValueError(f"{OUT}/ is a real directory; rerun with --migrate to move it to {home}")
        if home.exists() and any(home.iterdir()):
            raise ValueError(f"Store {home} is not empty; move or remove it before migrating")
        home.parent.mkdir(parents=True, exist_ok=True)
        if home.exists():
            home.rmdir()
        shutil.move(str(out), str(home))
        _git(project, "rm", "-r", "-q", "--cached", "--ignore-unmatch", OUT)
    home.mkdir(parents=True, exist_ok=True)
    if not out.is_symlink():
        out.symlink_to(home, target_is_directory=True)
    ignore = project / ".gitignore"
    lines = ignore.read_text().splitlines() if ignore.exists() else []
    if not any(l.strip().strip("/") == OUT for l in lines):
        ignore.write_text("\n".join([*lines, OUT]) + "\n")
    return home


def _build(project):
    if not shutil.which("graphify"):
        raise ValueError("Graphify CLI not found on PATH; it is mandatory for the graph overlay")
    def run(*a):
        r = subprocess.run(["graphify", *a], cwd=project, timeout=900, capture_output=True, text=True)
        if r.returncode:
            raise ValueError(f"graphify {' '.join(a)} failed: " + (r.stderr.strip().splitlines() or ["no output"])[-1])
    if (project / OUT / "graph.json").is_file():
        run("update", ".")
    else:  # code-only first build: no LLM, no API cost
        run("extract", ".", "--code-only")
        run("cluster-only", ".", "--no-label")


def render(graph, commit, ident=None, others=(), labels=None):
    nodes, links = graph.get("nodes", []), graph.get("links", graph.get("edges", []))
    degree = Counter()
    for e in links:
        degree[e.get("source")] += 1
        degree[e.get("target")] += 1
    communities = defaultdict(list)
    for n in nodes:
        communities[n.get("community")].append(n)
    lines = ["# Code map", "",
             "*Generated by `workflow.py graph` from Graphify. Do not edit; rerun to refresh.*", "",
             f"Built from commit: `{commit}`", "",
             *([f"Project: **{ident['project']}** · workspace: **{ident['workspace']}**"
                + (f" · other workspaces: {', '.join(others)}" if others else ""), ""] if ident else []),
             f"{len(nodes)} nodes · {len(links)} edges · {len(communities)} communities", "",
             "## Hubs (most connected)", ""]
    by_id = {n.get("id"): n for n in nodes}
    for nid, d in degree.most_common(12):
        n = by_id.get(nid)
        if n:
            lines.append(f"- **{n.get('label', nid)}** ({d}) `{n.get('source_file', '')}`")
    lines += ["", "## Areas", ""]
    ranked = sorted(communities.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))
    for cid, members in ranked[:40]:
        if len(members) < 3:
            continue
        files = Counter(m.get("source_file") for m in members if m.get("source_file"))
        main = files.most_common(1)[0][0] if files else ""
        name = (labels or {}).get(main) or next(
            (m.get("community_name") for m in members if m.get("community_name")), None) or f"Community {cid}"
        lines.append(f"### {name} ({len(members)})")
        lines += [f"- `{f}`" for f, _ in files.most_common(6)]
        lines.append("")
    lines += ["## Query locally", "",
              "- `graphify explain \"X\"`, `graphify path \"A\" \"B\"`, `graphify affected \"X\"`",
              "- Full graph lives outside the repo; `graphify-out/` is a symlink to it.", ""]
    return "\n".join(lines)


def build(project, migrate=False):
    project = Path(project)
    if not shutil.which("graphify"):
        raise ValueError("Graphify CLI not found on PATH; it is mandatory for the graph overlay")
    home = _link(project, migrate)
    _build(project)
    graph_path = home / "graph.json"
    if not graph_path.is_file():
        raise ValueError("Graphify produced no graph.json")
    commit = _git(project, "rev-parse", "HEAD") or "0000000"
    out = project / MAP
    out.parent.mkdir(parents=True, exist_ok=True)
    ident = identity(project)
    labels = json.loads((project / LABELS).read_text()) if (project / LABELS).is_file() else {}
    out.write_text(render(json.loads(graph_path.read_text()), commit, ident, siblings(project), labels))
    return {"graph": "refreshed", "map": str(MAP), "store": str(home), **ident,
            "next": "commit docs/map/ and .gitignore with the change"}


def refresh_in_background(project, workflow_py):
    """SessionStart cannot wait a minute; start a detached refresh guarded by a lock."""
    project = Path(project)
    if not shutil.which("graphify") or not (project / OUT).is_symlink():
        return None
    home = store(project)
    home.mkdir(parents=True, exist_ok=True)
    lock = home / "refresh.lock"
    if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_AGE:
        return "refresh already running"
    lock.write_text(str(os.getpid()))
    log = open(home / "refresh.log", "w")
    script = (f"import subprocess,sys,pathlib;p=pathlib.Path({str(lock)!r});"
              f"r=subprocess.run([sys.executable,'-B',{str(workflow_py)!r},'graph','--project',{str(project)!r}]);"
              "p.unlink(missing_ok=True);sys.exit(r.returncode)")
    subprocess.Popen([sys.executable, "-c", script], cwd=project, stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    return "started in background; commit docs/map/ when it updates (log in store/refresh.log)"


HANDOFF = """You are a graph worker for workspace {workspace} of project {project}.
Engineering workflow, Graphify overlay. Do only this:
1. Run: python3 -B {workflow} graph --project .{migrate}
   (code-only Graphify build, no LLM; writes docs/map/MAP.md).
2. Name the areas. For each `### Community N` heading in docs/map/MAP.md, read its listed files
   and pick a 2-4 word plain name. Write docs/map/labels.json as {{"<first file listed>": "<name>"}}.
   Keep existing entries that still match. No other files.
3. Run step 1 again so MAP.md uses the names.
4. Commit docs/map/ and .gitignore{migrate_note} on your branch and open a PR titled
   "Code map: {workspace}". Do not edit source code.
5. Report done with the PR link, or blocked with the exact error.
"""


def handoff(root, ao_projects, workflow_py, spawn=False, harness="mimo-code"):
    """Brief one AO worker (MiMo by default) per workspace to build and label its code map."""
    root = Path(root)
    ident = identity(root)
    legacy = (root / OUT).exists() and not (root / OUT).is_symlink()
    brief = HANDOFF.format(workspace=ident["workspace"], project=ident["project"], workflow=workflow_py,
                           migrate=" --migrate" if legacy else "",
                           migrate_note=" (and the graphify-out/ removal)" if legacy else "")
    jobs = []
    for ao in ao_projects:
        command = ["ao", "spawn", "--project", ao, "--harness", harness,
                   "--name", f"graph: {ao}", "--prompt", brief]
        job = {"ao_project": ao, "command": " ".join(command[:7]) + " --prompt <brief>"}
        if spawn:
            r = subprocess.run(command, capture_output=True, text=True, timeout=60)
            job["spawned"] = r.returncode == 0
            job["reply"] = (r.stdout or r.stderr).strip()[-300:]
        jobs.append(job)
    return {"workspace": ident, "brief": brief, "jobs": jobs,
            "note": "pass --spawn to start the workers" if not spawn else "workers started; review their PRs"}
