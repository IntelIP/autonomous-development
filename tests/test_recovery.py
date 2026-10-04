"""Recovery boundaries: retain authority, reuse commits, and avoid duplicate PRs."""
import datetime as dt
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'controller'))
import engineering as e


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.state_patch = patch.object(e.c, 'STATE', self.state)
        self.state_patch.start(); self.addCleanup(self.state_patch.stop)
        self.run = 'a' * 16
        self.directory = self.state / 'runs' / self.run
        self.tree = self.state / 'engineering-workspaces' / self.run / 'integration-0'
        self.tree.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.tree)], check=True)
        (self.tree / 'source.txt').write_text('original\n')
        e.repo_git('add', 'source.txt', cwd=self.tree)
        e.repo_git('-c', 'user.name=Test', '-c', 'user.email=test@localhost', 'commit', '-qm', 'base', cwd=self.tree)
        self.sha = e.repo_git('rev-parse', 'HEAD', cwd=self.tree)
        self.packet = {'schemaVersion': 2, 'recoveryPolicy': e.RECOVERY_POLICY,
            'issueId': 'test-issue', 'contract': {'requiredArtifacts': [], 'projectId': 'project',
            'githubRepository': 'IntelIP/example', 'baseBranch': 'main'}}
        self.report = {'passed': True, 'artifacts': {}}
        self.review = {'headSha': self.sha, 'approved': True, 'findings': [], 'summary': 'Test response'}
        self.receipt = {'runId': self.run, 'status': 'running', 'packet': self.packet,
            'startedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'workers': [], 'checks': [],
            'infrastructureRetries': 0}
        e.checkpoint(self.receipt, self.tree, self.directory, 'validate')

    def test_supplemental_repair_binds_source_scope_and_runs_only_once(self):
        self.packet.update(baseSha=self.sha, leadProfile={'agent': 'test'})
        self.packet['contract'].update(repositoryPath=str(self.tree), sources=['source.txt'],
            scopes={'cli': {'files': ['source.txt'], 'directories': []},
                    'engine': {'files': ['other.txt'], 'directories': []}})
        self.receipt['status'] = 'blocked'
        e.c.save(self.directory / 'receipt.json', self.receipt)
        repair = {'sourceRun': self.run, 'scope': 'cli', 'headSha': self.sha}
        packet = dict(self.packet, approval={'approvedBy': 'owner', 'repair': repair})
        original_digest = e.approval_digest(packet)
        packet['approval']['repair'] = dict(repair, scope='engine')
        self.assertNotEqual(original_digest, e.approval_digest(packet))
        packet['approval']['repair'] = repair
        packet['approval']['packetDigest'] = original_digest
        self.assertEqual(e.repair_source(repair, packet)[0], self.tree)
        (self.state / 'auth').mkdir(); (self.state / 'auth/auth.json').write_text('{}')
        assignment = {'id': 'cli', 'instructions': 'Fix the reported behavior and add the missing regression while preserving all existing interfaces and checks. ' * 2}
        def clone(root, dest, branch, base, **_):
            dest.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git', 'clone', '-q', str(root), str(dest)], check=True)
            e.repo_git('config', 'user.name', 'Test', cwd=dest)
            e.repo_git('config', 'user.email', 'test@localhost', cwd=dest)
            e.repo_git('checkout', '-b', branch, base, cwd=dest)
        def worker(task, _packet, tree, *_):
            (tree / 'source.txt').write_text('repaired\n')
            e.repo_git('add', 'source.txt', cwd=tree)
            e.repo_git('-c', 'user.name=Test', '-c', 'user.email=test@localhost', 'commit', '-qm', 'repair', cwd=tree)
            return {'id': task['id'], 'attempt': 0, 'commit': e.repo_git('rev-parse', 'HEAD', cwd=tree),
                    'branch': e.repo_git('branch', '--show-current', cwd=tree), 'paths': ['source.txt']}
        with patch.object(e, 'validate_packet'), patch.object(e, 'story', return_value={}), \
             patch.object(e.c, 'recover'), patch.object(e.c, 'lead', return_value={'assignments': [assignment]}) as lead, \
             patch.object(e, 'clone', side_effect=clone), patch.object(e, 'worker', side_effect=worker) as engineer, \
             patch.object(e, 'check', return_value={'passed': False}), patch.object(e, 'cleanup'), \
             patch.object(e, 'publish_candidate') as publish:
            result = e.execute(packet, pilot=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('no second coding invocation', result['reason'])
        engineer.assert_called_once(); lead.assert_called_once(); publish.assert_not_called()
        self.assertIn('Active assignment scope IDs: ["cli"]', lead.call_args.args[0])
        with self.assertRaisesRegex(ValueError, 'assignment authority'):
            e.validate_plan({'assignments': [assignment, dict(assignment, id='engine')]}, packet, {'cli'})
        self.assertEqual(e.repo_git('rev-parse', 'HEAD', cwd=self.tree), self.sha)

    def test_review_repair_shares_budget_and_changes_review_identity(self):
        self.packet.update(baseSha=self.sha, leadProfile={})
        self.packet['contract'].update(repositoryPath=str(self.tree), sources=['source.txt'],
            scopes={'cli': {'files': ['source.txt'], 'directories': []}})
        (self.state / 'auth').mkdir()
        (self.state / 'auth/auth.json').write_text('{}')
        assignment = {'id': 'cli', 'instructions': 'Implement only the approved source file and preserve the interface. Add the required focused regression, repair the identified behavior, and report the result.'}
        def clone(root, dest, branch, base, **_):
            dest.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git', 'clone', '-q', str(root), str(dest)], check=True)
            e.repo_git('config', 'user.name', 'Test', cwd=dest)
            e.repo_git('config', 'user.email', 'test@localhost', cwd=dest)
            e.repo_git('checkout', '-b', branch, base, cwd=dest)
        def worker(task, _packet, tree, _directory, _deadline, attempt):
            (tree / 'source.txt').write_text('repair-' + str(attempt) + '\n')
            e.repo_git('add', 'source.txt', cwd=tree)
            e.repo_git('commit', '-qm', 'worker', cwd=tree)
            return {'id': task['id'], 'attempt': attempt, 'commit': e.repo_git('rev-parse', 'HEAD', cwd=tree),
                'branch': e.repo_git('branch', '--show-current', cwd=tree), 'paths': ['source.txt']}
        for last_approved in (False, True):
            packet = dict(self.packet, approval={}, scenario=last_approved)
            phases = []
            def review(_packet, tree, _directory, _report, _deadline, phase='lead-review'):
                phases.append(phase)
                approved = last_approved and len(phases) == 2
                return {'headSha': e.repo_git('rev-parse', 'HEAD', cwd=tree), 'approved': approved,
                    'summary': 'Fixture review', 'findings': [] if approved else [{'path': 'source.txt',
                    'line': 1, 'quote': (tree / 'source.txt').read_text().strip(), 'severity': 'major', 'behavior': 'Required case still fails'}]}
            def publish(receipt, *_): receipt.update(status='draft-pr-created', prUrl='fixture://draft')
            with patch.object(e, 'validate_packet'), patch.object(e, 'story', return_value={}), \
                 patch.object(e.c, 'recover'), patch.object(e.c, 'lead', side_effect=lambda *_, **__: copy.deepcopy({'assignments': [assignment]})), \
                 patch.object(e, 'clone', side_effect=clone), patch.object(e, 'worker', side_effect=worker) as engineer, \
                 patch.object(e, 'check', return_value=self.report), patch.object(e, 'cleanup'), \
                 patch.object(e, 'review_candidate', side_effect=review), patch.object(e, 'publish_candidate', side_effect=publish) as publication:
                result = e.execute(packet, pilot=True)
            self.assertEqual(engineer.call_count, 2, result.get('reason'))
            self.assertEqual(phases, ['lead-review-0', 'lead-review-1'])
            self.assertEqual(result['status'], 'draft-pr-created' if last_approved else 'blocked')
            self.assertEqual(publication.call_count, int(last_approved))
            self.assertEqual([w['attempt'] for w in result['workers']], [0, 1])

    def test_interrupted_validation_resumes_without_replaying_workers(self):
        with patch.object(e.c, 'command', return_value=''):
            e.c.recover()
        saved = json.loads((self.directory / 'receipt.json').read_text())
        self.assertEqual(saved['status'], 'interrupted')
        def publish(receipt, *_):
            receipt.update(status='draft-pr-created', headSha=self.sha, prUrl='test://draft')
        with patch.object(e, 'worker') as worker, patch.object(e, 'check', return_value=self.report) as check, \
             patch.object(e, 'review_candidate', return_value=self.review), \
             patch.object(e, 'publish_candidate', side_effect=publish), patch.object(e, 'cleanup'), \
             patch.object(e, 'validate_packet'), patch.object(e, 'story', return_value={}):
            result = e.resume_candidate(self.packet, saved, self.directory, time.time() + 60)
        self.assertEqual(result['status'], 'draft-pr-created')
        self.assertEqual(result['infrastructureRetries'], 1)
        self.assertEqual(result['startedAt'], self.receipt['startedAt'])
        self.assertEqual(e.repo_git('rev-parse', 'HEAD', cwd=self.tree), self.sha)
        worker.assert_not_called(); check.assert_called_once()

    def test_changed_candidate_and_expired_deadline_cannot_publish(self):
        (self.tree / 'source.txt').write_text('changed\n')
        with patch.object(e, 'publish_candidate') as publish:
            with self.assertRaisesRegex(ValueError, 'changed'):
                e.finish_candidate(self.receipt, self.directory, time.time() + 60)
            with self.assertRaisesRegex(ValueError, 'deadline'):
                e.finish_candidate(self.receipt, self.directory, time.time() - 1)
        publish.assert_not_called()

    def test_retry_budget_does_not_reset_and_worker_interruption_blocks(self):
        self.receipt['infrastructureRetries'] = 1
        with patch.object(e, 'finish_candidate') as finish:
            result = e.resume_candidate(self.packet, self.receipt, self.directory, time.time() + 60)
        self.assertEqual(result['status'], 'blocked'); finish.assert_not_called()
        self.receipt.update(status='running', infrastructureRetries=0)
        self.receipt.pop('checkpoint')
        e.c.save(self.directory / 'receipt.json', self.receipt)
        with patch.object(e.c, 'command', return_value=''):
            e.c.recover()
        self.assertEqual(json.loads((self.directory / 'receipt.json').read_text())['status'], 'blocked')

    def test_existing_exact_pr_is_reconciled_without_another_push_or_create(self):
        e.checkpoint(self.receipt, self.tree, self.directory, 'publish', self.report)
        existing = [{'url': 'https://github.com/IntelIP/example/pull/1', 'headRefOid': self.sha,
                     'baseRefName': 'main', 'state': 'OPEN'}]
        original_git = e.repo_git
        calls = []
        def git(*args, **kwargs):
            calls.append(args)
            return original_git(*args, **kwargs)
        original_command = e.c.command
        def command(args, **kwargs):
            if 'pr' in args:
                self.assertEqual(args[1:3], ['pr', 'list'])
                return json.dumps(existing)
            return original_command(args, **kwargs)
        with patch.object(e, 'repo_git', side_effect=git), patch.object(e.c, 'command', side_effect=command):
            e.publish_candidate(self.receipt, self.tree, self.directory)
        self.assertEqual(self.receipt['prUrl'], existing[0]['url'])
        self.assertFalse(any('push' in args for args in calls))

    def test_ownership_cannot_escape_and_code_failure_is_not_infrastructure_retry(self):
        with patch.object(e.c, 'command') as command:
            with self.assertRaises(ValueError):
                e.prepare_workspace(self.state)
        command.assert_not_called()
        e.record_failure(self.receipt, ValueError('Lead review declined result'), time.time() + 60)
        self.assertEqual(self.receipt['status'], 'blocked')
        e.record_failure(self.receipt, TimeoutError('Connection interrupted'), time.time() + 60)
        self.assertEqual(self.receipt['status'], 'retryable')

    def test_worker_transport_failure_is_not_a_code_repair(self):
        packet = dict(self.packet, issueTitle='Test', imageId='image', ticket={'interfaces': []}, acceptance='{}')
        packet['contract'] = dict(packet['contract'], scopes={'engine': {'files': ['source.txt'], 'directories': []}},
            stackRoot='/unused', sources=['source.txt'], setup=[], checks=[])
        with patch.object(e.subprocess, 'run', side_effect=TimeoutError('transport lost')), patch.object(e, 'cleanup'):
            with self.assertRaisesRegex(e.WorkerInfrastructureError, 'no automatic replay'):
                e.worker({'id': 'engine', 'instructions': 'Test'}, packet, self.tree, self.directory, time.time() + 60, 0)

    def test_stale_queue_admission_preserves_saved_work(self):
        identity = e.c.digest(json.dumps(self.packet, sort_keys=True).encode())[:16]
        saved = dict(self.receipt, runId=identity, status='interrupted', workers=[{'commit': self.sha}])
        path = self.state / 'runs' / identity / 'receipt.json'
        e.c.save(path, saved)
        e.c.save(self.state / 'queue' / 'ticket.json', self.packet)
        with patch.object(sys, 'argv', ['control.py', 'tick']), patch.object(e.c, 'window', return_value=(True, 60)), \
             patch.object(e, 'execute', side_effect=ValueError('Stale ticket')):
            e.c.main()
        result = json.loads(path.read_text())
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['workers'], saved['workers'])
        self.assertEqual(result['checkpoint'], saved['checkpoint'])


if __name__ == '__main__':
    unittest.main()
