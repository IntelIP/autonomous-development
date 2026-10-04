import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'controller'))
import engineering as e


class EngineeringContract(unittest.TestCase):
    def test_lead_profile_rejects_wrong_model_without_fallback(self):
        profile = {'agent': 'autonomous-lead-codex', 'provider': 'pi-subscription', 'model': 'gpt-6-sol'}
        envelope = {'result': {'payloads': [{'text': '{"approved":true}'}],
                              'meta': {'agentMeta': {'provider': 'inference', 'model': 'gpt-oss-pi:latest'}}}}
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(e.c, 'gateway_request', return_value=json.dumps(envelope)) as command:
                with self.assertRaisesRegex(ValueError, 'no fallback'):
                    e.c.lead('Review', Path(temp), 'review', time.time() + 60, profile=profile)
                self.assertEqual(command.call_count, 1)
                self.assertEqual(profile['agent'], command.call_args.args[4])
            envelope['result']['meta']['agentMeta'] = {'provider': profile['provider'], 'model': profile['model']}
            with patch.object(e.c, 'gateway_request', return_value=json.dumps(envelope)):
                self.assertEqual(e.c.lead('Review', Path(temp), 'review', time.time() + 60, profile=profile), {'approved': True})

    def test_review_rejects_stale_or_unanchored_findings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'code.go').write_text('func pathsAlias() {}\n')
            decision = {'headSha': 'a' * 40, 'approved': False, 'summary': 'Defect found',
                        'findings': [{'path': 'code.go', 'line': 1, 'quote': 'func pathsAlias()', 'behavior': 'Specific incorrect behavior', 'severity': 'major'}]}
            e.validate_review(decision, 'a' * 40, root)
            for change in [lambda r: r.update(headSha='b' * 40), lambda r: r.update(findings=[]),
                           lambda r: r['findings'][0].update(quote='ConfidenceHigh'),
                           lambda r: r['findings'][0].update(path='../outside.go')]:
                bad = copy.deepcopy(decision); change(bad)
                with self.assertRaises(ValueError): e.validate_review(bad, 'a' * 40, root)

    def test_review_ignores_quote_indentation_but_keeps_source_text_and_line(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'code.go').write_text('\treturn value\nother line\n')
            decision = {'headSha': 'a' * 40, 'approved': False, 'summary': 'Defect found',
                'findings': [{'path': 'code.go', 'line': 1, 'quote': '  return value  ',
                    'behavior': 'Specific incorrect behavior', 'severity': 'major'}]}
            e.validate_review(decision, 'a' * 40, root)
            for field, value in [('quote', 'return different'), ('line', 2)]:
                bad = copy.deepcopy(decision); bad['findings'][0][field] = value
                with self.assertRaises(ValueError): e.validate_review(bad, 'a' * 40, root)

    def ticket(self, contract):
        return {'schemaVersion': 1, 'outcome': 'Explain cost variance to an engineer',
                'acceptance': [{'id': 'variance', 'scenario': 'Actual exceeds forecast', 'expected': 'Variance reconciles', 'check': 0}],
                'exclusions': ['No deployment'], 'dependencies': [],
                'interfaces': [{'owners': list(contract['scopes']), 'contract': 'Both engineers use the same explicit input and output contract.'}],
                'execution': contract, 'limits': e.c.LIMITS,
                'completion': {'success': 'draft-pr', 'failure': 'blocked-report', 'merge': 'human'}}

    def test_ticket_separates_history_and_rejects_missing_contracts(self):
        ticket = self.ticket(self.contract(Path('/tmp/product')))
        def description(value):
            return 'Historical failure: eight tests failed.\n```autonomous-ticket\n' + json.dumps(value) + '\n```\nLater history.'
        parsed = e.tickets.extract(description(ticket), e.validate_contract, e.c.LIMITS)
        self.assertNotIn('Historical failure', e.tickets.acceptance(parsed))
        for change in [lambda t: t.update(interfaces=[]), lambda t: t.update(acceptance=[]),
                       lambda t: t['acceptance'][0].update(check=7), lambda t: t['completion'].update(merge='automatic'),
                       lambda t: t['interfaces'][0].update(owners=['implementation'])]:
            bad = copy.deepcopy(ticket); change(bad)
            with self.assertRaises(ValueError):
                e.tickets.extract(description(bad), e.validate_contract, e.c.LIMITS)
        with self.assertRaises(ValueError):
            e.tickets.extract('Implement something useful.', e.validate_contract, e.c.LIMITS)

    def test_lead_json_retry_is_strict_bounded_and_recorded(self):
        malformed = json.dumps({'payloads': [{'text': '{"assignments":[{"instructions":"unterminated'}]})
        valid = json.dumps({'payloads': [{'text': '{"assignments": []}'}]})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(e.c, 'gateway_request', side_effect=[malformed, valid]) as command:
                self.assertEqual(e.c.lead('Return assignments.', root, 'plan', time.time() + 60), {'assignments': []})
                self.assertEqual(command.call_count, 2)
                self.assertIn('invalid JSON', command.call_args.args[0])
                self.assertEqual((root / 'plan-raw.json').read_text().strip(), malformed)
                self.assertEqual((root / 'plan-json-retry-raw.json').read_text().strip(), valid)
            with patch.object(e.c, 'gateway_request', return_value=malformed) as command:
                with self.assertRaises(json.JSONDecodeError):
                    e.c.lead('Return assignments.', root, 'bad', time.time() + 60)
                self.assertEqual(command.call_count, 2)
            with patch.object(e.c, 'gateway_request', return_value=malformed) as command, \
                 patch.object(e.c.time, 'time', side_effect=[100, 100, 161]):
                with self.assertRaises(TimeoutError):
                    e.c.lead('Return assignments.', root, 'expired', 160)
                self.assertEqual(command.call_count, 1)

    def test_lead_transport_preserves_large_prompt_as_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prompt = '\U0001f4a1' * 40000 + ' $(printf injected) `printf injected`\nend'
            envelope = {'payloads': [{'text': '{"approved":true}'}]}
            def invoke(argv, **_kwargs):
                self.assertTrue(all(len(arg.encode()) < 32768 for arg in argv))
                self.assertNotIn(prompt, argv)
                request = json.loads((root / 'transport-test-gateway/request.json').read_text())
                self.assertEqual(request['prompt'], prompt)
                if 'download' in argv:
                    Path(argv[-1]).write_text(json.dumps({'requestId': request['requestId'], 'result': envelope}))
                return json.dumps(envelope)
            with patch.object(e.c, 'command', side_effect=invoke):
                self.assertEqual(e.c.lead(prompt, root, 'transport-test', time.time() + 60), {'approved': True})
            with patch.object(e.c, 'command') as command:
                self.assertEqual(e.c.lead(prompt, root, 'transport-test', time.time() + 60), {'approved': True})
                command.assert_not_called()
            with patch.object(e.c, 'command') as command:
                with self.assertRaisesRegex(ValueError, 'context budget'):
                    e.c.lead('\U0001f4a1' * 140000, root, 'too-large', time.time() + 60)
                command.assert_not_called()

    def test_gateway_client_lifecycle(self):
        subprocess.run(['node', '--test', str(e.c.ROOT / 'tests/lead_gateway.test.mjs')], check=True, capture_output=True, text=True)

    def test_resume_preserves_product_authority_and_repair_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run = 'a' * 16; directory = root / 'runs' / run
            directory.mkdir(parents=True)
            packet = {'contract': self.contract(root), 'imageId': 'sha256:original', 'controllerSources': {'controller': 'old'}}
            previous = {'status': 'blocked', 'packet': packet, 'checks': [],
                        'workers': [{'id': key, 'attempt': 0} for key in packet['contract']['scopes']]}
            receipt = directory / 'receipt.json'; receipt.write_text(json.dumps(previous))
            updated = dict(packet, controllerSources={'controller': 'fixed'})
            with patch.object(e.c, 'STATE', root):
                self.assertEqual(e.resume_receipt(run, updated), previous)
                with self.assertRaisesRegex(ValueError, 'authority'):
                    e.resume_receipt(run, dict(updated, imageId='sha256:changed'))
                (directory / 'lead-repair-0.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'initial assignments'):
                    e.resume_receipt(run, updated)

    def contract(self, root):
        return {'repositoryPath': str(root), 'githubRepository': 'IntelIP/example', 'baseBranch': 'main', 'projectId': 'a' * 36,
                'sources': ['README.md'], 'scopes': {'implementation': {'files': ['runtime/review.py'], 'directories': []},
                'tests': {'files': [], 'directories': ['tests']}}, 'setup': [], 'checks': [['python3', '-m', 'unittest']],
                'stackRoot': str(root), 'workerImage': 'agent-stack:test', 'requiredArtifacts': []}

    def test_contract_rejects_overlap_escape_missing_checks_and_extra_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            contract = self.contract(Path(temp))
            e.validate_contract(contract)
            for mutate in [lambda c: c['scopes']['tests'].update(directories=['runtime']),
                           lambda c: c['scopes']['tests'].update(directories=['../outside']),
                           lambda c: c.update(checks=[]), lambda c: c.update(autoMerge=True)]:
                bad = copy.deepcopy(contract); mutate(bad)
                with self.assertRaises(ValueError): e.validate_contract(bad)

    def test_lead_cannot_change_scope_or_drop_an_engineer(self):
        packet = {'contract': self.contract(Path('/tmp/product'))}
        plan = {'assignments': [{'id': key, 'instructions': 'Implement the assigned product behavior from the approved references. Preserve existing contracts and edge cases. Add focused tests and report the exact commands and results.'} for key in packet['contract']['scopes']]}
        self.assertEqual(e.validate_plan(plan, packet), plan)
        bad = copy.deepcopy(plan); bad['assignments'][0]['path'] = '/etc/passwd'
        with self.assertRaises(ValueError): e.validate_plan(bad, packet)
        bad = copy.deepcopy(plan); bad['assignments'].pop()
        with self.assertRaises(ValueError): e.validate_plan(bad, packet)

    def test_packet_invalidates_changed_issue_image_and_driver(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['README.md', *e.DRIVER_FILES]:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('source')
            contract = self.contract(root)
            ticket = self.ticket(contract)
            item = {'id': 'b' * 36, 'project_id': contract['projectId'], 'updated_at': 'revision-1', 'title': 'Real feature',
                    'description': '```autonomous-ticket\n' + json.dumps(ticket) + '\n```'}
            def git(*args, **_kwargs): return 'a' * 40 if args[0] == 'rev-parse' else ''
            with patch.object(e, 'repo_git', side_effect=git), patch.object(e.c, 'command', return_value='sha256:' + '1' * 64):
                packet = e.compile_packet(contract, item)
                packet['approval'] = {'approvedBy': 'owner', 'packetDigest': e.c.digest(json.dumps(packet, sort_keys=True).encode())}
                e.validate_packet(packet, item)
                with self.assertRaisesRegex(ValueError, 'stale'): e.validate_packet(packet, dict(item, updated_at='revision-2'))
                (root / e.DRIVER_FILES[0]).write_text('changed runtime')
                with self.assertRaisesRegex(ValueError, 'stale'): e.validate_packet(packet, item)
                (root / e.DRIVER_FILES[0]).write_text('source')
                with patch.object(e.c, 'command', return_value='sha256:' + '2' * 64):
                    with self.assertRaisesRegex(ValueError, 'stale'): e.validate_packet(packet, item)

    def test_packet_checks_live_dependency_before_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['README.md', *e.DRIVER_FILES]:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('source')
            contract = self.contract(root); ticket = self.ticket(contract)
            ticket['dependencies'] = ['d' * 36]
            item = {'id': 'b' * 36, 'project_id': contract['projectId'], 'updated_at': 'revision-1', 'title': 'Real feature',
                    'description': '```autonomous-ticket\n' + json.dumps(ticket) + '\n```'}
            def git(*args, **_kwargs): return 'a' * 40 if args[0] == 'rev-parse' else ''
            with patch.object(e, 'repo_git', side_effect=git), patch.object(e.c, 'command', return_value='sha256:image'), \
                 patch.object(e, 'story', return_value={'updated_at': 'dependency-1', 'completed_at': '2026-01-01'}) as dependency:
                packet = e.compile_packet(None, item)
                packet['approval'] = {'approvedBy': 'owner', 'packetDigest': e.c.digest(json.dumps(packet, sort_keys=True).encode())}
                e.validate_packet(packet, item)
                dependency.return_value = {'updated_at': 'dependency-2', 'completed_at': None}
                with self.assertRaisesRegex(ValueError, 'Dependency is not complete'):
                    e.validate_packet(packet, item)

    def test_ownership_does_not_match_neighboring_directory(self):
        scope = {'files': ['runtime/review.py'], 'directories': ['tests']}
        self.assertTrue(e.owns('tests/test_review.py', scope))
        self.assertFalse(e.owns('tests-other/test_review.py', scope))
        self.assertFalse(e.owns('runtime/unrelated.py', scope))

    def test_cleanup_targets_only_the_interrupted_assignment(self):
        with patch.object(e.c, 'command', side_effect=['container-1\n', '']) as command:
            e.cleanup('a' * 16, 'implementation')
            query = command.call_args_list[0].args[0]
            self.assertIn('label=ad.run=' + 'a' * 16, query)
            self.assertIn('label=ad.assignment=implementation', query)
            self.assertEqual(command.call_args_list[1].args[0][-3:], ['rm', '-f', 'container-1'])


if __name__ == '__main__': unittest.main()
