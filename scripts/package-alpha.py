#!/usr/bin/env python3
"""Build an explicit, source-only alpha bundle. This does not publish a release."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import io
import gzip
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = (
    'controller/control.py', 'controller/engineering.py', 'controller/tickets.py',
    'controller/runtime.py', 'controller/engineering_checks.py',
    'controller/lead_gateway.mjs', 'controller/lead.json', 'controller/pi_inference.py',
    'scripts/prepare-demo.py', 'scripts/package-alpha.py', 'controller/autonomous-lead-inference.service', 'docs/alpha-quickstart.md', 'docs/native-agent-trials.md',
    'README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'docs/releases.md',
    'docs/executable-tickets.md', 'docs/engineering.md', 'docs/overnight-pilot.md',
    'controller/overnight.py', 'controller/autonomous-development-overnight@.service',
    'controller/autonomous-development.service', 'controller/autonomous-development.timer',
    'controller/autonomous-development-pilot@.service',
    'scripts/validate-poc.py', 'scripts/check-dead-code.sh', 'tabellio.validation.json',
    '.github/workflows/product-validation.yml', '.github/workflows/dead-code.yml',
    'tests/test_control.py', 'tests/test_engineering.py', 'tests/test_overnight.py',
    'tests/test_package.py', 'tests/test_pi_inference.py', 'tests/test_portable_runtime.py',
    'tests/test_recovery.py', 'tests/lead_gateway.test.mjs',
    'tests/fixtures/published-demo/sample.py', 'tests/fixtures/published-demo/checks.py',
    'tests/fixtures/published-demo/repair.patch', 'tests/fixtures/published-demo/receipt.json',
)
WORKER = (
    'agent/run-worker.py', 'agent/worker_protocol.py', 'agent/Dockerfile.runtime',
    'agent/bin/runtime_env.py', 'agent/bin/agentshift-readonly-http.py',
    'agent/LICENSE.autonomous-workers', 'agent/LICENSING.md',
)

def source_revision(root):
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = bool(subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True).strip())
    return {'commit': commit, 'dirty': dirty}


def package(stack, target, version='0.1.0-alpha.2'):
    if not re.fullmatch(r'\d+\.\d+\.\d+-alpha\.\d+', version):
        raise ValueError('Use an explicit alpha version, for example 0.1.0-alpha.2')
    files = {name: (ROOT / name).read_bytes() for name in CONTROLLER}
    files.update({name: (stack / name).read_bytes() for name in WORKER})
    license_file = ROOT / 'LICENSE'
    if license_file.is_file():
        files['LICENSE'] = license_file.read_bytes()
    manifest = {'schemaVersion': 1, 'version': version, 'publication': 'experimental-source-prerelease',
                'sources': {'controller': source_revision(ROOT), 'worker': source_revision(stack)},
                'license': 'see LICENSE' if license_file.is_file() else 'pending owner selection; not an open-source release',
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files['MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('wb') as output, gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w') as archive:
        for name, data in sorted(files.items()):
            entry = tarfile.TarInfo('autonomous-development-alpha/' + name)
            entry.size = len(data)
            entry.mode = 0o644
            entry.mtime = 0
            archive.addfile(entry, io.BytesIO(data))
    return manifest

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stack-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', default='0.1.0-alpha.2')
    args = parser.parse_args()
    result = package(args.stack_root.resolve(), args.output.resolve(), args.version)
    print(json.dumps({'output': str(args.output.resolve()), 'version': result['version'], 'fileCount': len(result['files']), 'sources': result['sources'], 'license': result['license']}))
