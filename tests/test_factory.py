"""Factory CLI tests: a temp git repo and a fake `orca` on PATH that logs every call."""
import json
import os
from pathlib import Path
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
elif words.startswith('agent launch'): reply(launch={{'outcome': {{'handle': 'term_1'}}}})
elif words.startswith('terminal read'):
    bypass = (control / 'bypass').exists()
    reply(text='claude --dangerously-skip-permissions' if bypass else 'claude')
elif words.startswith('worktree set'): reply(ok=not (control / 'card-fails').exists(), worktree={{}})
elif words.startswith('terminal close'): reply(ok=False)
elif words.startswith('terminal show') and (control / 'show-fails').exists(): reply(ok=False)
elif words.startswith('terminal show'): reply(terminal={{'connected': False, 'exitCause': 'closed'}})
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
        orca = self.fakebin / 'orca'; orca.write_text(FAKE_ORCA); orca.chmod(0o755)
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
        self.assertEqual(self.git('status', '--porcelain', cwd=self.worktree), 'A  thing.txt')
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

    def test_gate_is_rerun_on_ticket_branch_before_merge(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        (self.worktree / '.engineering-workflow' / 'gates.sh').write_text('echo "GATES: FAIL tests"\n')
        self.git('commit', '-qam', 'Break the gate', cwd=self.worktree)
        before = self.git('rev-parse', 'build/demo')
        self.cli('report', '01', 'approved', '--slowed-by', 'nothing', project=self.worktree)
        entry = self.ledger()['01']
        self.assertEqual((entry['state'], entry['reason']), ('needs-you', 'gates failed on the ticket branch'))
        self.assertEqual(self.git('rev-parse', 'build/demo'), before)
        self.assertTrue(self.worktree.exists())

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
        self.assertEqual(self.git('show', 'factory/demo-01:half.txt'), 'half done')

    def test_resume_sets_running_and_ticks(self):
        self.cli('install', '--feature', 'demo', '--paused')
        self.cli('resume')
        self.assertEqual(self.state()['mode'], 'running')
        self.assertEqual(self.ledger()['01']['state'], 'working')

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
        self.assertNotIn('02', self.ledger())
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
        state = self.state(); state['build_slots'] = 2
        (self.state_dir / 'state.json').write_text(json.dumps(state))
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

    def test_existing_claim_branch_is_skipped_and_later_tickets_still_start(self):
        self.add_ticket('02'); self.cli('install', '--feature', 'demo')
        self.git('branch', 'factory/demo-01', 'build/demo')
        sha = self.git('rev-parse', 'factory/demo-01')
        self.git('commit', '--allow-empty', '-qm', 'elsewhere'); self.git('branch', '-f', 'factory/demo-01', 'HEAD')
        sha = self.git('rev-parse', 'factory/demo-01')
        out = self.cli('tick').stdout
        self.assertIn('01 already claimed', out); self.assertEqual(sorted(self.ledger()), ['02'])
        self.assertEqual(self.git('rev-parse', 'factory/demo-01'), sha)
        self.assertFalse(self.worktree.exists())

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
                         ('dispatched', 'term_1', 'paused'))
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

    def test_uninstall_removes_heartbeat_and_keeps_ledger_worktrees_and_branches(self):
        self.cli('install', '--feature', 'demo'); self.cli('tick')
        self.cli('uninstall')
        self.assertIn(['automations', 'remove', 'auto_1', '--json'], self.orca_calls())
        self.assertFalse((self.state_dir / 'state.json').exists())
        self.assertEqual(self.ledger()['01']['state'], 'working')
        self.assertTrue(self.worktree.exists())
        self.git('rev-parse', '--verify', 'refs/heads/factory/demo-01')
        self.assertIn('No factory installed', self.cli('status', ok=False).stderr)
        self.cli('install', '--feature', 'demo', '--paused')

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
        self.assertIn(f"report 01 approved --project '{self.worktree}'", prompt)
        lock = json.loads((ROOT / 'workflow.lock.json').read_text())
        self.assertEqual(lock['skills']['ew-factory'], 'skills/factory')
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
        self.cli('install', '--feature', 'demo'); self.set_state(final_review='dispatched')  # the last ticket parking must not end the feature here
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
        (self.worktree / '.engineering-workflow' / 'gates.sh').write_text('echo "GATES: FAIL tests"\n')
        self.git('commit', '-qam', 'Break the gate', cwd=self.worktree)
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
        self.cli('install', '--feature', 'demo'); self.set_state(final_review='dispatched')  # the last ticket parking must not end the feature here
        self.cli('tick'); self.build()
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
        self.cli('install', '--feature', 'demo'); self.set_state(final_review='dispatched')  # the last ticket parking must not end the feature here
        self.cli('tick')
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


if __name__ == '__main__':
    unittest.main()
