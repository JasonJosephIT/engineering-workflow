"""Factory CLI tests: a temp git repo and a fake `orca` on PATH that logs every call."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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
elif words.startswith('agent launch') and (control / 'launch-fails').exists():
    print(json.dumps({{'ok': False, 'error': {{'code': 'runtime_error', 'message': 'no workspace for path'}}}}))
elif words.startswith('agent launch'): reply(launch={{'outcome': {{'handle': 'term_1'}}}})
elif words.startswith('terminal read'):
    bypass = (control / 'bypass').exists()
    reply(text='claude --dangerously-skip-permissions' if bypass else 'claude')
elif words.startswith('worktree set'): reply(ok=not (control / 'card-fails').exists(), worktree={{}})
elif words.startswith('terminal close'): reply(ok=False)
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
        self.cli('install', '--feature', 'demo')
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


    # --- ticket 04 ---
    def set_radius(self, line):
        ticket = self.project / '.scratch' / 'demo' / 'issues' / '01-thing.md'
        ticket.write_text(TICKET.replace('**Blast radius:** low\n', line))
        self.git('commit', '-qam', 'set blast radius')

    def cards(self):
        return [c[3:] for c in self.orca_calls() if c[:2] == ['worktree', 'set']]

    def held_card(self, reason):
        return [f'path:{self.worktree}', '--workspace-status', 'in-review', '--comment', f'NEEDS YOU: {reason}',
                '--unread', '--json']

    def test_high_or_missing_blast_radius_passes_gate_then_waits_for_approve(self):
        for line in ('**Blast radius:** high\n', '', 'Blast radius: huge\n'):
            with self.subTest(line=line):
                self.tmp.cleanup(); self.setUp()  # a fresh repo per radius
                self.set_radius(line)
                self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build()
                before = self.git('rev-parse', 'build/demo')
                self.approve()
                entry = self.ledger()['01']
                self.assertEqual((entry['state'], entry['reason']),
                                 ('needs-you', 'high blast radius: waiting for approval'))
                self.assertEqual(self.git('rev-parse', 'build/demo'), before)
                self.assertEqual(self.cards()[-1], self.held_card('high blast radius: waiting for approval'))
                self.assertIn('merged 01 into build/demo', self.cli('approve', '01').stdout)
                entry = self.ledger()['01']
                self.assertEqual([h['state'] for h in entry['history']],
                                 ['working', 'approved', 'needs-you', 'merged'])
                self.assertEqual(len(self.git('rev-list', '--parents', '-n', '1', 'build/demo').split()), 3)
                self.assertEqual(self.git('show', 'build/demo:thing.txt'), 'built')
                self.assertFalse(self.worktree.exists())
                self.assertEqual(self.cards()[-1],
                                 [f'path:{self.worktree}', '--workspace-status', 'completed', '--json'])

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
        self.cli('install', '--feature', 'demo'); self.cli('tick'); self.build()
        self.cli('report', '01', 'blocked', '--reason', 'needs an API decision', '--slowed-by', 'spec',
                 project=self.worktree)
        tip = self.git('rev-parse', 'factory/demo-01')
        self.cli('requeue', '01')
        self.assertEqual(self.ledger()['01']['state'], 'ready')
        self.assertIn('01 ready factory/demo-01', self.cli('status').stdout)
        self.cli('tick')
        entry = self.ledger()['01']
        self.assertEqual([h['state'] for h in entry['history']], ['working', 'needs-you', 'ready', 'working'])
        self.assertEqual((entry['branch'], entry['worktree'], entry['turns']),
                         ('factory/demo-01', str(self.worktree), 0))
        self.assertEqual(self.git('rev-parse', 'factory/demo-01'), tip)
        branches = self.git('branch', '--list', '--format=%(refname:short)', 'factory/*').split()
        self.assertEqual(branches, ['factory/demo-01'])
        launches = [c for c in self.orca_calls() if c[:2] == ['agent', 'launch']]
        self.assertEqual([c[c.index('--worktree') + 1] for c in launches], [f'path:{self.worktree}'] * 2)
        self.assertEqual(self.cards()[-1],
                         [f'path:{self.worktree}', '--workspace-status', 'in-progress', '--json'])


if __name__ == '__main__':
    unittest.main()
