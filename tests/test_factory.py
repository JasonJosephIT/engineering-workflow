"""Factory CLI tests: a temp git repo and a fake `orca` on PATH that logs every call."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import plistlib
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TICKET = """# 01: Thing

**Status:** ready-for-agent

**Blocked by:** None (can start immediately)

**Blast radius:** low
"""
FAKE_ORCA = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
control = Path(os.environ['FAKE_ORCA_DIR'])
args = sys.argv[1:]
with open(control / 'log.jsonl', 'a') as log: log.write(json.dumps(args) + '\\n')
words = ' '.join(a for a in args if not a.startswith('-'))
def reply(ok=True, **result): print(json.dumps({{'ok': ok, 'result': result}}))
if (control / 'non-dict').exists(): print('[]')
elif words.startswith('repo show'): reply(ok=not (control / 'unregistered').exists())
elif words.startswith('automations create'): reply(automation={{'id': 'auto_1'}})
elif words.startswith('automations remove'): reply(ok=not (control / 'automation-gone').exists())
elif words.startswith('agent launch') and (control / 'launch-fails').exists():
    print(json.dumps({{'ok': False, 'error': {{'code': 'runtime_error', 'message': 'no workspace for path'}}}}))
elif words.startswith('agent launch'):
    launched = sum(line.startswith('["agent", "launch"') for line in (control / 'log.jsonl').read_text().splitlines())
    outcome = {{'outcome': {{'kind': 'terminal', 'handle': f'term_{{launched}}'}}}}  # Orca's reply: outcome at the top
    reply(**({{'launch': outcome}} if (control / 'legacy-launch').exists() else outcome))
elif words.startswith('terminal read') and (control / 'read-fails').exists(): reply(ok=False)
elif words.startswith('terminal read'):
    screens = (control / 'bypass', control / f"screen-{{args[args.index('--terminal') + 1]}}", control / 'screen')
    reply(text=next((p.read_text() or 'claude --dangerously-skip-permissions' for p in screens if p.exists()), 'claude'))
elif words.startswith('worktree set'): reply(ok=not (control / 'card-fails').exists(), worktree={{}})
elif words.startswith('terminal close'):  # closes the terminal, yet reports ok:false like the real CLI
    (control / f"dead-{{args[args.index('--terminal') + 1]}}").touch(); reply(ok=False)
elif words.startswith('terminal show') and (control / 'show-fails').exists(): reply(ok=False)
elif words.startswith('terminal show'):
    reply(terminal={{'connected': not (control / f"dead-{{args[args.index('--terminal') + 1]}}").exists()}})
else: reply(ok=False)
"""
GATES = 'echo "checking"\necho "${FAKE_GATE:-GATES: PASS}"\n'


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base / 'project with spaces'; self.project.mkdir()
        self.orca_dir = self.base / 'orca'; self.orca_dir.mkdir()
        self.fakebin = self.base / 'fake bin'; self.fakebin.mkdir()
        for name in ('orca', 'orca-ide'):  # the adapter resolves orca-ide on Linux
            orca = self.fakebin / name; orca.write_text(FAKE_ORCA); orca.chmod(0o755)
        self.env = {**os.environ, 'PATH': f'{self.fakebin}:{os.environ["PATH"]}',
                    'FAKE_ORCA_DIR': str(self.orca_dir)}
        self.env.pop('ORCA_CLI_COMMAND', None)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'factory@example.com'); self.git('config', 'user.name', 'Factory')
        (self.project / 'README.md').write_text('demo\n')
        self.git('add', '-A'); self.git('commit', '-qm', 'init')
        self.git('checkout', '-qb', 'build/demo')
        issues = self.project / '.scratch' / 'demo' / 'issues'; issues.mkdir(parents=True)
        (issues / '01-thing.md').write_text(TICKET)
        gates = self.project / '.engineering-workflow' / 'gates.sh'; gates.parent.mkdir()
        gates.write_text(GATES)
        self.git('add', '-A'); self.git('commit', '-qm', 'tickets and gate')
        self.state_dir = self.project / '.engineering-workflow-state' / 'factory'
        self.worktree = self.state_dir / 'worktrees' / 'demo-01'

    def tearDown(self): self.tmp.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.project, check=True,
                              text=True, capture_output=True).stdout.strip()

    def cli(self, action, *args, project=None, ok=True, env=None):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'workflow.py'), 'factory', action,
                                 *args, '--project', str(project or self.project)],
                                text=True, capture_output=True, env=env or self.env)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def orca_calls(self):
        log = self.orca_dir / 'log.jsonl'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def ledger(self): return json.loads((self.state_dir / 'ledger.json').read_text())
    def state(self): return json.loads((self.state_dir / 'state.json').read_text())

    def test_one_ticket_goes_from_ready_to_merged(self):
        main_before = self.git('rev-parse', 'main')
        self.cli('install', '--feature', 'demo')
        state = self.state()
        self.assertEqual((state['mode'], state['feature'], state['integration_branch'], state['automation_id'],
                          state['allow_bypass']), ('running', 'demo', 'build/demo', 'auto_1', False))
        heartbeat = self.orca_calls()[-1]
        self.assertEqual(heartbeat[:2], ['automations', 'create'])
        self.assertIn('hourly', heartbeat)
        self.assertIn('--extra-agent-args=--model sonnet', heartbeat)
        self.assertIn(f'path:{self.project}', heartbeat)
        self.assertIn(f"tick --detach --project '{self.project}'", heartbeat[heartbeat.index('--prompt') + 1])
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.cli('status').stdout.splitlines()[0],
                         'factory: running · 1 ready · 0 building · 0 needs you')

        self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['branch'], entry['worker_handle']),
                         ('working', 'factory/demo-01', 'term_1'))
        self.assertEqual(self.git('rev-parse', 'factory/demo-01'), self.git('rev-parse', 'build/demo'))
        marker = json.loads((self.worktree / '.engineering-workflow-state' / 'factory-ticket.json').read_text())
        self.assertEqual(marker, {'ticket': '01', 'state_dir': str(self.state_dir)})
        launch = [c for c in self.orca_calls() if c[:2] == ['agent', 'launch']]
        self.assertEqual(len(launch), 1)
        self.assertIn(f'path:{self.worktree}', launch[0])
        self.assertIn('claude', launch[0])
        self.assertIn('01 working factory/demo-01', self.cli('status').stdout)

        (self.worktree / 'thing.txt').write_text('built\n')
        self.git('add', '-A', cwd=self.worktree)
        self.git('commit', '-qm', 'Build thing', cwd=self.worktree)
        self.cli('report', '01', 'approved', '--slowed-by', 'nothing', project=self.worktree)

        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['slowed_by']), ('merged', 'nothing'))
        self.assertEqual([h['state'] for h in entry['history']], ['working', 'approved', 'merged'])
        parents = self.git('rev-list', '--parents', '-n', '1', 'build/demo').split()
        self.assertEqual(len(parents), 3)
        self.assertEqual(self.git('show', 'build/demo:thing.txt'), 'built')
        self.assertFalse(self.worktree.exists())
        self.assertNotIn(str(self.worktree), self.git('worktree', 'list'))
        self.git('rev-parse', '--verify', 'refs/heads/factory/demo-01')
        self.assertEqual(self.git('rev-parse', 'main'), main_before)
        self.assertEqual(self.git('branch', '--show-current'), 'build/demo')


    def test_install_refuses_without_orca_or_on_main_or_missing_branch_tickets_gate_or_registration(self):
        no_orca = {**self.env, 'PATH': os.environ['PATH'], 'ORCA_CLI_COMMAND': 'orca-not-installed-here'}
        self.assertIn('Orca CLI not found', self.cli('install', '--feature', 'demo', ok=False, env=no_orca).stderr)
        self.assertIn('cannot be main',
                      self.cli('install', '--feature', 'demo', '--integration-branch', 'main', ok=False).stderr)
        self.assertIn('does not exist',
                      self.cli('install', '--feature', 'demo', '--integration-branch', 'nope', ok=False).stderr)
        self.assertIn('No ticket files', self.cli('install', '--feature', 'other', ok=False).stderr)
        (self.orca_dir / 'unregistered').touch()
        self.assertIn('not registered in Orca', self.cli('install', '--feature', 'demo', ok=False).stderr)
        (self.orca_dir / 'unregistered').unlink()
        self.git('rm', '-q', '.engineering-workflow/gates.sh'); self.git('commit', '-qm', 'drop gate')
        refused = self.cli('install', '--feature', 'demo', ok=False).stderr
        self.assertIn('No gate script', refused)
        self.assertIn('GATES: PASS', refused)
        self.assertFalse((self.state_dir / 'state.json').exists())
        self.assertFalse([c for c in self.orca_calls() if c[:2] == ['automations', 'create']])

    def test_second_install_refuses_and_paused_install_starts_nothing(self):
        self.cli('install', '--feature', 'demo', '--paused')
        self.assertEqual(self.state()['mode'], 'paused')
        self.assertIn('already installed', self.cli('install', '--feature', 'demo', ok=False).stderr)
        self.cli('tick')
        self.assertEqual(self.ledger(), {})
        self.assertFalse([c for c in self.orca_calls() if c[:2] == ['agent', 'launch']])

    def test_gate_passes_only_when_last_line_is_exactly_gates_pass(self):
        for output, ok in (('GATES: PASS', True), ('GATES: FAIL tests', False),
                           ('GATES: PASS\\nmore', False), ('GATES: PASS ', False)):
            with self.subTest(output=output):
                self.cli('gate', ok=ok, env={**self.env, 'FAKE_GATE': output.replace('\\n', '\n')})
        (self.project / '.engineering-workflow' / 'gates.sh').unlink()
        self.cli('gate', ok=False)

    def test_pre_merge_gate_runs_the_integration_branch_script_not_the_workers(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        (self.project / '.engineering-workflow' / 'gates.sh').write_text('echo "GATES: FAIL tests"\n')
        self.git('commit', '-qam', 'The project gate fails')
        (self.worktree / '.engineering-workflow' / 'gates.sh').write_text('echo "GATES: PASS"\n')
        self.git('commit', '-qam', 'Worker rewrites its gate', cwd=self.worktree)
        before = self.git('rev-parse', 'build/demo')
        self.cli('report', '01', 'approved', '--slowed-by', 'nothing', project=self.worktree)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('needs-you', 'gates failed on the ticket branch'))
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)
        self.assertTrue(self.worktree.exists())
        self.cli('approve', '01', ok=False)
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)

    def test_merge_refuses_when_integration_checkout_is_on_main(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        (self.worktree / 'thing.txt').write_text('built\n')
        self.git('add', '-A', cwd=self.worktree); self.git('commit', '-qm', 'Build thing', cwd=self.worktree)
        self.git('checkout', '-q', 'main')
        main_before = self.git('rev-parse', 'main')
        refused = self.cli('report', '01', 'approved', '--slowed-by', 'nothing', project=self.worktree, ok=False)
        self.assertIn('refusing to merge', refused.stderr)
        self.assertEqual(self.git('rev-parse', 'main'), main_before)
        self.assertEqual(self.ledger()['01']['state'], 'approved')

    def build(self, name='thing.txt', text='built\n', commit=True):
        (self.worktree / name).write_text(text)
        if commit:
            self.git('add', '-A', cwd=self.worktree)
            self.git('commit', '-qm', f'Build {name}', cwd=self.worktree)

    def approve(self, *extra, ok=True):
        return self.cli('report', '01', 'approved', '--slowed-by', 'nothing', *extra, project=self.worktree, ok=ok)

    def test_failed_launch_parks_the_ticket_and_the_next_ticket_still_starts(self):
        second = self.project / '.scratch' / 'demo' / 'issues' / '02-other.md'
        second.write_text(TICKET.replace('01: Thing', '02: Other'))
        self.git('add', '-A'); self.git('commit', '-qm', 'second ticket')
        self.cli('install', '--feature', 'demo'); self.set_state(concurrency=1)
        (self.orca_dir / 'launch-fails').touch()
        self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual(entry['state'], 'needs-you')
        self.assertTrue(entry['reason'].startswith('worker launch failed: '), entry['reason'])
        self.assertIn('no workspace for path', entry['reason'])
        self.assertIsNone(entry['worker_handle'])
        self.assertTrue(self.worktree.exists())
        self.git('rev-parse', '--verify', 'refs/heads/factory/demo-01')
        (self.orca_dir / 'launch-fails').unlink()
        self.cli('tick')
        self.assertEqual(self.ledger()['02']['state'], 'working')
        self.assertEqual(self.ledger()['01']['state'], 'needs-you')

    def test_uncommitted_worker_output_blocks_the_merge(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.build('thing.txt'); self.build('loose.txt', commit=False)
        before = self.git('rev-parse', 'build/demo')
        self.approve()
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('needs-you', 'uncommitted changes in the worktree'))
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)
        self.assertEqual((self.worktree / 'loose.txt').read_text(), 'built\n')

    def test_merge_conflict_goes_to_needs_you_and_leaves_integration_clean(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        (self.project / 'README.md').write_text('integration side\n')
        self.git('commit', '-qam', 'Integration change')
        before = self.git('rev-parse', 'build/demo')
        self.build('README.md', 'ticket side\n')
        self.approve()
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('needs-you', 'merge conflict'))
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertTrue(self.worktree.exists())

    def test_report_blocked_records_the_reason(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.cli('report', '01', 'blocked', '--reason', 'needs an API decision', '--slowed-by', 'unclear spec',
                 project=self.worktree)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason'], entry['slowed_by']),
                         ('needs-you', 'needs an API decision', 'unclear spec'))
        self.assertTrue(self.worktree.exists())

    def test_later_field_lines_in_the_ticket_body_do_not_override_status(self):
        ticket = self.project / '.scratch' / 'demo' / 'issues' / '01-thing.md'
        ticket.write_text(TICKET + '\nNotes from the last attempt.\n\nStatus: shipped once, then reverted\n')
        self.git('commit', '-qam', 'ticket notes')
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'working')

    def test_non_json_object_reply_from_orca_is_not_ok(self):
        (self.orca_dir / 'non-dict').touch()
        refused = self.cli('install', '--feature', 'demo', ok=False).stderr
        self.assertEqual(refused.strip(), 'Error: This repo is not registered in Orca')

    def test_worker_launched_in_bypass_is_stopped_and_factory_pauses(self):
        (self.orca_dir / 'bypass').touch()
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual(entry['state'], 'needs-you')
        self.assertEqual(entry['reason'], "Orca launched in bypass mode; remove it from Orca's Claude "
                                          "arguments or reinstall with --allow-bypass")
        self.assertEqual(self.state()['mode'], 'paused')
        self.assertIn(['terminal', 'close', '--terminal', 'term_1', '--json'], self.orca_calls())

    def test_allow_bypass_is_recorded_and_keeps_the_worker(self):
        (self.orca_dir / 'bypass').touch()
        self.cli('install', '--feature', 'demo', '--allow-bypass'); self.cli('tick')
        self.assertTrue(self.state()['allow_bypass'])
        self.assertEqual((self.ledger()['01']['state'], self.state()['mode']), ('working', 'running'))
        self.assertFalse([c for c in self.orca_calls() if c[:1] == ['terminal']])

    # --- ticket 05 (uses ticket 03's add_ticket, set_state and finish helpers) ---
    def test_pause_drains_in_flight_work_then_pauses(self):
        self.add_ticket('02')
        self.cli('install', '--feature', 'demo'); self.set_state(concurrency=1); self.cli('tick')
        self.cli('pause')
        self.assertEqual(self.state()['mode'], 'draining')
        self.cli('tick')
        self.assertNotIn('02', self.ledger())
        self.build(); self.approve()
        self.assertEqual(self.ledger()['01']['state'], 'merged')
        self.assertEqual(self.state()['mode'], 'paused')
        self.assertNotIn('02', self.ledger())

    def test_pause_with_nothing_in_flight_pauses_at_once(self):
        self.cli('install', '--feature', 'demo')
        self.cli('pause')
        self.assertEqual(self.state()['mode'], 'paused')

    def test_pause_now_stops_workers_and_keeps_their_work(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.build('half.txt', 'half done\n')
        self.cli('pause', '--now')
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['branch']), ('interrupted', 'factory/demo-01'))
        self.assertEqual(self.state()['mode'], 'paused')
        self.assertIn(['terminal', 'close', '--terminal', 'term_1', '--json'], self.orca_calls())
        self.assertEqual((self.worktree / 'half.txt').read_text(), 'half done\n')
        self.assertEqual(self.cards()[-1], self.held_card('interrupted: stopped by pause --now'))
        self.assertEqual(self.git('show', 'factory/demo-01:half.txt'), 'half done')

    def test_cycle_runs_one_wave_then_pauses(self):
        self.add_ticket('02')
        self.cli('install', '--feature', 'demo', '--paused')
        self.cli('cycle')
        self.assertEqual((self.state()['mode'], self.state()['wave']), ('once', ['01', '02']))
        self.add_ticket('03')
        self.cli('tick'); self.cli('tick')
        ledger = self.ledger()
        self.assertEqual((ledger['01']['state'], ledger['02']['state']), ('working', 'working'))
        self.assertNotIn('03', ledger)
        self.build(); self.approve()
        self.assertEqual((self.ledger()['01']['state'], self.state()['mode']), ('merged', 'once'))
        self.assertNotIn('wave_ended_at', self.state())
        self.cli('report', '02', 'blocked', '--reason', 'unclear', '--slowed-by', 'spec', project=self.state_dir / 'worktrees' / 'demo-02')
        state = self.state()
        self.assertEqual(state['mode'], 'paused')
        self.assertTrue(state['wave_ended_at'])
        self.cli('tick')
        self.assertNotIn('03', self.ledger())
        self.cli('cycle')
        self.assertEqual((self.state()['mode'], self.state()['wave']), ('once', ['03']))
        self.assertNotIn('wave_ended_at', self.state())

    def test_wave_ticket_claimed_elsewhere_does_not_keep_the_wave_open(self):
        self.add_ticket('02')
        self.git('branch', 'factory/demo-02', 'build/demo')  # claimed by someone else
        self.cli('install', '--feature', 'demo', '--paused'); self.cli('cycle')
        self.assertEqual(self.ledger()['01']['state'], 'working')
        self.build(); self.approve()
        self.assertEqual(self.ledger()['02']['state'], 'needs-you')
        self.assertEqual(self.state()['mode'], 'paused')

    def test_wave_ticket_no_longer_ready_does_not_keep_the_wave_open(self):
        self.add_ticket('02')
        self.cli('install', '--feature', 'demo', '--paused'); self.set_state(concurrency=1); self.cli('cycle')
        self.add_ticket('02', status='needs-triage')
        self.build(); self.approve()
        self.assertNotIn('02', self.ledger())
        self.assertEqual(self.state()['mode'], 'paused')

    def test_pause_now_saves_the_ledger_when_orca_fails_to_confirm_a_stop(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        (self.orca_dir / 'show-fails').touch()
        out = self.cli('pause', '--now').stdout
        self.assertIn('worker term_1 did not stop; close it in Orca', out)
        self.assertEqual((self.ledger()['01']['state'], self.state()['mode']), ('interrupted', 'paused'))

    def test_precheck_runs_only_when_unpaused_with_work_to_do(self):
        self.add_ticket('02')
        self.cli('install', '--feature', 'demo', '--paused')
        self.cli('precheck', ok=False)  # paused, even with ready tickets
        self.cli('cycle')
        self.cli('precheck')  # once-wave still has ready or working tickets
        self.cli('pause')
        self.assertEqual(self.state()['mode'], 'draining')
        self.cli('precheck')  # working tickets to check
        self.cli('pause', '--now')
        self.cli('precheck', ok=False)
        self.add_ticket('03')
        self.set_state(mode='draining')
        self.cli('precheck', ok=False)  # draining starts nothing, so a ready ticket is no work
        self.set_state(mode='running')
        self.cli('precheck')

    def test_once_wave_respects_concurrency_and_pauses_when_both_merge(self):
        self.add_ticket('02')
        self.cli('install', '--feature', 'demo', '--paused'); self.set_state(concurrency=1)
        self.cli('cycle')
        self.assertEqual(sorted(self.ledger()), ['01'])
        self.cli('tick')
        self.assertEqual(sorted(self.ledger()), ['01'])  # concurrency 1: 02 waits for room
        self.finish('01')  # report's tick merges 01 and starts 02
        self.assertEqual((self.ledger()['02']['state'], self.state()['mode']), ('working', 'once'))
        self.finish('02')
        self.assertEqual(self.ledger()['02']['state'], 'merged')
        self.assertEqual(self.state()['mode'], 'paused')

    def test_precheck_skips_when_the_daily_cap_is_reached(self):
        self.add_ticket('02')
        self.cli('install', '--feature', 'demo'); self.set_state(daily_ticket_cap=1); self.cli('tick')
        self.finish('01')
        self.assertNotIn('02', self.ledger())
        self.cli('precheck', ok=False)  # 02 is ready but nothing may start today

    def test_precheck_runs_for_an_approved_ticket_waiting_to_merge(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.build(); self.git('checkout', '-q', 'main')
        self.approve(ok=False)  # refused on main, so the ticket stays approved
        self.assertEqual(self.ledger()['01']['state'], 'approved')
        self.cli('precheck')
        self.git('checkout', '-q', 'build/demo'); self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'merged')
        self.cli('precheck', ok=False)  # running, nothing ready, working or approved

    # --- ticket 06 ---
    def slow_gate(self, seconds):
        script = self.project / '.engineering-workflow' / 'gates.sh'
        script.write_text(f'echo "start $(python3 -c "import time;print(time.time())")" >> "{self.base}/runs.log"\n'
                          f'sleep {seconds}\n'
                          f'echo "end $(python3 -c "import time;print(time.time())")" >> "{self.base}/runs.log"\n'
                          'echo "GATES: PASS"\n')

    def start_gate(self, *args):
        return subprocess.Popen([sys.executable, '-B', str(ROOT / 'workflow.py'), 'factory', 'gate', *args,
                                 '--project', str(self.project)], env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)

    def test_concurrent_gates_take_turns_and_the_wait_is_recorded(self):
        self.cli('install', '--feature', 'demo', '--paused')
        (self.state_dir / 'ledger.json').write_text(json.dumps({'01': {
            'state': 'working', 'queue_wait_seconds': 0, 'gate_seconds': 0, 'history': []}}))
        self.slow_gate(1)
        first = self.start_gate('--ticket', '01')
        time.sleep(0.4)
        second = self.start_gate('--ticket', '01')
        self.assertEqual((first.wait(timeout=30), second.wait(timeout=30)), (0, 0))
        marks = [line.split() for line in (self.base / 'runs.log').read_text().splitlines()]
        self.assertEqual([m[0] for m in marks], ['start', 'end', 'start', 'end'])
        times = [float(m[1]) for m in marks]
        self.assertEqual(times, sorted(times))
        entry = self.ledger()['01']
        self.assertGreater(entry['queue_wait_seconds'], 0.2)
        self.assertGreater(entry['gate_seconds'], 0.9)

    def test_a_gate_that_dies_frees_its_slot(self):
        self.cli('install', '--feature', 'demo', '--paused')
        self.slow_gate(60)
        dying = self.start_gate()
        time.sleep(1)
        os.killpg(dying.pid, signal.SIGKILL); dying.wait()
        self.slow_gate(0)
        waiter = self.start_gate()
        self.assertEqual(waiter.wait(timeout=15), 0)

    def test_more_build_slots_let_gates_run_together(self):
        self.cli('install', '--feature', 'demo', '--paused')
        self.set_state(build_slots=2)
        self.slow_gate(1)
        runs = [self.start_gate(), self.start_gate()]
        begin = time.time()
        self.assertEqual([r.wait(timeout=30) for r in runs], [0, 0])
        self.assertLess(time.time() - begin, 1.9)

    def test_tick_merge_gate_goes_through_the_queue_and_records_times(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.slow_gate(1)
        self.git('commit', '-qam', 'Slow gate')
        self.git('merge', '-q', 'build/demo', cwd=self.worktree)
        holder = self.start_gate()
        time.sleep(0.4)
        self.cli('report', '01', 'approved', '--slowed-by', 'nothing', project=self.worktree)
        holder.wait(timeout=30)
        entry = self.ledger()['01']
        self.assertEqual(entry['state'], 'merged')
        self.assertGreater(entry['queue_wait_seconds'], 0.3)
        self.assertGreater(entry['gate_seconds'], 0.9)

    # --- ticket 03 ---
    def add_ticket(self, number, blocked='None', status='ready-for-agent'):
        text = TICKET.replace('ready-for-agent', status).replace('None (can start immediately)', blocked)
        (self.project / '.scratch' / 'demo' / 'issues' / f'{number}-t{number}.md').write_text(text)
        self.git('add', '-A'); self.git('commit', '-qm', f'ticket {number}')

    def set_state(self, **values):
        data = self.state(); data.update(values)
        (self.state_dir / 'state.json').write_text(json.dumps(data))

    def launches(self): return [c for c in self.orca_calls() if c[:2] == ['agent', 'launch']]

    def finish(self, number):
        worktree = self.state_dir / 'worktrees' / f'demo-{number}'
        (worktree / f'{number}.txt').write_text('x\n')
        self.git('add', '-A', cwd=worktree); self.git('commit', '-qm', 'work', cwd=worktree)
        self.cli('report', number, 'approved', '--slowed-by', 'nothing', project=worktree)

    def test_ticket_waits_for_blockers_to_merge_and_unblocked_tickets_start_in_order(self):
        self.add_ticket('02', blocked='01'); self.add_ticket('03', blocked='01, 02'); self.add_ticket('04')
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.assertEqual(sorted(self.ledger()), ['01', '04'])
        self.assertEqual([c[c.index('--worktree') + 1][-7:] for c in self.launches()], ['demo-01', 'demo-04'])
        self.finish('01'); self.assertEqual(sorted(self.ledger()), ['01', '02', '04'])
        self.finish('02'); self.assertIn('03', self.ledger())

    def test_resolved_manual_blocker_counts_as_merged_but_open_one_does_not(self):
        self.add_ticket('02', status='resolved'); self.add_ticket('03', status='needs-triage')
        self.add_ticket('04', blocked='02'); self.add_ticket('05', blocked='03')
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.assertEqual(sorted(self.ledger()), ['01', '04'])

    def test_prose_numbers_after_a_blocker_are_not_blockers(self):
        self.add_ticket('02', status='resolved'); self.add_ticket('10', status='needs-triage')
        self.add_ticket('03', blocked='02 (needs 10 users)')
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.assertIn('03', self.ledger())

    def test_bypass_launch_stops_further_claims_in_the_same_tick(self):
        (self.orca_dir / 'bypass').touch(); self.add_ticket('02')
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.assertEqual(len(self.launches()), 1)
        self.assertEqual((sorted(self.ledger()), self.state()['mode']), (['01'], 'paused'))

    def test_concurrency_limits_working_tickets_and_more_start_as_others_finish(self):
        for number in ('02', '03', '04'): self.add_ticket(number)
        self.cli('install', '--feature', 'demo'); self.set_state(concurrency=2)
        self.cli('tick'); self.assertEqual(sorted(self.ledger()), ['01', '02'])
        self.cli('tick'); self.assertEqual(sorted(self.ledger()), ['01', '02'])
        self.finish('01'); self.assertEqual(sorted(self.ledger()), ['01', '02', '03'])

    def test_daily_ticket_cap_counts_todays_starts(self):
        self.add_ticket('02'); self.add_ticket('03')
        self.cli('install', '--feature', 'demo'); self.set_state(daily_ticket_cap=2)
        self.cli('tick'); self.cli('tick')
        self.assertEqual(sorted(self.ledger()), ['01', '02'])
        ledger = self.ledger(); ledger['01']['started_at'] = '2000-01-01T00:00:00+00:00'; ledger['01']['state'] = 'merged'
        (self.state_dir / 'ledger.json').write_text(json.dumps(ledger))
        self.cli('tick'); self.assertEqual(sorted(self.ledger()), ['01', '02', '03'])

    def test_two_simultaneous_ticks_launch_each_ticket_once(self):
        self.add_ticket('02'); self.cli('install', '--feature', 'demo')
        argv = [sys.executable, '-B', str(ROOT / 'workflow.py'), 'factory', 'tick', '--project', str(self.project)]
        procs = [subprocess.Popen(argv, env=self.env, stdout=subprocess.DEVNULL) for _ in range(2)]
        self.assertEqual([p.wait() for p in procs], [0, 0])
        self.assertEqual(len(self.launches()), 2)
        self.assertEqual(sorted(c[c.index('--worktree') + 1][-7:] for c in self.launches()), ['demo-01', 'demo-02'])
        self.assertEqual(sorted(self.ledger()), ['01', '02'])

    def test_leftover_claim_branch_parks_the_ticket_once_and_requeue_builds_on_it(self):
        self.add_ticket('02'); self.cli('install', '--feature', 'demo')
        self.git('commit', '--allow-empty', '-qm', 'elsewhere'); self.git('branch', 'factory/demo-01', 'HEAD')
        sha = self.git('rev-parse', 'factory/demo-01')
        self.cli('tick'); self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason'], entry['branch']),
                         ('needs-you', 'claim branch exists without a ledger entry', 'factory/demo-01'))
        self.assertEqual([h['state'] for h in entry['history']], ['needs-you'])
        self.assertEqual(self.ledger()['02']['state'], 'working')
        self.assertEqual(self.git('rev-parse', 'factory/demo-01'), sha)
        self.assertFalse(self.worktree.exists())
        self.cli('requeue', '01')
        self.assertIn('relaunched 01 in its worktree', self.cli('tick').stdout)
        self.assertEqual((self.ledger()['01']['state'], self.git('rev-parse', 'HEAD', cwd=self.worktree)), ('working', sha))

    def test_claim_branch_is_pushed_when_a_remote_exists_and_a_rejected_push_means_claimed(self):
        remote = self.base / 'remote.git'; self.git('init', '-q', '--bare', str(remote))
        self.git('remote', 'add', 'origin', str(remote))
        self.add_ticket('02'); self.cli('install', '--feature', 'demo')
        other = self.git('commit-tree', 'build/demo^{tree}', '-m', 'other claim')  # unrelated history
        self.git('push', '-q', 'origin', f'{other}:refs/heads/factory/demo-01')  # someone else got there first
        self.cli('tick')
        self.assertEqual(sorted(self.ledger()), ['02'])
        self.assertEqual(self.git('branch', '--list', 'factory/demo-01'), '')
        self.git('--git-dir', str(remote), 'rev-parse', '--verify', 'refs/heads/factory/demo-02')


    # --- ticket 09 ---

    def final_reviews(self): return [c for c in self.launches() if f'path:{self.project}' in c]

    def test_final_review_runs_once_in_the_integration_checkout_then_pauses(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.build(); self.approve()
        self.assertEqual(self.ledger()['01']['state'], 'merged')
        reviews = self.final_reviews()
        self.assertEqual(len(reviews), 1)
        prompt = reviews[0][reviews[0].index('--prompt') + 1]
        self.assertIn('Use the ew-factory skill (final review brief) for demo on build/demo', prompt)
        self.assertIn(str(self.state_dir / 'final-review.md'), prompt)
        state = self.state()
        self.assertEqual((state['final_review'], state['final_review_handle'], state['mode']),
                         ('dispatched', 'term_2', 'paused'))  # the fake numbers each launch
        self.cli('resume'); self.cli('tick')
        self.assertEqual(len(self.final_reviews()), 1)

    def test_final_review_waits_while_tickets_are_ready_or_working(self):
        self.add_ticket('02', blocked='01'); self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.cli('tick')
        self.assertEqual(self.final_reviews(), [])
        self.finish('01')
        self.assertEqual((self.ledger()['02']['state'], self.state()['mode']), ('working', 'running'))
        self.assertEqual(self.final_reviews(), [])

    def test_requeued_ticket_held_by_the_daily_cap_blocks_the_final_review(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.cli('pause', '--now')
        self.cli('requeue', '01'); self.set_state(daily_ticket_cap=1)
        self.cli('resume')
        self.assertEqual((self.ledger()['01']['state'], self.state()['mode']), ('ready', 'running'))
        self.assertEqual(self.final_reviews(), [])

    def test_held_high_radius_ticket_blocks_the_final_review_until_approve_merges_it(self):
        self.set_radius('**Blast radius:** high\n')
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build(); self.approve()
        self.assertEqual((self.ledger()['01']['state'], self.state()['mode']), ('needs-you', 'running'))
        self.assertEqual(self.final_reviews(), [])
        self.assertIn('final review waits on 1 parked ticket', self.cli('status').stdout)
        self.cli('precheck', ok=False)
        self.cli('approve', '01')
        self.assertEqual(self.ledger()['01']['state'], 'merged')
        self.cli('precheck')
        self.cli('tick')
        self.assertEqual((len(self.final_reviews()), self.state()['mode']), (1, 'paused'))
        self.set_state(mode='running')
        self.cli('precheck', ok=False)

    def test_no_final_review_when_no_ticket_was_ever_started(self):
        (self.project / '.scratch' / 'demo' / 'issues' / '01-thing.md').write_text(TICKET.replace('ready-for-agent', 'needs-triage'))
        self.git('commit', '-qam', 'triage'); self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.assertEqual((self.launches(), self.state()['mode']), ([], 'running'))

    def test_failed_final_review_launch_still_pauses_without_dispatching(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build()
        (self.orca_dir / 'launch-fails').touch()
        out = self.approve().stdout
        self.assertIn('final review launch failed', out)
        self.assertEqual((self.state()['final_review'], self.state()['mode']), ('not-started', 'paused'))

    def test_status_shows_the_final_review_file_once_written(self):
        self.cli('install', '--feature', 'demo')
        self.assertNotIn('final review', self.cli('status').stdout)
        (self.state_dir / 'final-review.md').write_text('findings\n')
        self.assertIn(f'final review: {self.state_dir / "final-review.md"}', self.cli('status').stdout)

    # --- climb and queued features ---

    def add_climb(self, status='ready-for-agent', radius='low'):
        (self.project / '.scratch' / 'demo' / 'climb.md').write_text(
            f'# Climb: faster build\n\n**Status:** {status}\n\n**Blast radius:** {radius}\n\n'
            '**Metric:** `python3 bench.py` (ms, lower is better)\n\n**Target:** <= 50\n')
        self.git('add', '-A'); self.git('commit', '-qm', 'climb file')

    def add_feature(self, name):
        issues = self.project / '.scratch' / name / 'issues'; issues.mkdir(parents=True)
        (issues / '01-next.md').write_text(TICKET.replace('01: Thing', '01: Next'))
        self.git('add', '-A'); self.git('commit', '-qm', f'{name} tickets')

    def prompt(self, launch): return launch[launch.index('--prompt') + 1]

    def test_approved_climb_runs_after_every_ticket_merges_then_the_final_review(self):
        self.add_climb(); self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.build(); out = self.approve().stdout
        self.assertIn('climbing demo on factory/demo-climb', out)
        self.assertEqual(self.final_reviews(), [])
        climb_tree = self.state_dir / 'worktrees' / 'demo-climb'
        brief = self.prompt(self.launches()[-1])
        self.assertIn(f'(climb brief). Climb file: {climb_tree / ".scratch" / "demo" / "climb.md"}', brief)
        self.assertIn(f"report climb approved --detach --project '{climb_tree}'", brief)
        self.assertEqual(self.ledger()['climb']['state'], 'working')
        self.cli('precheck')
        (climb_tree / 'faster.txt').write_text('x\n')
        self.git('add', '-A', cwd=climb_tree); self.git('commit', '-qm', 'round 1: 80 -> 45 ms', cwd=climb_tree)
        self.cli('report', 'climb', 'approved', '--slowed-by', 'nothing', project=climb_tree)
        self.assertEqual(self.ledger()['climb']['state'], 'merged')
        self.assertTrue((self.project / 'faster.txt').is_file())
        self.assertEqual((len(self.final_reviews()), self.state()['mode']), (1, 'paused'))

    def test_unapproved_climb_file_is_skipped(self):
        self.add_climb(status='needs-triage'); self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.build(); self.approve()
        self.assertNotIn('climb', self.ledger())
        self.assertEqual(len(self.final_reviews()), 1)

    def test_blocked_climb_waits_on_you_and_requeue_relaunches_it(self):
        self.add_climb(); self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build(); self.approve()
        climb_tree = self.state_dir / 'worktrees' / 'demo-climb'
        self.cli('report', 'climb', 'blocked', '--reason', 'no improvement', '--slowed-by', 'nothing',
                 project=climb_tree)
        self.assertEqual((self.ledger()['climb']['state'], self.final_reviews()), ('needs-you', []))
        self.assertIn('final review waits on 1 parked ticket', self.cli('status').stdout)
        self.cli('requeue', 'climb')
        self.assertIn('relaunched climb in its worktree', self.cli('tick').stdout)

    def test_high_radius_climb_waits_for_approval_before_merging(self):
        self.add_climb(radius='high'); self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.build(); self.approve()
        climb_tree = self.state_dir / 'worktrees' / 'demo-climb'
        (climb_tree / 'faster.txt').write_text('x\n')
        self.git('add', '-A', cwd=climb_tree); self.git('commit', '-qm', 'round 1', cwd=climb_tree)
        self.cli('report', 'climb', 'approved', '--slowed-by', 'nothing', project=climb_tree)
        self.assertEqual(self.ledger()['climb']['reason'], 'high blast radius: waiting for approval')
        self.cli('approve', 'climb'); self.cli('tick')
        self.assertEqual(len(self.final_reviews()), 1)

    def test_queued_feature_starts_after_the_final_review_and_pings_each_merge(self):
        self.add_feature('next'); self.cli('install', '--feature', 'demo')
        self.assertEqual(self.cli('queue', 'next').stdout.strip(), 'next: next')
        self.assertIn('next: next', self.cli('status').stdout)
        self.cli('tick'); self.build()
        out = self.approve().stdout
        self.assertIn('demo done; now building next', out)
        review = self.prompt(self.final_reviews()[0])
        tip = self.git('rev-parse', 'build/demo~0')
        self.assertIn(f'on build/demo up to commit {tip}', review)
        self.assertIn(str(self.state_dir / 'final-review.md'), review)
        state = self.state()
        self.assertEqual((state['feature'], state['mode'], state['next_features'], state['done_features'],
                          state['final_review'], state['past_reviews']),
                         ('next', 'running', [], ['demo'], 'not-started', ['term_2']))
        self.assertEqual(list(self.state_dir.glob('ledger-demo-*.json'))[0].name[:12], 'ledger-demo-')
        self.assertEqual((sorted(self.ledger()), self.ledger()['01']['branch']), (['01'], 'factory/next-01'))
        pings = [c for c in self.cards() if c[0] == f'path:{self.project}']
        self.assertIn('BUILT: feature demo built, climbed and sent to final review; now building next', pings[-1])
        tree = self.state_dir / 'worktrees' / 'next-01'
        (tree / 'n.txt').write_text('x\n')
        self.git('add', '-A', cwd=tree); self.git('commit', '-qm', 'next work', cwd=tree)
        self.cli('report', '01', 'approved', '--slowed-by', 'nothing', project=tree)
        pings = [c for c in self.cards() if c[0] == f'path:{self.project}']
        self.assertIn('BUILT: next 01 merged into build/demo', pings[-1])
        self.assertIn(str(self.state_dir / 'final-review-next.md'), self.prompt(self.final_reviews()[-1]))
        self.assertEqual(self.state()['mode'], 'paused')  # nothing more queued

    def test_daily_ticket_cap_still_counts_todays_starts_once_a_queued_feature_takes_over(self):
        self.add_feature('next'); self.cli('install', '--feature', 'demo'); self.set_state(daily_ticket_cap=1)
        self.cli('queue', 'next'); self.cli('tick'); self.build()
        self.assertIn('demo done; now building next', self.approve().stdout)
        self.assertEqual((self.state()['feature'], self.ledger()), ('next', {}))  # today's one start is spent
        self.cli('precheck', ok=False)
        self.set_state(carried_starts={'2000-01-01': 1})  # another day
        self.cli('tick'); self.assertEqual(self.ledger()['01']['branch'], 'factory/next-01')

    def test_queue_refuses_unknown_or_duplicate_features_and_ticket_worktrees(self):
        self.add_feature('next'); self.cli('install', '--feature', 'demo')
        self.assertIn('No ticket files in .scratch/nope/issues/', self.cli('queue', 'nope', ok=False).stderr)
        self.assertIn('demo is already in this factory', self.cli('queue', 'demo', ok=False).stderr)
        self.cli('queue', 'next')
        self.assertIn('next is already in this factory', self.cli('queue', 'next', ok=False).stderr)
        self.cli('tick')
        self.assertIn('not a ticket worktree', self.cli('queue', 'next', project=self.worktree, ok=False).stderr)

    def test_uninstall_stops_workers_archives_the_ledger_and_a_new_feature_starts_fresh(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.cli('uninstall')
        calls = self.orca_calls()
        self.assertLess(calls.index(['terminal', 'close', '--terminal', 'term_1', '--json']),
                        calls.index(['automations', 'remove', 'auto_1', '--json']))
        self.assertFalse((self.state_dir / 'state.json').exists())
        self.assertFalse((self.state_dir / 'ledger.json').exists())
        [kept] = self.state_dir.glob('ledger-*.json')
        self.assertRegex(kept.name, r'^ledger-demo-\d{8}T\d{6}\.json$')
        self.assertEqual(json.loads(kept.read_text())['01']['state'], 'interrupted')
        self.assertTrue(self.worktree.exists())
        self.git('rev-parse', '--verify', 'refs/heads/factory/demo-01')
        self.assertIn('No factory installed', self.cli('status', ok=False).stderr)
        issues = self.project / '.scratch' / 'next' / 'issues'; issues.mkdir(parents=True)
        (issues / '01-next.md').write_text(TICKET); self.git('add', '-A'); self.git('commit', '-qm', 'next feature')
        self.cli('install', '--feature', 'next'); self.cli('tick')
        self.assertEqual({t: e['branch'] for t, e in self.ledger().items()}, {'01': 'factory/next-01'})

    def test_uninstall_still_succeeds_when_the_heartbeat_is_already_gone(self):
        self.cli('install', '--feature', 'demo'); (self.orca_dir / 'automation-gone').touch()
        self.assertIn('heartbeat', self.cli('uninstall').stdout)
        self.assertFalse((self.state_dir / 'state.json').exists())

    def test_workers_launch_with_the_ew_factory_worker_brief(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        prompt = self.launches()[0][self.launches()[0].index('--prompt') + 1]
        self.assertTrue(prompt.startswith('Use the ew-factory skill (worker brief). '
                                          f'Ticket: {self.worktree / ".scratch/demo/issues/01-thing.md"}. Ticket id: 01. Gate: '), prompt)
        self.assertIn(f"gate --ticket 01 --project '{self.worktree}'", prompt)
        self.assertIn(f"report 01 approved --detach --project '{self.worktree}'", prompt)
        lock = json.loads((ROOT / 'workflow.lock.json').read_text())
        self.assertEqual(lock['skills']['ew-factory'], 'skills/factory')
    def test_worker_handle_is_read_from_a_legacy_launch_wrapped_reply(self):
        (self.orca_dir / 'legacy-launch').touch()
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.assertEqual(self.ledger()['01']['worker_handle'], 'term_1')
    # --- ticket 04 ---
    def set_radius(self, line):
        ticket = self.project / '.scratch' / 'demo' / 'issues' / '01-thing.md'
        ticket.write_text(TICKET.replace('**Blast radius:** low\n', line))
        self.git('commit', '-qam', 'set blast radius')

    def cards(self):
        return [c[3:] for c in self.orca_calls() if c[:2] == ['worktree', 'set']]

    def held_card(self, reason, worktree=None):
        return [f'path:{worktree or self.worktree}', '--workspace-status', 'in-review',
                '--comment', f'NEEDS YOU: {reason}', '--unread', '--json']

    def last_card(self, worktree):
        return [c for c in self.cards() if c[0] == f'path:{worktree}'][-1]

    def test_high_missing_or_unknown_blast_radius_passes_gate_then_waits_for_approve(self):
        issues = self.project / '.scratch' / 'demo' / 'issues'
        radius = '**Blast radius:** low\n'
        (issues / '01-thing.md').write_text(TICKET.replace(radius, '**Blast radius:** high\n'))
        (issues / '02-other.md').write_text(TICKET.replace('01: Thing', '02: Other').replace(radius, ''))
        odd = TICKET.replace('01: Thing', '03: Odd').replace(radius, 'Blast radius: huge\n')
        (issues / '03-odd.md').write_text(odd)
        self.git('add', '-A'); self.git('commit', '-qm', 'radius tickets')
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        before = self.git('rev-parse', 'build/demo')
        hold = 'high blast radius: waiting for approval'
        worktrees = {n: self.state_dir / 'worktrees' / f'demo-{n}' for n in ('01', '02', '03')}
        for n, worktree in worktrees.items():  # each report's tick holds this ticket and starts the next
            (worktree / f'{n}.txt').write_text('built\n')
            self.git('add', '-A', cwd=worktree); self.git('commit', '-qm', f'Build {n}', cwd=worktree)
            self.cli('report', n, 'approved', '--slowed-by', 'nothing', project=worktree)
            self.assertEqual((self.ledger()[n]['state'], self.ledger()[n]['reason']), ('needs-you', hold))
            self.assertEqual(self.last_card(worktree), self.held_card(hold, worktree))
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)
        for n, worktree in worktrees.items():
            self.assertIn(f'merged {n} into build/demo', self.cli('approve', n).stdout)
            self.assertEqual([h['state'] for h in self.ledger()[n]['history']],
                             ['working', 'approved', 'needs-you', 'merged'])
            self.assertEqual(len(self.git('rev-list', '--parents', '-n', '1', 'build/demo').split()), 3)
            self.assertEqual(self.git('show', f'build/demo:{n}.txt'), 'built')
            self.assertFalse(worktree.exists())
            self.assertEqual(self.last_card(worktree),
                             [f'path:{worktree}', '--workspace-status', 'completed', '--json'])

    def test_cards_show_in_progress_then_needs_you_and_medium_merges_automatically(self):
        self.set_radius('**Blast radius:** medium\n')
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.assertEqual(self.cards(), [[f'path:{self.worktree}', '--workspace-status', 'in-progress', '--json']])
        self.cli('tick')
        self.assertEqual(len(self.cards()), 1)  # unchanged state: no new card call
        self.build('README.md', 'ticket side\n')
        (self.project / 'README.md').write_text('integration side\n')
        self.git('commit', '-qam', 'Integration change')
        self.approve()
        self.assertEqual(self.ledger()['01']['state'], 'needs-you')
        self.assertEqual(self.cards()[-1], self.held_card('merge conflict'))
        self.git('merge', '-q', '--no-edit', '-X', 'theirs', 'build/demo', cwd=self.worktree)
        self.cli('approve', '01')
        self.assertEqual(self.ledger()['01']['state'], 'merged')
        self.assertEqual(self.cards()[-1], [f'path:{self.worktree}', '--workspace-status', 'completed', '--json'])

    def test_low_ticket_merges_automatically_with_a_completed_card(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build(); self.approve()
        self.assertEqual(self.ledger()['01']['state'], 'merged')
        self.assertEqual([c[2] for c in self.cards()], ['in-progress', 'completed'])

    def test_blocked_report_shows_needs_you_card(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.cli('report', '01', 'blocked', '--reason', 'needs an API decision', '--slowed-by', 'spec',
                 project=self.worktree)
        self.assertEqual(self.cards()[-1], self.held_card('needs an API decision'))

    def test_approve_refuses_tickets_their_worker_did_not_approve(self):
        second = self.project / '.scratch' / 'demo' / 'issues' / '02-other.md'
        second.write_text(TICKET.replace('01: Thing', '02: Other'))
        self.git('add', '-A'); self.git('commit', '-qm', 'second ticket')
        self.cli('install', '--feature', 'demo')
        before = self.git('rev-parse', 'build/demo')
        (self.orca_dir / 'launch-fails').touch(); self.cli('tick'); (self.orca_dir / 'launch-fails').unlink()
        self.cli('requeue', '02'); self.cli('tick')  # both launches failed; 02 now gets a worker
        self.cli('report', '02', 'blocked', '--reason', 'needs an API decision', '--slowed-by', 'spec',
                 project=self.state_dir / 'worktrees' / 'demo-02')
        for n in ('01', '02'):
            refused = self.cli('approve', n, ok=False).stderr
            self.assertIn(f'Ticket {n} was not approved by its worker; requeue it instead', refused)
            self.assertEqual(self.ledger()[n]['state'], 'needs-you')
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)

    def test_merged_ticket_whose_card_failed_is_not_retried_after_its_worktree_is_gone(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build()
        (self.orca_dir / 'card-fails').touch()
        self.assertIn('card for 01 not updated', self.approve().stdout)
        self.assertEqual(self.ledger()['01']['state'], 'merged')
        (self.orca_dir / 'card-fails').unlink()
        calls = len(self.cards())
        self.assertNotIn('not updated', self.cli('tick').stdout)
        self.assertEqual(len(self.cards()), calls)

    def test_failed_card_update_does_not_abort_the_tick_and_is_retried(self):
        self.cli('install', '--feature', 'demo')
        (self.orca_dir / 'card-fails').touch()
        out = self.cli('tick').stdout
        self.assertIn('claimed 01', out)
        self.assertIn('card for 01 not updated', out)
        self.assertEqual(self.ledger()['01']['state'], 'working')
        (self.orca_dir / 'card-fails').unlink()
        self.assertNotIn('not updated', self.cli('tick').stdout)
        self.assertEqual([c[2] for c in self.cards()], ['in-progress', 'in-progress'])

    def test_approve_reruns_the_gate_and_keeps_a_failing_ticket_in_needs_you(self):
        self.set_radius('**Blast radius:** high\n')
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build(); self.approve()
        (self.project / '.engineering-workflow' / 'gates.sh').write_text('echo "GATES: FAIL tests"\n')
        self.git('commit', '-qam', 'Break the gate')
        before = self.git('rev-parse', 'build/demo')
        refused = self.cli('approve', '01', ok=False).stdout
        self.assertIn('01 needs you: gates failed on the ticket branch', refused)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('needs-you', 'gates failed on the ticket branch'))
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)
        self.assertEqual(self.cards()[-1], self.held_card('gates failed on the ticket branch'))

    def test_approve_and_requeue_refuse_tickets_in_other_states(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.assertIn('not waiting for you', self.cli('approve', '01', ok=False).stderr)
        self.assertIn('cannot be requeued', self.cli('requeue', '01', ok=False).stderr)
        self.assertIn('cannot be requeued', self.cli('requeue', '07', ok=False).stderr)
        self.assertEqual(self.ledger()['01']['state'], 'working')

    def test_requeued_ticket_relaunches_in_its_existing_worktree(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build()
        self.cli('report', '01', 'blocked', '--reason', 'needs an API decision', '--slowed-by', 'spec',
                 project=self.worktree)
        tip = self.git('rev-parse', 'factory/demo-01')
        self.cli('requeue', '01')
        self.assertEqual(self.ledger()['01']['state'], 'ready')
        self.assertIn('01 ready factory/demo-01', self.cli('status').stdout)
        relaunched = self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual([h['state'] for h in entry['history']], ['working', 'needs-you', 'ready', 'working'])
        self.assertEqual((entry['branch'], entry['worktree'], entry['turns']),
                         ('factory/demo-01', str(self.worktree), 0))
        self.assertEqual(self.git('rev-parse', 'factory/demo-01'), tip)
        branches = self.git('branch', '--list', '--format=%(refname:short)', 'factory/*').split()
        self.assertEqual(branches, ['factory/demo-01'])
        launches = [c for c in self.orca_calls() if c[:2] == ['agent', 'launch']]
        self.assertEqual([c[c.index('--worktree') + 1] for c in launches], [f'path:{self.worktree}'] * 2)
        self.assertNotIn('claimed', relaunched.stdout)
        self.assertIn('relaunched 01 in its worktree', relaunched.stdout)
        self.assertEqual(self.cards()[-1],
                         [f'path:{self.worktree}', '--workspace-status', 'in-progress', '--json'])


    def test_requeued_ticket_counts_as_work_for_precheck(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.cli('report', '01', 'blocked', '--reason', 'needs an API decision', '--slowed-by', 'spec',
                 project=self.worktree)
        self.cli('precheck', ok=False)
        self.cli('requeue', '01')
        self.cli('precheck')

    def test_requeued_ticket_waits_while_draining_or_paused_and_joins_the_next_wave_or_resume(self):
        second = self.project / '.scratch' / 'demo' / 'issues' / '02-other.md'
        second.write_text(TICKET.replace('01: Thing', '02: Other'))
        self.git('add', '-A'); self.git('commit', '-qm', 'second ticket')
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        other = self.state_dir / 'worktrees' / 'demo-02'
        blocked = ('blocked', '--reason', 'needs an API decision', '--slowed-by', 'spec')
        self.cli('report', '02', *blocked, project=other)
        self.cli('requeue', '02')
        self.assertEqual(self.cli('pause').stdout.strip(), 'factory draining')  # 01 is still working
        self.cli('tick')
        self.assertEqual(self.ledger()['02']['state'], 'ready')
        self.cli('report', '01', *blocked, project=self.worktree)
        self.assertEqual(self.state()['mode'], 'paused')
        self.assertEqual(self.ledger()['02']['state'], 'ready')
        self.cli('requeue', '01')
        self.cli('precheck', ok=False)
        self.cli('cycle')
        self.assertEqual(self.state()['wave'], ['01', '02'])
        self.assertEqual({n: e['state'] for n, e in self.ledger().items()}, {'01': 'working', '02': 'working'})
        self.cli('report', '01', *blocked, project=self.worktree)
        self.cli('report', '02', *blocked, project=other)
        self.assertEqual(self.state()['mode'], 'paused')
        self.cli('requeue', '02')
        self.assertIn('relaunched 02 in its worktree', self.cli('resume').stdout)
        self.assertEqual(self.ledger()['02']['state'], 'working')
        launches = [c[c.index('--worktree') + 1] for c in self.orca_calls() if c[:2] == ['agent', 'launch']]
        self.assertEqual(launches.count(f'path:{other}'), 3)
        self.assertEqual(self.git('branch', '--list', '--format=%(refname:short)', 'factory/*').split(),
                         ['factory/demo-01', 'factory/demo-02'])

    # --- ticket 07 ---
    def test_dead_worker_that_never_reported_is_interrupted_and_an_orca_error_skips_the_check(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        (self.orca_dir / 'show-fails').touch()
        self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'working')
        (self.orca_dir / 'show-fails').unlink()
        (self.orca_dir / 'dead-term_1').touch()  # the worker died
        self.assertIn('interrupted 01: worker exited without reporting', self.cli('tick').stdout)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('interrupted', 'worker exited without reporting'))
        self.assertTrue(self.worktree.exists())

    def hook(self, event, cwd=None, **data):
        payload = {'hook_event_name': event, 'cwd': str(cwd or self.worktree), **data}
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'workflow.py'), 'hook', '--platform', 'claude'],
                                input=json.dumps(payload), text=True, capture_output=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def bash(self, command, cwd=None):
        return self.hook('PreToolUse', cwd, tool_name='Bash', tool_input={'command': command})

    def denied(self, reason):
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                       'permissionDecisionReason': reason}}

    def test_turn_cap_refuses_every_tool_then_tick_caps_and_requeue_starts_fresh(self):
        self.cli('install', '--feature', 'demo'); self.set_state(max_turns=2); self.cli('tick')
        read = {'tool_name': 'Read', 'tool_input': {'file_path': 'README.md'}}
        self.assertEqual(self.hook('PreToolUse', **read), {})
        self.hook('PostToolUse', **read); self.hook('PostToolUse', **read)
        capped = self.denied('Factory turn cap reached; run factory report 01 blocked')
        self.assertEqual(self.hook('PreToolUse', **read), capped)
        self.assertEqual(self.bash('git status'), capped)
        self.build('half.txt', 'half done\n')
        self.assertIn('01 capped: turn cap', self.cli('tick').stdout)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason'], entry['turns']), ('capped', 'turn cap', 2))
        self.assertIn(['terminal', 'close', '--terminal', 'term_1', '--json'], self.orca_calls())
        self.assertEqual(self.git('show', 'factory/demo-01:half.txt'), 'half done')
        self.cli('requeue', '01')
        self.assertIn('relaunched 01 in its worktree', self.cli('tick').stdout)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['turns'], entry['worker_handle']), ('working', 0, 'term_2'))
        self.assertEqual(self.launches()[-1][self.launches()[-1].index('--worktree') + 1], f'path:{self.worktree}')
        self.assertEqual(self.hook('PreToolUse', **read), {})
        self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'working')

    def test_at_the_turn_cap_only_the_workers_own_blocked_report_gets_through(self):
        self.add_ticket('02'); self.cli('install', '--feature', 'demo'); self.set_state(max_turns=1); self.cli('tick')
        self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'README.md'})
        capped = self.denied('Factory turn cap reached; run factory report 01 blocked')
        workflow = str(ROOT / 'workflow.py')
        def report(*args, python=sys.executable, script=workflow):  # the form factory.workflow_command emits
            return shlex.join([python, script, 'factory', 'report', *args])
        own = report('01', 'blocked')
        allowed = [own, report('01', 'blocked', '--reason', 'needs an API decision', '--slowed-by', "spec's gap"),
                   report('01', 'blocked', '--detach', '--project', str(self.worktree), '--reason', 'stuck')]
        for command in allowed:
            with self.subTest(allowed=command): self.assertEqual(self.bash(command), {})
        self.assertEqual(self.hook('PreToolUse', tool_name='exec_command',
                                   tool_input={'cmd': own, 'workdir': str(self.worktree)}), {})
        link = self.base / 'python3'; link.symlink_to(sys.executable)
        denied = [report('02', 'blocked'), report('01', 'approved'), own + '; rm -rf x', own + ' && rm -rf x',
                  own + ' --reason $(id)', own + ' --reason `id`', own + '\nrm -rf x', own + ' extra',
                  own + ' --allow-bypass', own + ' --reason a --reason b', own + ' --reason', own + ' --reason=x',
                  own + ' | tee x', own + ' > x', own + ' "unclosed', own + ' --reason "needs a decision"',
                  own + ' --reason *', own + ' --reason {a,b}', own + ' --reason ~', own + ' #x',
                  own.replace(' 01 ', '\t01 '), own.replace(' 01 ', '\x0b01 '), own + ' ',
                  report('01', 'blocked', python='python3'), report('01', 'blocked', python=str(link)),
                  report('01', 'blocked', script=str(self.worktree / 'workflow.py')),
                  report('01', 'blocked', script='workflow.py'), report('01', 'blocked', script=str(ROOT / 'other.py')),
                  f'sh {shlex.quote(workflow)} factory report 01 blocked',
                  report('01', 'blocked', '--project', str(self.project)),
                  report('01', 'blocked', '--project', str(self.state_dir / 'worktrees' / 'demo-02')),
                  report('01', 'blocked', '--project', '.')]
        for command in denied:
            with self.subTest(denied=command): self.assertEqual(self.bash(command), capped)
        for tool, given in (('Read', {'file_path': 'README.md'}), ('Write', {'command': own}),
                            ('Bash', {'command': own, 'cmd': own}),
                            ('exec_command', {'cmd': own, 'workdir': str(self.project)}),
                            ('exec_command', {'cmd': own, 'cwd': 'elsewhere'})):
            with self.subTest(tool=tool, given=given):
                self.assertEqual(self.hook('PreToolUse', tool_name=tool, tool_input=given), capped)
        brief = report('01', 'blocked', '--project', str(self.worktree), '--reason', 'stuck on it', '--slowed-by', 'spec')
        self.assertEqual(self.bash(brief), {})
        run = subprocess.run(shlex.split(brief), cwd=self.worktree, text=True, capture_output=True, env=self.env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason'], entry['slowed_by']), ('needs-you', 'stuck on it', 'spec'))

    def test_hooks_outside_a_ticket_worktree_neither_count_nor_cap(self):
        self.cli('install', '--feature', 'demo'); self.set_state(max_turns=1); self.cli('tick')
        read = {'tool_name': 'Read', 'tool_input': {'file_path': 'README.md'}}
        for _ in range(2): self.hook('PostToolUse', self.project, **read)
        self.assertEqual(self.hook('PreToolUse', self.project, **read), {})
        self.assertFalse((self.project / '.engineering-workflow-state' / 'factory-turns.json').exists())
        self.cli('tick')
        self.assertEqual((self.ledger()['01']['state'], self.ledger()['01']['turns']), ('working', 0))

    def test_guard_ask_becomes_deny_in_a_ticket_worktree_and_tick_parks_it_as_permission_needed(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        withheld = self.denied('Claude Guard requires local review of this command; command text withheld.')
        asked = {'hookSpecificOutput': {**withheld['hookSpecificOutput'], 'permissionDecision': 'ask'}}
        self.assertEqual(self.bash('git reset --hard', self.project), asked)  # outside: unchanged
        self.assertEqual(self.bash('rm -rf /'), withheld)  # Guard deny stays deny ...
        self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'working')  # ... and parks nothing
        self.assertEqual(self.bash('git reset --hard'), withheld)
        self.assertIn('01 needs-you: permission needed', self.cli('tick').stdout)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('needs-you', 'permission needed'))
        self.assertIn(['terminal', 'close', '--terminal', 'term_1', '--json'], self.orca_calls())
        self.assertEqual(self.cards()[-1], self.held_card('permission needed'))
        self.assertTrue(self.worktree.exists())

    def test_unreadable_factory_files_in_a_worktree_refuse_every_tool_call(self):
        self.cli('install', '--feature', 'demo'); self.set_state(max_turns=1); self.cli('tick')
        self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'README.md'})
        (self.state_dir / 'state.json').write_text('{not json')
        refused = self.denied('Factory state unreadable; tool call refused')
        for command in ('git reset --hard', 'rm -rf /', 'git status'):
            self.assertEqual(self.bash(command), refused)

    def test_time_cap_counts_working_minutes_without_queue_wait(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')

        def started(minutes_ago, waited_minutes):
            ledger = self.ledger()
            begun = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
            ledger['01'].update(started_at=begun.isoformat(), queue_wait_seconds=waited_minutes * 60)
            (self.state_dir / 'ledger.json').write_text(json.dumps(ledger))

        started(100, 20)  # 80 working minutes: under the 90-minute cap
        self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'working')
        started(100, 5)
        self.assertIn('01 capped: time cap', self.cli('tick').stdout)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('capped', 'time cap'))
        self.assertEqual(self.cards()[-1], self.held_card('capped: time cap'))
        self.assertIn(['terminal', 'close', '--terminal', 'term_1', '--json'], self.orca_calls())
        self.assertTrue(self.worktree.exists())
        self.git('rev-parse', '--verify', 'refs/heads/factory/demo-01')

    def test_interrupted_ticket_requeued_resumes_in_its_worktree_and_branch(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.build('half.txt', 'half done\n')
        self.cli('pause', '--now')
        self.cli('requeue', '01')
        self.assertIn('relaunched 01 in its worktree', self.cli('resume').stdout)
        entry = self.ledger()['01']
        self.assertEqual([h['state'] for h in entry['history']], ['working', 'interrupted', 'ready', 'working'])
        self.assertEqual((entry['branch'], entry['worktree']), ('factory/demo-01', str(self.worktree)))
        self.assertEqual([c[c.index('--worktree') + 1] for c in self.launches()], [f'path:{self.worktree}'] * 2)
        self.assertEqual(self.git('show', 'factory/demo-01:half.txt'), 'half done')

    def counters_file(self): return self.worktree / '.engineering-workflow-state' / 'factory-turns.json'

    def test_missing_worktree_parks_only_that_ticket_and_the_tick_carries_on(self):
        self.add_ticket('02'); self.cli('install', '--feature', 'demo'); self.cli('tick')
        other = self.state_dir / 'worktrees' / 'demo-02'
        self.git('worktree', 'remove', '--force', str(other))
        self.assertIn('02 needs-you: worktree missing', self.cli('tick').stdout)
        self.assertEqual((self.ledger()['02']['state'], self.ledger()['02']['reason']), ('needs-you', 'worktree missing'))
        self.assertIn(['terminal', 'close', '--terminal', 'term_2', '--json'], self.orca_calls())
        self.finish('01')
        self.assertEqual(self.ledger()['01']['state'], 'merged')

    def test_garbage_counters_file_caps_the_worker_in_the_hook_and_the_tick(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        capped = self.denied('Factory turn cap reached; run factory report 01 blocked')
        for garbage in ('{not json', '{"turns": -5, "permission_needed": false}', '{"turns": "0"}', '[]'):
            with self.subTest(garbage=garbage):
                self.counters_file().write_text(garbage)
                self.assertEqual(self.bash('git status'), capped)
        self.assertIn('01 capped: turn cap', self.cli('tick').stdout)
        self.assertEqual(self.ledger()['01']['turns'], 100)

    def test_deleting_the_counters_file_cannot_lower_the_ticket_count(self):
        self.cli('install', '--feature', 'demo'); self.set_state(max_turns=3); self.cli('tick')
        read = {'tool_name': 'Read', 'tool_input': {'file_path': 'README.md'}}
        self.hook('PostToolUse', **read); self.hook('PostToolUse', **read)
        self.cli('tick')
        self.assertEqual(self.ledger()['01']['turns'], 2)
        self.counters_file().unlink()
        self.hook('PostToolUse', **read)
        self.cli('tick')
        self.assertEqual((self.ledger()['01']['state'], self.ledger()['01']['turns']), ('working', 2))
        self.counters_file().write_text('{"turns": 3, "permission_needed": false}')
        self.assertIn('01 capped: turn cap', self.cli('tick').stdout)

    def test_malformed_or_deleted_marker_refuses_every_tool_call(self):
        self.cli('install', '--feature', 'demo'); self.set_state(max_turns=1); self.cli('tick')
        marker = self.worktree / '.engineering-workflow-state' / 'factory-ticket.json'
        marker.write_text('{"ticket": ')
        refused = self.denied('Factory state unreadable; tool call refused')
        self.assertEqual(self.bash('git status'), refused)
        marker.unlink()
        self.assertEqual(self.bash('git status'), refused)

    def test_credential_warning_survives_a_turn_count_that_fails(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.counters_file().write_text('{not json')
        secret = self.worktree / 'example.py'; secret.write_text('access_key = "AKIA' + 'Z' * 16 + '"\n')
        result = self.hook('PostToolUse', tool_name='Write', tool_input={'file_path': str(secret)})
        self.assertIn('potential credential', json.dumps(result))

    def test_requeued_ticket_whose_worktree_is_gone_goes_back_to_needs_you_and_others_still_start(self):
        self.add_ticket('02'); self.cli('install', '--feature', 'demo'); self.set_state(concurrency=1)
        self.cli('tick')
        self.git('worktree', 'remove', '--force', str(self.worktree))
        self.set_state(mode='draining'); self.cli('tick')  # parks 01 without starting 02
        self.assertEqual((self.ledger()['01']['state'], self.state()['mode']), ('needs-you', 'paused'))
        self.cli('requeue', '01'); self.set_state(mode='running')
        out = self.cli('tick').stdout
        self.assertIn('01 needs you: worktree missing', out)
        self.assertEqual((self.ledger()['01']['state'], self.ledger()['01']['reason']), ('needs-you', 'worktree missing'))
        self.assertEqual(self.ledger()['02']['state'], 'working')

    # --- ticket 08 ---
    def test_back_pressure_holds_new_starts_until_the_pile_drops(self):
        self.add_ticket('02'); self.add_ticket('03')
        self.cli('install', '--feature', 'demo'); self.set_state(concurrency=1, stop_if_waiting=1); self.cli('tick')
        self.cli('report', '01', 'blocked', '--reason', 'needs a decision', project=self.worktree)
        self.assertEqual((sorted(self.ledger()), self.state()['held']), (['01'], True))
        self.assertEqual(self.cli('status').stdout.splitlines()[0],
                         'factory: running · 2 ready · 0 building · 1 needs you · held')
        self.cli('precheck', ok=False)  # held: ready tickets are not work
        self.cli('tick'); self.assertEqual(sorted(self.ledger()), ['01'])
        self.cli('requeue', '01')
        self.assertIn('relaunched 01 in its worktree', self.cli('tick').stdout)
        self.assertFalse(self.state()['held'])
        self.assertNotIn('held', self.cli('status').stdout.splitlines()[0])

    def test_set_changes_a_setting_for_the_next_tick_and_rejects_bad_input_without_writing(self):
        self.add_ticket('02'); self.add_ticket('03')
        self.cli('install', '--feature', 'demo', '--paused')
        before = (self.state_dir / 'state.json').read_bytes()
        for bad in (['colour', '3'], ['concurrency', '0'], ['concurrency', '-1'], ['concurrency', 'two'],
                    ['concurrency', '1.5'], ['max_minutes'], ['mode', '1']):
            self.assertIn('Error:', self.cli('set', *bad, ok=False).stderr)
            self.assertEqual((self.state_dir / 'state.json').read_bytes(), before)
        self.assertEqual(self.cli('set', 'concurrency', '2').stdout, 'concurrency = 2\n')
        for name in ('build_slots', 'daily_ticket_cap', 'stop_if_waiting', 'max_turns', 'max_minutes'):
            self.cli('set', name, '7')
        state = self.state()
        self.assertEqual([state[k] for k in ('concurrency', 'build_slots', 'daily_ticket_cap', 'stop_if_waiting',
                                             'max_turns', 'max_minutes')], [2, 7, 7, 7, 7, 7])
        self.cli('resume')
        self.assertEqual(sorted(self.ledger()), ['01', '02'])

    def test_status_summarises_the_last_wave_from_the_ledger(self):
        self.add_ticket('02'); self.add_ticket('03')
        self.cli('install', '--feature', 'demo'); self.set_state(stop_if_waiting=9); self.cli('tick')
        self.build()
        self.cli('report', '01', 'approved', '--slowed-by', 'slow gate', project=self.worktree)
        two = self.state_dir / 'worktrees' / 'demo-02'
        self.cli('report', '02', 'blocked', '--reason', 'needs an API decision', '--slowed-by', 'unclear spec',
                 project=two)
        self.assertEqual([self.ledger()[t]['slowed_by'] for t in ('01', '02')], ['slow gate', 'unclear spec'])
        self.set_state(max_turns=1)
        self.hook('PostToolUse', cwd=self.state_dir / 'worktrees' / 'demo-03', tool_name='Read', tool_input={})
        self.cli('tick')
        ledger = self.ledger(); ledger['01']['queue_wait_seconds'] = 100; ledger['02']['queue_wait_seconds'] = 25
        (self.state_dir / 'ledger.json').write_text(json.dumps(ledger))
        lines = self.cli('status').stdout.splitlines()
        self.assertEqual(lines[lines.index('last wave: 1 merged'):], [
            'last wave: 1 merged', 'needs you: 02 (needs an API decision)', 'capped: 03 (turn cap)',
            'queue wait: 2m', 'slowed by:', '  01: slow gate', '  02: unclear spec',
            'final review waits on 2 parked tickets'])

    def test_status_summarises_only_the_cycle_wave_and_its_end(self):
        self.add_ticket('02')
        self.cli('install', '--feature', 'demo', '--paused'); self.set_state(concurrency=1)
        self.cli('cycle'); self.finish('01')  # the wave is 01 and 02; 02 starts once 01 merges
        self.finish('02')
        self.add_ticket('03'); self.cli('cycle')  # a new wave of just 03
        three = self.state_dir / 'worktrees' / 'demo-03'
        (three / 'x.txt').write_text('x\n'); self.git('add', '-A', cwd=three); self.git('commit', '-qm', 'x', cwd=three)
        self.cli('report', '03', 'approved', '--slowed-by', 'waited on review', project=three)
        lines = self.cli('status').stdout.splitlines()
        summary = lines[lines.index('last wave: 1 merged'):]
        self.assertEqual(summary[:4], ['last wave: 1 merged', 'queue wait: 0s', 'slowed by:', '  03: waited on review'])
        self.assertEqual(summary[4], f"wave ended: {self.state()['wave_ended_at']}")
        self.assertEqual(len(summary), 5)


    # --- final review fixes ---
    def test_control_file_changes_wait_for_approval_and_approve_merges_them(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.build('CLAUDE.md', 'obey\n', commit=False)
        (self.worktree / '.claude').mkdir(); self.build('.claude/settings.json', '{}\n')
        before = self.git('rev-parse', 'build/demo')
        self.approve()
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']),
                         ('needs-you', 'changes workflow control files: .claude/settings.json, CLAUDE.md'))
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)
        self.cli('approve', '01')
        self.assertEqual(self.ledger()['01']['state'], 'merged')

    def forge_runtime(self, where):
        runtime = where / '.engineering-workflow'
        lock = json.dumps({'schema': 1, 'version': '9.9.9', 'files': {}})
        (runtime / 'workflow.lock.json').write_text(lock); (runtime / 'VERSION').write_text('9.9.9\n')
        import hashlib
        (runtime / 'install.json').write_text(json.dumps({'lock_sha256': hashlib.sha256(lock.encode()).hexdigest()}))
        (runtime / 'workflow.py').write_text(f'open({str(self.base / "forged-ran")!r}, "w")\n')

    def test_a_forged_project_runtime_in_a_ticket_worktree_is_never_used(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.forge_runtime(self.worktree)
        self.assertEqual(self.bash('rm -rf /')['hookSpecificOutput']['permissionDecision'], 'deny')
        self.cli('status', project=self.worktree)
        self.assertFalse((self.base / 'forged-ran').exists())

    def test_a_held_counters_lock_or_fifo_never_hangs_the_hook_or_the_tick(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        lock = self.worktree / '.engineering-workflow-state' / 'factory-turns.lock'
        holder = subprocess.Popen([sys.executable, '-c', 'import fcntl,sys,time; f=open(sys.argv[1],"a"); '
                                   'fcntl.flock(f, fcntl.LOCK_EX); print(1, flush=True); time.sleep(60)', str(lock)],
                                  stdout=subprocess.PIPE, text=True)
        try:
            holder.stdout.readline()
            begin = time.time()
            self.assertEqual(self.bash('git status'), self.denied('Factory state unreadable; tool call refused'))
            self.assertLess(time.time() - begin, 6)
            self.cli('tick')
            self.assertEqual(self.ledger()['01']['state'], 'working')
            ledger = self.ledger()
            ledger['01']['started_at'] = (datetime.now(timezone.utc) - timedelta(minutes=200)).isoformat()
            (self.state_dir / 'ledger.json').write_text(json.dumps(ledger))
            self.assertIn('01 capped: time cap', self.cli('tick').stdout)
        finally:
            holder.kill(); holder.wait()
        self.cli('requeue', '01'); self.cli('tick')
        self.counters_file().unlink(missing_ok=True); os.mkfifo(self.counters_file())
        begin = time.time()
        self.assertEqual(self.bash('git status')['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertLess(time.time() - begin, 6)

    def test_an_unexpected_hook_error_fails_closed(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'workflow.py'), 'hook', '--platform', 'claude',
                                 '--event', 'PreToolUse'], input='[' * 100000, text=True, capture_output=True,
                                env=self.env)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_person_only_commands_refuse_inside_a_ticket_worktree(self):
        self.add_ticket('02'); self.cli('install', '--feature', 'demo'); self.cli('tick')
        for argv in (['install', '--feature', 'demo'], ['uninstall'], ['set', 'max_turns', '999'], ['pause'],
                     ['resume'], ['cycle'], ['approve', '01'], ['requeue', '01']):
            with self.subTest(argv=argv):
                refused = self.cli(*argv, project=self.worktree, ok=False).stderr
                self.assertIn('Run this from the integration checkout, not a ticket worktree', refused)
        self.cli('report', '02', 'approved', project=self.worktree, ok=False)
        self.assertEqual(self.ledger()['02']['state'], 'working')
        self.assertEqual(self.state()['max_turns'], 100)

    BYPASS = "Orca launched in bypass mode; remove it from Orca's Claude arguments or reinstall with --allow-bypass"

    def test_bypass_is_rechecked_every_tick_in_any_spelling(self):
        self.add_ticket('02'); self.cli('install', '--feature', 'demo'); self.set_state(concurrency=1); self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'working')
        (self.orca_dir / 'screen-term_1').write_text('claude --permission-mode bypassPermissions')
        self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason'], self.state()['mode']), ('needs-you', self.BYPASS, 'paused'))
        self.assertIn(['terminal', 'close', '--terminal', 'term_1', '--json'], self.orca_calls())
        self.assertNotIn('02', self.ledger())

    def test_a_terminal_that_cannot_be_read_stops_the_worker_and_pauses(self):
        (self.orca_dir / 'read-fails').touch()
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason'], self.state()['mode']),
                         ('needs-you', "could not confirm Orca's permission mode", 'paused'))
        self.assertIn(['terminal', 'close', '--terminal', 'term_1', '--json'], self.orca_calls())

    def test_final_review_agent_in_bypass_is_stopped_and_not_dispatched(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build()
        (self.orca_dir / 'screen-term_2').write_text('BYPASS PERMISSIONS on')
        self.assertIn(self.BYPASS, self.approve().stdout)
        self.assertEqual((self.state()['final_review'], self.state()['mode']), ('not-started', 'paused'))
        self.assertIn(['terminal', 'close', '--terminal', 'term_2', '--json'], self.orca_calls())

    def test_a_hung_gate_is_killed_and_fails_with_timeout(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        (self.project / '.engineering-workflow' / 'gates.sh').write_text('sleep 60 &\nwait\necho "GATES: PASS"\n')
        self.git('commit', '-qam', 'Hung gate'); self.build(); self.set_state(max_minutes=0.03)
        begin = time.time()
        self.assertIn('GATES: FAIL timeout', self.cli('gate', ok=False).stdout)
        self.approve()
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('needs-you', 'gate timed out on the ticket branch'))
        self.assertLess(time.time() - begin, 20)

    def wait_for(self, check, seconds=30):
        deadline = time.time() + seconds
        while not check():
            self.assertLess(time.time(), deadline, 'timed out waiting')
            time.sleep(0.2)

    def test_detached_report_and_tick_return_at_once_and_the_tick_still_runs(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build()
        self.slow_gate(3); self.git('commit', '-qam', 'Slow gate')
        begin = time.time()
        self.approve('--detach')
        self.assertLess(time.time() - begin, 2.5)
        self.assertEqual(self.ledger()['01']['state'], 'approved')
        self.wait_for(lambda: self.state()['mode'] == 'paused')
        self.assertEqual(self.ledger()['01']['state'], 'merged')
        last = self.state()['last_tick']
        self.cli('tick', '--detach')
        self.wait_for(lambda: self.state()['last_tick'] != last)
        self.assertIn('merged 01', (self.state_dir / 'tick.log').read_text())

    def test_report_made_while_a_tick_holds_the_lock_returns_at_once_and_is_not_lost(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build()
        holder = subprocess.Popen([sys.executable, '-c', 'import fcntl,sys,time; f=open(sys.argv[1],"a"); '
                                   'fcntl.flock(f, fcntl.LOCK_EX); print(1, flush=True); time.sleep(8)',
                                   str(self.state_dir / 'tick.lock')], stdout=subprocess.PIPE, text=True)
        try:  # a tick holds its lock through a pre-merge gate, which can outlast the worker's tool call
            holder.stdout.readline()
            self.assertIn('Ticket ../ledger is not working', self.cli('report', '../ledger', 'approved', ok=False).stderr)
            begin = time.time()
            self.approve('--detach')
            self.assertLess(time.time() - begin, 5)
            (self.orca_dir / 'dead-term_1').touch()  # the worker exits once it has reported
        finally:
            holder.kill(); holder.wait(); holder.stdout.close()
        self.wait_for(lambda: self.state()['mode'] == 'paused')
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['slowed_by']), ('merged', 'nothing'))

    def test_report_files_a_worker_plants_never_wedge_the_factory(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        reports = self.state_dir / 'reports'
        (reports / '01.json').mkdir(parents=True); (reports / '01.json' / 'kept').write_text('x')
        (reports / '02.json').write_text('not json'); os.mkfifo(reports / '03.json')
        self.cli('tick'); self.cli('status')
        self.assertEqual((self.ledger()['01']['state'], list(reports.iterdir())), ('working', []))

    def test_precheck_runs_while_paused_with_a_working_ticket_and_tick_starts_nothing(self):
        self.add_ticket('02'); self.cli('install', '--feature', 'demo'); self.set_state(concurrency=1); self.cli('tick')
        self.set_state(mode='paused', concurrency=3)
        self.cli('precheck')
        (self.orca_dir / 'dead-term_1').touch()
        self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'interrupted')
        self.assertNotIn('02', self.ledger())
        self.cli('precheck', ok=False)

    def test_a_forged_ledger_entry_is_refused_before_any_git_change(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build()
        before = self.git('rev-parse', 'build/demo')
        for field, value in (('worktree', str(self.project)), ('branch', 'main')):
            with self.subTest(field=field):
                ledger = self.ledger(); good = ledger['01'][field]
                ledger['01'].update({field: value, 'state': 'approved'})
                (self.state_dir / 'ledger.json').write_text(json.dumps(ledger))
                self.cli('tick')
                ledger = self.ledger()
                self.assertEqual((ledger['01']['state'], ledger['01']['reason']),
                                 ('needs-you', 'ledger entry failed validation'))
                ledger['01'][field] = good; (self.state_dir / 'ledger.json').write_text(json.dumps(ledger))
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)
        self.assertTrue(self.worktree.exists())

    def test_resume_clears_the_wave_and_the_final_review_ends_the_running_wave(self):
        self.cli('install', '--feature', 'demo', '--paused'); self.cli('cycle')
        self.assertEqual(self.state()['wave'], ['01'])
        self.cli('pause', '--now'); self.cli('requeue', '01'); self.cli('resume')
        self.assertEqual(self.state()['wave'], [])
        self.assertNotIn('wave_ended_at', self.state())
        self.build(); self.approve()
        state = self.state()
        self.assertEqual((state['mode'], state['final_review']), ('paused', 'dispatched'))
        self.assertTrue(state['wave_ended_at'])

    def session(self, project):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'workflow.py'), 'session', '--project', str(project),
                                 '--platform', 'claude'], text=True, capture_output=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_session_start_report_carries_the_factory_status_line(self):
        self.assertNotIn('factory', self.session(self.project))
        self.add_ticket('02'); self.cli('install', '--feature', 'demo'); self.set_state(concurrency=1); self.cli('tick')
        line = 'factory: running · 1 ready · 1 building · 0 needs you'
        self.assertEqual(self.session(self.project)['factory'], line)
        self.assertEqual(self.session(self.worktree)['factory'], line)  # inside a ticket worktree too
        started = self.hook('SessionStart', cwd=self.project)
        self.assertEqual(json.loads(started['hookSpecificOutput']['additionalContext'])['factory'], line)
        (self.state_dir / 'ledger.json').write_text('not json')
        self.assertEqual(self.session(self.project)['factory'], 'unreadable')


FAKE_AO = f"""#!{sys.executable}
import json, os, re, subprocess, sys
from pathlib import Path
control = Path(os.environ['FAKE_AO_DIR'])
project = os.environ['FAKE_AO_PROJECT']
args = sys.argv[1:]
with open(control / 'log.jsonl', 'a') as log: log.write(json.dumps(args) + '\\n')
store = control / 'sessions.json'
sessions = json.loads(store.read_text()) if store.exists() else {{}}
def save(): store.write_text(json.dumps(sessions))
def out(value): print(json.dumps(value))
def fail(message): print(message, file=sys.stderr); sys.exit(1)
def flag(name): return args[args.index(name) + 1] if name in args else None
def git(*a, cwd=project): return subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True)
words = [a for a in args if not a.startswith('-')]
if args[:2] == ['project', 'ls']:
    out({{'projects': [] if (control / 'unregistered').exists() else [{{'id': 'demo', 'name': 'demo'}}]}})
elif args[:2] == ['project', 'get']:
    mode = 'bypass-permissions' if (control / 'bypass').exists() else 'auto'
    out({{'status': 'ok', 'project': {{'id': 'demo', 'path': project,
         'config': {{'agentConfig': {{'permissions': mode}}, 'worker': {{'agentConfig': {{}}}}}}}}}})
elif args[:1] == ['spawn']:
    if (control / 'spawn-fails').exists(): fail('spawn demo: workspace: branch is checked out elsewhere')
    sid = f'demo-{{len(sessions) + 1}}'
    kind, branch, path = flag('--kind') or 'worker', flag('--branch'), None
    if kind == 'worker':
        path = str(control / 'worktrees' / sid)
        if git('worktree', 'add', path, branch).returncode: fail('spawn demo: could not create worktree')
    sessions[sid] = {{'kind': kind, 'branch': branch, 'path': path, 'name': flag('--name'), 'dead': False}}
    save(); print(f'spawned session {{sid}} "{{flag("--name")}}" (idle) [prompt 0 B, system 1 B]')
elif args[:2] == ['session', 'get']:
    s = sessions.get(args[2])
    if not s: fail('session not found')
    out({{'session': {{'id': args[2], 'projectId': 'demo', 'kind': s['kind'], 'isTerminated': s['dead']}}}})
elif args[:2] == ['session', 'kill']:
    s = sessions[args[2]]; s['dead'] = True; save()
    if s['path'] and Path(s['path']).exists() and not git('status', '--porcelain', cwd=s['path']).stdout.strip():
        git('worktree', 'remove', '--force', s['path'])  # AO drops a clean workspace, keeps a dirty one
    print(f'session {{args[2]}} killed')
elif args[:2] == ['session', 'restore']:
    s = sessions[args[2]]
    if (control / 'restore-fails').exists(): fail('restore failed')
    if s['path'] and not Path(s['path']).exists() and git('worktree', 'add', s['path'], s['branch']).returncode:
        fail('restore: branch gone')
    s['dead'] = False; save(); print('restored')
elif args[:2] == ['session', 'rename']:
    sessions[args[2]]['name'] = args[3]; save(); print('renamed')
elif args[:1] == ['send']:
    if (control / 'send-fails').exists(): fail('send failed')
    print('sent')
elif args[:2] == ['orchestrator', 'ls']:
    out({{'data': [{{'id': k, 'projectId': 'demo', 'isTerminated': v['dead']}}
                   for k, v in sessions.items() if v['kind'] == 'orchestrator']}})
else: fail('unknown command ' + ' '.join(args))
"""
FAKE_LAUNCHCTL = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
with open(Path(os.environ['FAKE_AO_DIR']) / 'launchctl.jsonl', 'a') as log: log.write(json.dumps(sys.argv[1:]) + '\\n')
"""


class AoRunnerTests(unittest.TestCase):
    """The same factory with --runner ao: AO sessions and worktrees, a launchd heartbeat, an orchestrator relay.
    Borrows FactoryTests' fixture and helpers, not its tests."""
    tearDown, git, cli, orca_calls = FactoryTests.tearDown, FactoryTests.git, FactoryTests.cli, FactoryTests.orca_calls
    ledger, state = FactoryTests.ledger, FactoryTests.state

    def setUp(self):
        FactoryTests.setUp(self)
        self.ao_dir = self.base / 'ao'; self.ao_dir.mkdir()
        self.home = self.base / 'home'; self.home.mkdir()
        for name, text in (('ao', FAKE_AO), ('launchctl', FAKE_LAUNCHCTL)):
            tool = self.fakebin / name; tool.write_text(text); tool.chmod(0o755)
        self.env.update(FAKE_AO_DIR=str(self.ao_dir), FAKE_AO_PROJECT=str(self.project), HOME=str(self.home),
                        AO_SESSION_ID='caller-1')
        self.env.pop('AO_CLI_COMMAND', None)

    def ao_calls(self):
        log = self.ao_dir / 'log.jsonl'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def sends(self, session=None):
        return [c[c.index('--message') + 1] for c in self.ao_calls()
                if c[:1] == ['send'] and (session is None or c[c.index('--session') + 1] == session)]

    def install_ao(self, *extra, ok=True):
        return self.cli('install', '--feature', 'demo', '--runner', 'ao', *extra, ok=ok)

    def ticket_tree(self, ticket='01'):
        return Path(self.ledger()[ticket]['worktree'])

    def test_ao_one_ticket_goes_from_ready_to_merged_without_orca(self):
        main_before = self.git('rev-parse', 'main')
        self.install_ao()
        state = self.state()
        label = 'com.engineering-workflow.factory.demo.demo'
        self.assertEqual((state['runner'], state['ao_project'], state['automation_id'], state['relay_handle']),
                         ('ao', 'demo', label, 'ao:demo-1'))
        plist = plistlib.loads((self.home / 'Library' / 'LaunchAgents' / f'{label}.plist').read_bytes())
        self.assertEqual((plist['Label'], plist['StartInterval']), (label, 3600))
        script = plist['ProgramArguments'][-1]
        self.assertIn(f"precheck --project '{self.project}' && ", script)
        self.assertTrue(script.endswith(f"tick --project '{self.project}'"), script)
        launchctl = [json.loads(l) for l in (self.ao_dir / 'launchctl.jsonl').read_text().splitlines()]
        self.assertEqual(launchctl[0][:2], ['bootstrap', f'gui/{os.getuid()}'])
        relay = [c for c in self.ao_calls() if c[:1] == ['spawn']][0]
        self.assertEqual(relay[relay.index('--kind') + 1], 'orchestrator')
        self.assertIn('Never edit files, merge, push', relay[relay.index('--prompt') + 1])

        self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['branch'], entry['worker_handle']),
                         ('working', 'factory/demo-01', 'ao:demo-2'))
        tree = self.ticket_tree()
        self.assertEqual(tree, self.ao_dir / 'worktrees' / 'demo-2')
        self.assertEqual(self.git('branch', '--show-current', cwd=tree), 'factory/demo-01')
        marker = json.loads((tree / '.engineering-workflow-state' / 'factory-ticket.json').read_text())
        self.assertEqual(marker, {'ticket': '01', 'state_dir': str(self.state_dir)})
        spawn = [c for c in self.ao_calls() if c[:1] == ['spawn']][1]
        self.assertEqual((spawn[spawn.index('--branch') + 1], spawn[spawn.index('--harness') + 1]),
                         ('factory/demo-01', 'claude-code'))
        self.assertNotIn('--prompt', spawn)  # the brief goes in only after the marker exists
        brief = self.sends('demo-2')
        self.assertEqual(len(brief), 1)
        self.assertIn('Use the ew-factory skill (worker brief)', brief[0])
        self.assertIn(f"--project {shlex.quote(str(tree))}", brief[0])

        (tree / 'thing.txt').write_text('built\n')
        self.git('add', '-A', cwd=tree); self.git('commit', '-qm', 'Build thing', cwd=tree)
        self.cli('report', '01', 'approved', '--slowed-by', 'nothing', project=tree)
        self.assertEqual(self.ledger()['01']['state'], 'merged')
        self.assertEqual(self.git('show', 'build/demo:thing.txt'), 'built')
        self.assertFalse(tree.exists())
        self.assertIn(['session', 'kill', 'demo-2'], self.ao_calls())
        self.assertEqual(self.git('branch', '--list', 'factory/demo-01'), '')  # merged claim branch removed
        self.assertEqual(self.git('rev-parse', 'main'), main_before)
        self.assertEqual(self.orca_calls(), [])

    def test_ao_calls_drop_the_calling_sessions_identity(self):
        self.env['FAKE_AO_DIR'] = str(self.ao_dir)
        probe = self.fakebin / 'ao'
        probe.write_text(FAKE_AO.replace("args = sys.argv[1:]",
                                         "args = sys.argv[1:]\nassert 'AO_SESSION_ID' not in os.environ, 'leaked'"))
        self.install_ao(); self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'working')

    def test_ao_install_refuses_without_ao_unregistered_or_bad_runner(self):
        no_ao = {**self.env, 'AO_CLI_COMMAND': 'ao-not-installed-here'}
        self.assertIn('AO CLI not found',
                      self.cli('install', '--feature', 'demo', '--runner', 'ao', ok=False, env=no_ao).stderr)
        (self.ao_dir / 'unregistered').touch()
        self.assertIn('This repo is not registered in AO', self.install_ao(ok=False).stderr)
        self.assertFalse((self.state_dir / 'state.json').exists())
        self.assertFalse((self.ao_dir / 'launchctl.jsonl').exists())
        self.assertIn('invalid choice', self.cli('install', '--feature', 'demo', '--runner', 'x', ok=False).stderr)

    def test_ao_install_reuses_a_live_project_orchestrator_as_the_relay(self):
        (self.ao_dir / 'sessions.json').write_text(json.dumps(
            {'demo-1': {'kind': 'orchestrator', 'branch': None, 'path': None, 'name': 'mine', 'dead': False}}))
        self.install_ao()
        self.assertEqual(self.state()['relay_handle'], 'ao:demo-1')
        self.assertFalse(self.state()['relay_spawned'])
        self.assertEqual([c for c in self.ao_calls() if c[:1] == ['spawn']], [])
        self.assertIn('You relay the engineering-workflow factory', self.sends('demo-1')[0])

    def test_ao_needs_you_is_relayed_once_to_the_orchestrator(self):
        self.install_ao(); self.cli('tick')
        tree = self.ticket_tree()
        self.cli('report', '01', 'blocked', '--reason', 'needs an API decision', '--slowed-by', 'spec', project=tree)
        self.cli('tick')
        relayed = [m for m in self.sends('demo-1') if 'NEEDS YOU' in m]
        self.assertEqual(relayed, ['Ticket 01 NEEDS YOU: needs an API decision (branch factory/demo-01)'])
        self.assertEqual(self.title('demo-2'), 'NEEDS YOU: factory demo 01')  # the board card says so
        self.cli('requeue', '01'); self.cli('tick')
        self.assertEqual(self.title('demo-2'), 'factory demo 01')  # back to plain once it builds again

    def title(self, session):
        return json.loads((self.ao_dir / 'sessions.json').read_text())[session]['name']

    def test_ao_relay_failure_is_reported_and_retried_next_tick(self):
        self.install_ao(); self.cli('tick')
        (self.ao_dir / 'send-fails').touch()
        out = self.cli('report', '01', 'blocked', '--reason', 'stuck', project=self.ticket_tree()).stdout
        self.assertIn('card for 01 not updated', out)
        (self.ao_dir / 'send-fails').unlink()
        self.cli('tick'); self.cli('tick')
        self.assertEqual(len([m for m in self.sends('demo-1') if 'NEEDS YOU' in m]), 2)  # the failed try, one retry

    def test_ao_bypass_project_stops_the_worker_and_pauses(self):
        (self.ao_dir / 'bypass').touch()
        self.install_ao(); self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], self.state()['mode']), ('needs-you', 'paused'))
        self.assertTrue(entry['reason'].startswith('AO runs this project'), entry['reason'])
        self.assertIn(['session', 'kill', 'demo-2'], self.ao_calls())

    def test_ao_allow_bypass_keeps_the_worker(self):
        (self.ao_dir / 'bypass').touch()
        self.install_ao('--allow-bypass'); self.cli('tick')
        self.assertEqual(self.ledger()['01']['state'], 'working')

    def test_ao_spawn_failure_parks_the_ticket(self):
        self.install_ao(); (self.ao_dir / 'spawn-fails').touch()
        out = self.cli('tick').stdout
        entry = self.ledger()['01']
        self.assertEqual(entry['state'], 'needs-you')
        self.assertIn('branch is checked out elsewhere', entry['reason'])
        self.assertIn('01 needs you', out)

    def test_ao_dead_session_is_interrupted_and_requeue_restores_it_on_its_branch(self):
        self.install_ao(); self.cli('tick')
        tree = self.ticket_tree()
        (tree / 'half.txt').write_text('half\n')
        self.git('add', '-A', cwd=tree); self.git('commit', '-qm', 'half', cwd=tree)
        self.cli('pause', '--now')
        self.assertFalse(tree.exists())  # a clean AO workspace goes with its session; the branch keeps the work
        self.assertEqual(self.ledger()['01']['state'], 'interrupted')
        self.cli('requeue', '01')
        self.assertIn('relaunched 01 in its worktree', self.cli('resume').stdout)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['worker_handle']), ('working', 'ao:demo-2'))
        self.assertIn(['session', 'restore', 'demo-2'], self.ao_calls())
        self.assertEqual(self.git('show', 'HEAD:half.txt', cwd=tree), 'half')
        self.assertTrue((tree / '.engineering-workflow-state' / 'factory-ticket.json').is_file())
        self.assertEqual(len([m for m in self.sends('demo-2') if 'worker brief' in m]), 2)

    def test_ao_failed_restore_sends_the_ticket_back_to_needs_you(self):
        self.install_ao(); self.cli('tick'); self.cli('pause', '--now'); self.cli('requeue', '01')
        (self.ao_dir / 'restore-fails').touch()
        self.assertIn('01 needs you: worktree missing', self.cli('resume').stdout)

    def test_ao_ledger_cannot_point_a_merge_at_another_worktree(self):
        self.install_ao(); self.cli('tick')
        tree = self.ticket_tree()
        self.build_in(tree)
        data = self.ledger(); data['01']['worktree'] = str(self.project)
        (self.state_dir / 'ledger.json').write_text(json.dumps(data))
        self.cli('report', '01', 'approved', '--slowed-by', 'nothing', project=tree)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('needs-you', 'ledger entry failed validation'))

    def build_in(self, tree):
        (tree / 'thing.txt').write_text('built\n')
        self.git('add', '-A', cwd=tree); self.git('commit', '-qm', 'Build', cwd=tree)

    def test_ao_worktree_without_its_marker_is_still_a_ticket_worktree(self):
        self.install_ao(); self.cli('tick')
        tree = self.ticket_tree()
        (tree / '.engineering-workflow-state' / 'factory-ticket.json').unlink()
        self.assertIn('Run this from the integration checkout', self.cli('pause', project=tree, ok=False).stderr)

    def test_ao_final_review_runs_on_a_review_branch_at_the_integration_tip(self):
        self.install_ao(); self.cli('tick')
        self.build_in(self.ticket_tree())
        self.cli('report', '01', 'approved', '--slowed-by', 'nothing', project=self.ticket_tree())
        state = self.state()
        self.assertEqual((state['final_review'], state['final_review_handle'], state['mode']),
                         ('dispatched', 'ao:demo-3', 'paused'))
        review = [c for c in self.ao_calls() if c[:1] == ['spawn']][-1]
        self.assertEqual(review[review.index('--branch') + 1], 'factory/demo-final-review')
        self.assertEqual(self.git('rev-parse', 'factory/demo-final-review'), self.git('rev-parse', 'build/demo'))
        prompt = review[review.index('--prompt') + 1]
        self.assertIn('Use the ew-factory skill (final review brief) for demo on build/demo', prompt)
        self.assertIn(str(self.state_dir / 'final-review.md'), prompt)
        self.cli('uninstall')
        self.assertIn(['session', 'kill', 'demo-3'], self.ao_calls())
        self.assertEqual(self.git('branch', '--list', 'factory/demo-final-review'), '')

    def test_ao_uninstall_boots_out_the_heartbeat_and_kills_its_own_relay(self):
        self.install_ao(); self.cli('tick'); self.cli('uninstall')
        self.assertNotIn(['session', 'kill', 'demo-3'], self.ao_calls())  # no final review was started
        label = 'com.engineering-workflow.factory.demo.demo'
        launchctl = [json.loads(l) for l in (self.ao_dir / 'launchctl.jsonl').read_text().splitlines()]
        self.assertEqual(launchctl[-1], ['bootout', f'gui/{os.getuid()}/{label}'])
        self.assertFalse((self.home / 'Library' / 'LaunchAgents' / f'{label}.plist').exists())
        self.assertIn(['session', 'kill', 'demo-1'], self.ao_calls())
        self.assertIn(['session', 'kill', 'demo-2'], self.ao_calls())
        self.assertFalse((self.state_dir / 'state.json').exists())

    def test_orca_installs_keep_their_old_shape(self):
        self.cli('install', '--feature', 'demo')
        self.assertEqual(self.state().get('runner', 'orca'), 'orca')
        self.assertEqual(self.ao_calls(), [])


if __name__ == '__main__':
    unittest.main()
