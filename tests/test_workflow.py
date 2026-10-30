import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from argparse import Namespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workflow", ROOT / "workflow.py")
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.project = self.base / "project with spaces"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, success=True, stdin=None, cwd=None):
        r = subprocess.run([sys.executable, "-B", str(ROOT / "workflow.py"), *args],
                           capture_output=True, text=True, input=stdin, cwd=cwd or ROOT)
        if success:
            self.assertEqual(r.returncode, 0, r.stderr)
        else:
            self.assertNotEqual(r.returncode, 0)
        return r

    def install(self, *args):
        return self.cli("install", "--project", str(self.project), "--platform", "all", *args)

    def test_package_integrity_and_version(self):
        self.assertEqual(workflow.verify()["version"], "0.3.1")
        with self.assertRaises(ValueError):
            workflow.verify(expected="99.0.0")

    def test_dry_run_does_not_write(self):
        self.install("--dry-run")
        self.assertFalse((self.project / ".engineering-workflow").exists())
        self.assertFalse((self.project / "AGENTS.md").exists())

    def test_install_preserves_instructions_and_unrelated_settings(self):
        (self.project / "AGENTS.md").write_text("Keep the payment checks.\n")
        config = self.project / ".claude/settings.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"permissions": {"deny": ["Bash(sudo *)"]}, "env": {"CUSTOM": "preserve"}}))
        self.install()
        self.assertIn("Keep the payment checks.", (self.project / "AGENTS.md").read_text())
        parsed = json.loads(config.read_text())
        self.assertEqual(parsed["env"], {"CUSTOM": "preserve"})
        self.assertEqual(parsed["permissions"], {"deny": ["Bash(sudo *)"]})
        self.assertTrue(list((self.project / ".workflow-backups").glob("*/AGENTS.md")))
        self.assertEqual(len(list((self.project / ".agents/skills").iterdir())), 43)

    def test_idempotent_install_no_duplicate_hooks_or_blocks(self):
        self.install()
        self.install()
        for p in (self.project / "AGENTS.md", self.project / "CLAUDE.md", self.project / "GEMINI.md"):
            self.assertEqual(p.read_text().count(workflow.START), 1)
        for rel in (".claude/settings.json", ".codex/hooks.json", ".gemini/settings.json"):
            data = json.loads((self.project / rel).read_text())
            self.assertTrue(all(len(entries) == 1 for entries in data["hooks"].values()))
        agy_hooks = json.loads((self.project / ".agents/hooks.json").read_text())
        self.assertIn("engineering-workflow", agy_hooks)

    def test_tampering_fails_session(self):
        self.install()
        runtime = self.project / ".engineering-workflow"
        (runtime / "core/WORKFLOW.md").write_text("tampered")
        r = self.cli("session", "--project", str(self.project), "--platform", "codex", success=False)
        self.assertIn("integrity mismatch", r.stderr)

    def test_tampered_lock_rejected_even_with_updated_file_hash(self):
        self.install()
        runtime = self.project / ".engineering-workflow"
        p = runtime / "workflow.lock.json"
        lock = json.loads(p.read_text()); lock["version"] = "fake"
        p.write_text(json.dumps(lock))
        self.cli("session", "--project", str(self.project), "--platform", "codex", success=False)

    def test_nested_session_selects_project_pin(self):
        self.install()
        sub = self.project / "src/deep"; sub.mkdir(parents=True)
        r = self.cli("session", "--project", str(sub), "--platform", "gemini")
        self.assertEqual(json.loads(r.stdout)["selection"], "project pin")

    def test_nested_install_normalizes_to_git_root(self):
        sub = self.project / "src"; sub.mkdir()
        self.cli("install", "--project", str(sub), "--platform", "codex")
        self.assertTrue((self.project / ".engineering-workflow/install.json").exists())
        self.assertFalse((sub / ".engineering-workflow").exists())

    def test_hook_merge_preserves_unrelated_sibling(self):
        prior = {"hooks": {"Stop": [{"hooks": [
            {"command": "python3 /old/workflow.py hook --platform codex"},
            {"command": "audit-tool"}]}]}}
        result = workflow.merge_hooks(prior, {"Stop": [{"hooks": [{"command": "new-hook"}]}]})
        self.assertEqual([h["command"] for e in result["hooks"]["Stop"] for h in e["hooks"]],
                         ["audit-tool", "new-hook"])

    def test_project_pin_executes_pinned_implementation(self):
        self.install()
        runtime = self.project / ".engineering-workflow"
        code = runtime / "workflow.py"
        code.write_text('print("selected-project-implementation")\n')
        lock = json.loads((runtime / "workflow.lock.json").read_text())
        lock["files"]["workflow.py"] = workflow.digest(code.read_bytes())
        (runtime / "workflow.lock.json").write_bytes(workflow.encoded(lock))
        state = json.loads((runtime / "install.json").read_text())
        state["lock_sha256"] = workflow.digest((runtime / "workflow.lock.json").read_bytes())
        (runtime / "install.json").write_bytes(workflow.encoded(state))
        r = self.cli("session", "--project", str(self.project), "--platform", "codex")
        self.assertEqual(r.stdout.strip(), "selected-project-implementation")

    def test_global_hook_yields_to_project_hook(self):
        self.install()
        r = self.cli("hook", "--platform", "codex", stdin=json.dumps({
            "hook_event_name": "SessionStart", "cwd": str(self.project)}))
        self.assertEqual(json.loads(r.stdout), {})

    def test_unmanaged_conflict_fails_before_writes(self):
        p = self.project / ".agents/skills/ew-ponytail"
        p.mkdir(parents=True); (p / "SKILL.md").write_text("mine")
        self.cli("install", "--project", str(self.project), "--platform", "all", success=False)
        self.assertEqual((p / "SKILL.md").read_text(), "mine")
        self.assertFalse((self.project / "AGENTS.md").exists())

    def test_persistent_config_failure_restores_previous_runtime(self):
        self.install()
        runtime = self.project / ".engineering-workflow"
        marker = runtime / "recovery-marker"
        marker.write_text("old-runtime")
        before = (self.project / "CLAUDE.md").read_bytes()
        atomic = workflow.write_atomic

        def fail_config(path, content):
            if path.name == "settings.json":
                raise PermissionError("persistent config-write failure")
            return atomic(path, content)

        args = Namespace(scope="project", project=str(self.project), home=str(self.base),
            platform="all", expected=None, headroom=False, adhd=False, dry_run=False, replace_overlap=False)
        with patch.object(workflow, "write_atomic", side_effect=fail_config):
            with self.assertRaises(PermissionError):
                workflow.install(args)
        self.assertEqual(marker.read_text(), "old-runtime")
        self.assertEqual((self.project / "CLAUDE.md").read_bytes(), before)
        workflow.verify(runtime)

    def test_user_install_and_overlap_replacement(self):
        home = self.base / "home"; (home / ".claude").mkdir(parents=True)
        (home / ".codex").mkdir()
        c = home / ".claude/settings.json"
        c.write_text(json.dumps({"enabledPlugins": {"headroom@market": True, "unrelated@market": True,
                                                    "i-have-adhd@i-have-adhd": True},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "/bin/headroom init hook ensure"},
                {"type": "command", "command": "keep-unrelated-hook"}]}]}}))
        t = home / ".codex/config.toml"
        t.write_text('[plugins."headroom@market"]\nenabled = true\n[plugins."keep@market"]\nenabled = true\n')
        self.cli("install", "--scope", "user", "--home", str(home), "--platform", "all", "--replace-overlap")
        data = json.loads(c.read_text())
        self.assertFalse(data["enabledPlugins"]["headroom@market"])
        self.assertFalse(data["enabledPlugins"]["i-have-adhd@i-have-adhd"])
        self.assertTrue(data["enabledPlugins"]["unrelated@market"])
        hooks = str(data["hooks"])
        self.assertIn("keep-unrelated-hook", hooks)
        self.assertNotIn("/bin/headroom init", hooks)
        import tomllib
        d = tomllib.loads(t.read_text())
        self.assertFalse(d["plugins"]["headroom@market"]["enabled"])
        self.assertTrue(d["plugins"]["keep@market"]["enabled"])

    def test_adhd_ruleset_injected_only_when_installed_with_flag(self):
        def start():
            r = subprocess.run([sys.executable, "-B", str(self.project / ".engineering-workflow/workflow.py"),
                "hook", "--platform", "claude"], input=json.dumps({"hook_event_name": "SessionStart",
                "cwd": str(self.project)}), text=True, capture_output=True, check=True)
            return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.install("--adhd")
        context = start()
        self.assertIn('"adhd": "always-on ruleset injected"', context)
        self.assertIn("ADHD MODE ACTIVE", context)
        self.assertNotIn("name: ew-i-have-adhd", context)
        self.assertTrue((self.project / ".claude/skills/ew-i-have-adhd").is_symlink())
        self.install()
        self.assertNotIn("ADHD MODE", start())

    def test_guard_allow_and_block_all_platform_protocols(self):
        for platform, event, tool in (("claude", "PreToolUse", "Bash"),
                                      ("codex", "PreToolUse", "exec_command"),
                                      ("gemini", "BeforeTool", "run_shell_command")):
            safe = {"hook_event_name": event, "tool_name": tool, "cwd": str(self.project),
                    "tool_input": {"command": "git status"}}
            self.assertEqual(workflow.hook(platform, safe), {})
            safe["tool_input"] = {"command": "rm -rf /"}
            result = workflow.hook(platform, safe)
            self.assertNotIn("rm -rf", json.dumps(result))
            if platform == "gemini": self.assertEqual(result["decision"], "deny")
            else: self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        agy_safe = {"workspacePaths": [str(self.project)],
                    "toolCall": {"name": "run_command", "args": {"CommandLine": "git status"}}}
        self.assertEqual(workflow.hook("agy", agy_safe, event="PreToolUse"), {"decision": "ask"})
        agy_bad = {"workspacePaths": [str(self.project)],
                   "toolCall": {"name": "run_command", "args": {"CommandLine": "rm -rf /"}}}
        agy_res = workflow.hook("agy", agy_bad, event="PreToolUse")
        self.assertNotIn("rm -rf", json.dumps(agy_res))
        self.assertEqual(agy_res["decision"], "deny")

    def test_agy_hooks_preserve_orca_and_handle_lifecycle(self):
        home = self.base / "agy-home"
        orca_cfg = home / ".gemini/config/hooks.json"
        orca_cfg.parent.mkdir(parents=True)
        orca_cfg.write_text(json.dumps({"orca-status": {"Stop": [{"type": "command", "command": "orca-stop"}]}}))
        self.cli("install", "--scope", "user", "--home", str(home), "--platform", "agy")
        merged = json.loads(orca_cfg.read_text())
        self.assertIn("orca-status", merged)
        self.assertIn("engineering-workflow", merged)
        start = workflow.hook("agy", {"workspacePaths": [str(self.project)]}, event="SessionStart")
        self.assertIn("verified", start["injectSteps"][0]["systemMessage"]["systemMessage"])
        self.assertEqual(workflow.hook("agy", {"workspacePaths": [str(self.project)]}, event="Stop"), {"decision": ""})
        self.cli("goal", "set", "approved agy task", "--project", str(self.project))
        self.assertEqual(workflow.hook("agy", {"workspacePaths": [str(self.project)],
                                               "terminationReason": "USER_CANCELED"}, event="Stop"), {"decision": ""})
        cont = workflow.hook("agy", {"workspacePaths": [str(self.project)],
                                     "terminationReason": "NO_TOOL_CALL"}, event="Stop")
        self.assertEqual(cont["decision"], "continue")

    def test_goal_continuations_are_bounded_and_pausing_stops(self):
        self.cli("goal", "set", "approved task", "--project", str(self.project))
        data = {"hook_event_name": "Stop", "cwd": str(self.project)}
        for _ in range(30): self.assertEqual(workflow.hook("codex", data)["decision"], "block")
        self.assertIn("systemMessage", workflow.hook("codex", data))
        self.assertEqual(workflow.hook("codex", data), {})
        state = json.loads(workflow.goal_path(self.project).read_text())
        self.assertEqual(state["status"], "needs-attention")
        self.cli("goal", "resume", "--project", str(self.project))
        self.cli("goal", "pause", "--project", str(self.project))
        self.assertEqual(workflow.hook("codex", data), {})

    def test_complete_requires_evidence(self):
        self.cli("goal", "set", "approved task", "--project", str(self.project))
        self.cli("goal", "complete", "--project", str(self.project), success=False)
        self.cli("goal", "complete", "--project", str(self.project), "--evidence", "suite: 12 passed")
        self.assertEqual(json.loads(workflow.goal_path(self.project).read_text())["status"], "complete")

    def test_gemini_goal_protocol_and_subagent_filter(self):
        self.cli("goal", "set", "approved task", "--project", str(self.project))
        data = {"hook_event_name": "AfterAgent", "cwd": str(self.project)}
        self.assertEqual(workflow.hook("gemini", {**data, "agent_id": "child"}), {})
        self.assertEqual(workflow.hook("gemini", data)["decision"], "deny")

    def test_secret_warning_never_echoes_matches(self):
        secret = "AKIA" + "Z" * 16
        p = self.project / "example.py"
        p.write_text('access_key = "' + secret + '"\n')
        result = workflow.hook("codex", {"hook_event_name": "PostToolUse", "cwd": str(self.project),
                                          "tool_input": {"file_path": str(p)}})
        self.assertNotIn(secret, json.dumps(result))
        self.assertIn("potential credential", json.dumps(result))

    def test_generated_project_hook_works_from_nested_directory_with_spaces(self):
        self.install()
        deep = self.project / "src"; deep.mkdir()
        command = json.loads((self.project / ".codex/hooks.json").read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        result = subprocess.run(command, shell=True, cwd=deep, input=json.dumps({
            "hook_event_name": "SessionStart", "cwd": str(deep)}), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertIn("verified", output["hookSpecificOutput"]["additionalContext"])

    def test_docs_reports_missing_tools_without_claiming_refresh(self):
        data = workflow.docs(self.project)
        self.assertEqual(data["graph"], "absent")
        self.assertFalse(data["tracker_configured"])
        with self.assertRaises(ValueError): workflow.docs(self.project, refresh=True)


if __name__ == "__main__":
    unittest.main()
