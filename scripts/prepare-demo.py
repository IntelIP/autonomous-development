#!/usr/bin/env python3
"""Create a local, seeded demonstration repository and an executable file ticket."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def prepare(directory, github_repository, stack_root, image, agent, model, workflow):
    if directory.exists(): raise ValueError('Choose a new directory; existing work is never replaced')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', github_repository): raise ValueError('Expected owner/repository')
    directory.mkdir(parents=True)
    bug = workflow == 'bugfix'
    (directory / 'sample.py').write_text(
        '"""Demonstration data: summarize a list of integers."""\nimport json\n\n'
        'def summarize(values):\n    return {"count": len(values), "total": '
        + ('len(values)' if bug else 'sum(values)') + '}\n\n'
        'if __name__ == "__main__":\n    print(json.dumps(summarize([1, 2, 3]), sort_keys=True))\n')
    (directory / 'README.md').write_text('# Demonstration repository\n\nSeeded example, not a production system.\n\n'
        'Run `python3 sample.py` to summarize the example measurements.\n\n'
        'Expected output:\n```json\n' + ('{"count": 3, "total": 6}' if bug else '{"count": 0, "total": 0}') + '\n```\n')
    checks = 'import json\nfrom pathlib import Path\nfrom sample import summarize\n'
    checks += 'assert summarize([]) == {"count": 0, "total": 0}\nassert summarize([1, 2, 3]) == {"count": 3, "total": 6}\nassert summarize([-2, 5]) == {"count": 2, "total": 3}\n'
    if not bug: checks += 'assert json.dumps(summarize([1, 2, 3]), sort_keys=True) in Path("README.md").read_text()\n'
    (directory / 'checks.py').write_text(checks)
    (directory / '.gitignore').write_text('.alpha/\n__pycache__/\n')
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(directory)], check=True)
    for name, value in [('user.name', 'Autonomous Development Demo'), ('user.email', 'demo@example.invalid')]:
        subprocess.run(['git', '-C', str(directory), 'config', name, value], check=True)
    subprocess.run(['git', '-C', str(directory), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(directory), 'commit', '-qm', 'Seed explicit demonstration task'], check=True)
    identity, project = str(uuid.uuid4()), str(uuid.uuid4())
    outcome = 'Correctly summarize integer measurements' if bug else 'Document the actual runnable example output'
    contract = {'repositoryPath': str(directory), 'githubRepository': github_repository, 'baseBranch': 'main',
        'projectId': project, 'sources': ['README.md', 'sample.py', 'checks.py'],
        'scopes': {'implementation': {'files': ['sample.py' if bug else 'README.md'], 'directories': []}},
        'setup': [], 'checks': [['python3', 'checks.py']], 'requiredArtifacts': [],
        'stackRoot': str(stack_root), 'workerImage': image, 'workerAgent': agent,
        'workerProfile': 'minimal'}
    if model:
        contract['workerModel'] = model
    ticket = {'schemaVersion': 1, 'outcome': outcome,
        'acceptance': [{'id': workflow, 'scenario': 'Run empty, positive and mixed-sign integer examples and the documented example',
            'expected': 'All committed checks pass. Keep checks and public interfaces unchanged.', 'check': 0}],
        'exclusions': ['No merge, deployment, new dependencies, or edits outside the assigned file.'],
        'dependencies': [], 'interfaces': [{'owners': ['implementation'],
            'contract': 'sample.summarize(values) accepts a list of integers and returns count=len(values), total=sum(values).'}],
        'execution': contract, 'limits': {'workers': 2, 'repairAttempts': 1, 'runSeconds': 3600},
        'completion': {'success': 'draft-pr', 'failure': 'blocked-report', 'merge': 'human'}}
    item = {'id': identity, 'project_id': project, 'title': outcome,
        'description': '```autonomous-ticket\n' + json.dumps(ticket, indent=2) + '\n```'}
    target = directory / '.alpha/tickets.json'; target.parent.mkdir()
    target.write_text(json.dumps({identity: item}, indent=2) + '\n')
    return {'ticketFile': str(target), 'projectId': project, 'issueId': identity,
            'repository': str(directory), 'publication': 'Publish the seeded main branch to your own target repository before running the controller.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--github-repository', required=True)
    parser.add_argument('--stack-root', type=Path, default=ROOT)
    parser.add_argument('--image', required=True)
    parser.add_argument('--agent', choices=['pi', 'codex', 'claude-code', 'opencode'], default='pi')
    parser.add_argument('--model', required=True)
    parser.add_argument('--workflow', choices=['bugfix', 'docs'], default='bugfix')
    args = parser.parse_args()
    print(json.dumps(prepare(args.directory.resolve(), args.github_repository, args.stack_root.resolve(),
                             args.image, args.agent, args.model, args.workflow), indent=2))
