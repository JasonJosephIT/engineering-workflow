"""Consumer CLI tests. All records and private bundles are synthetic."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEYS = ['overview', 'problem_audience', 'role_scope', 'approach_decisions',
        'challenges_solutions', 'outcome_evidence', 'reflection', 'links']


class ReviewFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base / 'project'; self.project.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        self.state = self.base / 'private-state'
        self.standard = self.base / 'standard.json'
        self.standard.write_text(json.dumps({'standard_version': '1.0.0', 'sections': [
            {'key': key, 'title': key, 'fields': {'detail': 'Detail'}} for key in KEYS]}))
        self.bundle = self.base / 'bundle'; self.bundle.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.bundle)], check=True)

    def tearDown(self): self.tmp.cleanup()

    def cli(self, group, action, *args, ok=True):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'workflow.py'), group, action,
            '--project', str(self.project), '--state-dir', str(self.state), *args],
            text=True, capture_output=True, env={**os.environ, 'DAYDREAMER_BUNDLE': str(self.bundle)})
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return json.loads(result.stdout) if result.returncode == 0 else result

    def config(self, *args):
        return self.cli('project', 'configure', '--public-facing', 'true',
            '--audience', 'Library visitors', '--goal', 'Find a book',
            '--standards-source', str(self.standard), *args)

    def draft(self, status='checkpoint'):
        path = self.base / 'draft.json'
        path.write_text(json.dumps({'title': 'Book lookup', 'status': status,
            'sections': {'outcome': 'Readers can search by title.',
                'purpose_decisions': 'Use the existing catalog to meet the lookup goal.',
                'evidence_limits': 'Synthetic search test passed; keyboard use is unverified.',
                'standards_implications': 'Outcome evidence is partial.', 'your_attention': 'Try keyboard navigation.'},
            'references': {'implementation': ['spec:book-lookup'], 'sessions': [{'platform': 'codex', 'id': 'session-a'}]}}))
        return path

    def upsert(self, path, base=0, platform='codex', ok=True):
        return self.cli('review', 'upsert', '--implementation', 'book-lookup', '--file', str(path),
                        '--base-revision', str(base), '--platform', platform, ok=ok)

    def test_public_kickoff_records_missing_discovery_without_inventing_answers(self):
        data = self.config()
        self.assertEqual(data['public_facing'], True)
        self.assertEqual(data['discovery']['pending'], KEYS)
        self.assertEqual(data['standard']['version'], '1.0.0')
        self.assertEqual(self.cli('project', 'status')['discovery']['status'], 'incomplete')

    def test_multisession_review_preserves_identity_and_rejects_stale_revision(self):
        self.config()
        first = self.upsert(self.draft())
        self.assertEqual(first['revision'], 1)
        second = self.upsert(self.draft('complete'), base=1, platform='claude')
        self.assertEqual(first['implementation_id'], second['implementation_id'])
        self.assertEqual(second['revision'], 2)
        self.assertEqual(second['status'], 'complete')
        self.assertEqual(second['standard']['version'], '1.0.0')
        self.assertIn('unverified', second['sections']['evidence_limits'])
        self.upsert(self.draft(), base=1, ok=False)
        shown = self.cli('review', 'show', '--implementation', 'book-lookup')
        self.assertEqual(shown['revision'], 2)
        self.assertFalse(list(self.project.rglob('review.json')))

    def test_sync_is_idempotent_and_concurrent_conflict_preserves_both(self):
        self.config()
        first = self.upsert(self.draft())
        self.cli('review', 'sync')
        target = self.bundle / 'reviews' / first['project_id'] / first['implementation_id'] / 'review.json'
        before = target.read_bytes()
        self.cli('review', 'sync')
        self.assertEqual(target.read_bytes(), before)
        remote = json.loads(before); remote['sections']['outcome'] = 'Another contributor changed this.'
        target.write_text(json.dumps(remote))
        self.upsert(self.draft('complete'), base=1)
        self.cli('review', 'sync', ok=False)
        self.assertEqual(json.loads(target.read_text())['sections']['outcome'], 'Another contributor changed this.')

    def test_shared_proposal_remains_private_and_unadopted(self):
        self.config(); record = self.upsert(self.draft())
        feedback = self.base / 'feedback.json'
        feedback.write_text(json.dumps({'text': 'Please make the evidence limits more explicit.',
            'attribution': 'human', 'classification': 'shared_standard_proposal',
            'standard_proposal': {'standard_key': 'outcome_evidence', 'standard_version': '1.0.0',
                'proposed_wording': 'Name what remains untested.', 'evidence': ['implementation:book-lookup'],
                'rationale': 'Readers mistook a partial test for complete coverage.',
                'expected_effect': 'More accurate audience expectations.'}}))
        result = self.cli('review', 'feedback', '--implementation', 'book-lookup', '--file', str(feedback))
        self.assertEqual(result['attribution'], 'human')
        self.assertEqual(result['adoption_status'], 'proposed')
        self.assertEqual(result['review_revision'], 1)
        self.cli('review', 'sync')
        self.assertTrue((self.bundle / 'reviews' / record['project_id'] / record['implementation_id'] /
                         'feedback' / (result['id'] + '.json')).is_file())
        self.assertEqual(json.loads(self.standard.read_text())['standard_version'], '1.0.0')

    def test_discovery_updates_and_deliberate_standard_revision(self):
        original = self.config()
        discovery = self.base / 'discovery.json'
        discovery.write_text(json.dumps({key: {'implications': 'Use the stated audience.',
            'evidence': 'A user can finish the task.', 'tradeoffs': 'Unknown until a user trial.'} for key in KEYS}))
        complete = self.cli('project', 'configure', '--discovery', str(discovery))
        self.assertEqual(complete['discovery']['status'], 'addressed_not_verified')
        self.cli('project', 'configure', '--public-facing', 'false')
        self.assertEqual(self.cli('project', 'status')['discovery']['status'], 'not_required')
        version = json.loads(self.standard.read_text()); version['standard_version'] = '1.1.0'
        self.standard.write_text(json.dumps(version))
        updated = self.config()
        self.assertEqual(updated['project_id'], original['project_id'])
        self.assertEqual(updated['discovery']['pending'], KEYS)
        self.assertEqual(updated['standard_history'][0]['standard']['version'], '1.0.0')

    def test_unavailable_source_does_not_invent_a_standard(self):
        data = self.cli('project', 'configure', '--public-facing', 'true')
        self.assertIsNone(data['standard'])
        self.assertEqual(data['discovery']['status'], 'source_unavailable')

    def test_private_outbox_redaction_and_unavailable_bundle(self):
        self.config()
        path = self.draft(); draft = json.loads(path.read_text())
        secret = 'AKIA' + 'Z' * 16
        draft['sections']['your_attention'] = 'Do not share ' + secret
        path.write_text(json.dumps(draft))
        record = self.upsert(path)
        self.assertNotIn(secret, json.dumps(record))
        self.cli('review', 'sync', '--bundle', str(self.base / 'offline'), ok=False)
        self.assertEqual(self.cli('review', 'show', '--implementation', 'book-lookup')['revision'], 1)
        paths = list(self.state.rglob('review.json'))
        self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)
        self.cli('review', 'upsert', '--implementation', 'book-lookup', '--file', str(path),
                 '--base-revision', '1', '--state-dir', str(self.project / 'oops'), ok=False)

    def test_feedback_identity_is_idempotent_and_does_not_imply_human_approval(self):
        self.config(); self.upsert(self.draft())
        import uuid
        event = {'id': str(uuid.uuid4()), 'text': 'I interpret the outcome as useful; no human said this.',
                 'attribution': 'agent_interpretation', 'classification': 'local_clarification'}
        path = self.base / 'feedback.json'; path.write_text(json.dumps(event))
        first = self.cli('review', 'feedback', '--implementation', 'book-lookup', '--file', str(path))
        self.assertEqual(first, self.cli('review', 'feedback', '--implementation', 'book-lookup', '--file', str(path)))
        event['text'] = 'A different statement'; path.write_text(json.dumps(event))
        self.cli('review', 'feedback', '--implementation', 'book-lookup', '--file', str(path), ok=False)

    def test_interrupted_revision_recovers_exact_history_and_refuses_a_different_draft(self):
        self.config(); first = self.upsert(self.draft())
        second = self.upsert(self.draft('complete'), base=1)
        current = next(self.state.rglob('review.json'))
        current.write_text(json.dumps(first))
        self.assertEqual(self.upsert(self.draft('complete'), base=1), second)
        current.write_text(json.dumps(first))
        path = self.draft('complete'); draft = json.loads(path.read_text())
        draft['sections']['outcome'] = 'A different implementation.'
        path.write_text(json.dumps(draft))
        self.upsert(path, base=1, ok=False)
        self.assertEqual(json.loads((current.parent / 'revisions/2.json').read_text()), second)

    def test_historical_feedback_uses_historical_standard(self):
        self.config(); self.upsert(self.draft())
        data = json.loads(self.standard.read_text()); data['standard_version'] = '1.1.0'
        self.standard.write_text(json.dumps(data)); self.config()
        self.upsert(self.draft('complete'), base=1)
        event = {'text': 'Clarify the prior standard.', 'review_revision': 1, 'attribution': 'human',
            'classification': 'shared_standard_proposal', 'standard_proposal': {
                'standard_key': 'outcome_evidence', 'standard_version': '1.0.0',
                'proposed_wording': 'State limits.', 'evidence': ['spec:book-lookup'],
                'rationale': 'Partial evidence was ambiguous.', 'expected_effect': 'Clearer expectations.'}}
        path = self.base / 'feedback.json'; path.write_text(json.dumps(event))
        self.assertEqual(self.cli('review', 'feedback', '--implementation', 'book-lookup', '--file', str(path))['review_revision'], 1)
        event['standard_proposal']['standard_version'] = '1.1.0'; path.write_text(json.dumps(event))
        self.cli('review', 'feedback', '--implementation', 'book-lookup', '--file', str(path), ok=False)

    def test_unrelated_standard_repository_commit_does_not_clear_discovery(self):
        # Source history changes while the actual contract bytes remain identical.
        subprocess.run(['git', 'init', '-q', str(self.base)], check=True)
        subprocess.run(['git', '-C', str(self.base), 'add', 'standard.json'], check=True)
        def commit(message):
            subprocess.run(['git', '-C', str(self.base), '-c', 'user.name=Fixture', '-c',
                'user.email=fixture@example.invalid', 'commit', '-qm', message], check=True)
        commit('standard')
        discovery = self.base / 'discovery.json'
        discovery.write_text(json.dumps({key: {'not_applicable_reason': 'Explicit fixture scope decision.'} for key in KEYS}))
        self.config('--discovery', str(discovery))
        (self.base / 'unrelated.txt').write_text('unrelated')
        subprocess.run(['git', '-C', str(self.base), 'add', 'unrelated.txt'], check=True); commit('unrelated')
        self.assertEqual(self.config()['discovery']['status'], 'addressed_not_verified')

    def test_install_preserves_project_identity_and_private_outbox(self):
        configured = self.config(); review = self.upsert(self.draft())
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'workflow.py'), 'install',
            '--project', str(self.project), '--platform', 'all'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.cli('project', 'status')['project_id'], configured['project_id'])
        self.assertEqual(self.cli('review', 'show', '--implementation', 'book-lookup'), review)


if __name__ == '__main__': unittest.main()
