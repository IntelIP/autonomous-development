#!/usr/bin/env python3
"""Run operator-defined acceptance commands in a container without provider credentials."""
import json
from pathlib import Path
import subprocess
import shutil
import time

root = Path('/results')
spec = json.loads((root / 'spec.json').read_text())
deadline = time.monotonic() + spec['seconds']
report = {'passed': True, 'commands': []}
try:
    # Validators may create Git worktrees. Keep their metadata writes in container memory.
    shutil.copytree('/input-git', '/workspace/.git', dirs_exist_ok=True, symlinks=True)
    for phase in ('setup', 'checks'):
        for index, argv in enumerate(spec[phase]):
            path = root / f'{phase}-{index}.log'
            with path.open('w') as log:
                result = subprocess.run(argv, cwd='/workspace', stdout=log, stderr=subprocess.STDOUT, timeout=max(1, deadline - time.monotonic()))
            report['commands'].append({'phase': phase, 'argv': argv, 'exitCode': result.returncode, 'log': path.name})
            if result.returncode:
                report.update(passed=False, failure=path.read_text()[-5000:])
                raise RuntimeError('Acceptance command failed')
except Exception as error:
    report.update(passed=False, error=str(error))
(root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
raise SystemExit(0 if report['passed'] else 1)
