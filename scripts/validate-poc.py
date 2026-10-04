#!/usr/bin/env python3
"""Persist each static validator invocation, including failed commands."""
import json
from pathlib import Path
import subprocess
import time

root=Path(__file__).resolve().parents[1]
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip())
manifest=json.loads((root/'tabellio.validation.json').read_text())
results=[]
for validator in manifest['validators']:
    start=time.time()
    path=root/validator['evidence']['path'];path.parent.mkdir(parents=True,exist_ok=True)
    try:
        result=subprocess.run(validator['argv'],cwd=root/validator['cwd'],capture_output=True,text=True,timeout=validator['timeoutMs']/1000)
        log=result.stdout+'\n'+result.stderr;status='passed' if result.returncode==0 else 'failed'
    except Exception as error:log=str(error);status='blocked'
    path.with_suffix('.log').write_text(log)
    evidence={'validatorId':validator['id'],'headSha':head,'sourceDirty':dirty,'status':status,'elapsedSeconds':time.time()-start,'log':str(path.with_suffix('.log').relative_to(root))}
    path.write_text(json.dumps(evidence,indent=2)+'\n');results.append(evidence)
    print(validator['id'],status)
status='failed' if any(r['status']=='failed' for r in results) else 'blocked' if dirty or any(r['status']=='blocked' for r in results) else 'passed'
(root/'.evidence/result.json').write_text(json.dumps({'headSha':head,'sourceDirty':dirty,'status':status,'reason':'Uncommitted source changes; exact-commit validation requires a clean checkout' if dirty and status=='blocked' else None,'validators':results},indent=2)+'\n')
raise SystemExit(0 if status=='passed' else 1)
