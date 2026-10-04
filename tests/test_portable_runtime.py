import copy
import importlib.util
import subprocess
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'controller'))
import engineering as e


class PortableRuntime(unittest.TestCase):
    def test_local_ticket_revision_changes_with_content(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'tickets.json'
            identity = 'a' * 36
            item = {'id': identity, 'project_id': 'project', 'title': 'Task', 'description': 'Before'}
            path.write_text(json.dumps({identity: item}))
            with patch.dict(os.environ, {'AD_TICKETS_FILE': str(path)}):
                before = e.story(identity, 'project')
                item['description'] = 'After'
                path.write_text(json.dumps({identity: item}))
                after = e.story(identity, 'project')
                self.assertNotEqual(before['updated_at'], after['updated_at'])
                with self.assertRaises(ValueError): e.story(identity, 'other-project')

    def test_demo_contracts_and_seeded_failures(self):
        spec = importlib.util.spec_from_file_location('demo', Path(__file__).parents[1] / 'scripts/prepare-demo.py')
        demo = importlib.util.module_from_spec(spec); spec.loader.exec_module(demo)
        with tempfile.TemporaryDirectory() as temp:
            for workflow in ('bugfix', 'docs'):
                root = Path(temp) / workflow
                info = demo.prepare(root, 'example/demo', Path(temp), 'demo:1', 'codex', '', workflow)
                with patch.dict(os.environ, {'AD_TICKETS_FILE': info['ticketFile']}):
                    item = e.story(info['issueId'], info['projectId'])
                ticket = e.tickets.extract(item['description'], e.validate_contract, e.c.LIMITS)
                e.validate_contract(ticket['execution'])
                self.assertNotIn('workerModel', ticket['execution'])
                self.assertNotEqual(subprocess.run(['python3', 'checks.py'], cwd=root, capture_output=True).returncode, 0)

    def test_runtime_choice_is_part_of_approved_authority(self):
        packet = {'contract': {'workerAgent': 'pi'}, 'approval': {'approvedBy': 'operator'}}
        before = e.approval_digest(packet)
        changed = copy.deepcopy(packet)
        changed['contract']['workerAgent'] = 'codex'
        self.assertNotEqual(before, e.approval_digest(changed))


if __name__ == '__main__': unittest.main()
