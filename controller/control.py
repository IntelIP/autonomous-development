#!/usr/bin/env python3
"""Bounded Windows/WSL controller. Model output is data, never executable policy."""
import argparse
import concurrent.futures
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request
import uuid
from zoneinfo import ZoneInfo
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get('AD_STATE', '/var/lib/autonomous-development'))
DOCKER = ['docker'] + (['-H', runtime.settings()['dockerHost']] if runtime.settings()['dockerHost'] else [])
SOURCES = ['docs/product.md', 'docs/claims.md', 'docs/architecture.md', 'docs/design.md']
OWNERS = {'proposition': 'src/content/products/backintel.md', 'narrative': 'src/content/night-shift.md'}
LIMITS = {'workers': 2, 'repairAttempts': 1, 'runSeconds': 3600}
PROJECT = 'ec593752-b03a-45db-8e60-06cf68eae13a'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def command(args, cwd=ROOT, timeout=60):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {result.stderr[-1800:]}')
    return result.stdout.strip()


def git(*args, cwd=ROOT):
    return command(['git', *args], cwd=cwd)


def window(now=None):
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    if 6 <= now.hour < 22:
        return False, 0
    day = now.date() + dt.timedelta(days=1 if now.hour >= 22 else 0)
    end = dt.datetime.combine(day, dt.time(6), now.tzinfo)
    return True, int(end.timestamp() - now.timestamp())


def issue(issue_id):
    if not re.fullmatch(r'[0-9a-f-]{36}', issue_id):
        raise ValueError('Invalid issue ID')
    with urllib.request.urlopen('http://127.0.0.1:3000/api/remote/issues/' + issue_id, timeout=15) as response:
        result = json.load(response)
    if not result.get('success') or result['data']['project_id'] != PROJECT:
        raise ValueError('Issue unavailable or outside Autonomous Development')
    return result['data']


def references(root=ROOT):
    index = json.loads((root / 'docs/sources.json').read_text())
    if {s['path'] for s in index['sources']} != set(SOURCES):
        raise ValueError('Required source set missing or conflicting')
    for source in index['sources']:
        p = root / source['path']
        if not p.is_file() or p.is_symlink() or digest(p.read_bytes()) != source['sha256']:
            raise ValueError('Stale or missing source: ' + source['path'])
        if not source.get('owner') or not source.get('revision'):
            raise ValueError('Source owner/revision missing')
    return index['sources']


def compile_packet(story, root=ROOT):
    if story.get('project_id') != PROJECT or not story.get('description') or not story.get('updated_at'):
        raise ValueError('Story lacks project, acceptance, or revision')
    if 'Acceptance' not in story['description']:
        raise ValueError('Story lacks acceptance criteria')
    base = git('rev-parse', 'HEAD', cwd=root)
    return {
        'schemaVersion': 1, 'issueId': story['id'], 'issueRevision': story['updated_at'],
        'issueTitle': story['title'], 'acceptance': story['description'],
        'baseSha': base, 'sourceSha': base, 'sources': references(root),
        'ownedPaths': OWNERS, 'excluded': ['all other paths', 'merge', 'deploy', 'external messages'],
        'checks': [['npm', 'run', 'build'], ['npm', 'run', 'typecheck']],
        'branchPlan': 'autonomous/<run-id>/<assignment-id>', 'limits': LIMITS,
        'stopConditions': ['stale issue/source', 'invalid lead plan', 'check failure after one repair', 'deadline', 'auth or quota failure'],
        'approval': None,
    }


def validate_packet(packet, root=ROOT, current=None):
    expected = {'schemaVersion','issueId','issueRevision','issueTitle','acceptance','baseSha','sourceSha','sources','ownedPaths','excluded','checks','branchPlan','limits','stopConditions','approval'}
    if set(packet) != expected or packet['schemaVersion'] != 1:
        raise ValueError('Invalid packet fields')
    if packet['ownedPaths'] != OWNERS or packet['limits'] != LIMITS:
        raise ValueError('Packet broadens authority')
    if packet['checks'] != [['npm','run','build'], ['npm','run','typecheck']]:
        raise ValueError('Unexpected validation command')
    if packet['sources'] != references(root) or packet['baseSha'] != git('rev-parse','HEAD',cwd=root) or packet['sourceSha'] != packet['baseSha']:
        raise ValueError('Stale source/base revision')
    approval = packet['approval']
    if not isinstance(approval, dict) or set(approval) != {'owner','approvedAt','packetDigest'}:
        raise ValueError('Explicit queue approval missing')
    original = dict(packet, approval=None)
    if approval['owner'] != 'Hudson Aikins' or approval['packetDigest'] != digest(json.dumps(original,sort_keys=True).encode()):
        raise ValueError('Approval does not match packet')
    if current is not None and (current['id'] != packet['issueId'] or current['updated_at'] != packet['issueRevision']):
        raise ValueError('Stale issue revision')


def validate_plan(plan):
    if not isinstance(plan,dict) or set(plan) != {'assignments'} or not isinstance(plan['assignments'], list) or len(plan['assignments']) != 2:
        raise ValueError('Lead must return exactly two assignments')
    seen = set()
    for task in plan['assignments']:
        if set(task) != {'id','path','instructions','sourceIds'}:
            raise ValueError('Unexpected assignment fields')
        if task['id'] in seen or OWNERS.get(task['id']) != task['path']:
            raise ValueError('Invalid or overlapping ownership')
        if set(task['sourceIds']) != {'product','claims','architecture','design'}:
            raise ValueError('Unknown or missing source IDs')
        if not isinstance(task['instructions'], str) or not 120 <= len(task['instructions']) <= 6000:
            raise ValueError('Invalid instructions')
        seen.add(task['id'])
    return plan


def gateway_request(prompt, directory, phase, deadline, agent):
    """Keep source text in files; OpenClaw's client owns Gateway authentication."""
    target = directory / (phase + '-gateway')
    target.mkdir(mode=0o700, exist_ok=True)
    request_path = target / 'request.json'
    if request_path.exists():
        request = json.loads(request_path.read_text())
        if request['prompt'] != prompt or request['agent'] != agent:
            raise ValueError('Saved lead request differs; do not replay another request')
    else:
        request = {'requestId': str(uuid.uuid4()), 'agent': agent, 'prompt': prompt,
                   'deadlineMs': int(deadline * 1000)}
        save(request_path, request)
    receipt_path = target / 'gateway-receipt.json'
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get('requestId') != request['requestId']:
            raise ValueError('Saved Gateway receipt belongs to another request')
        if receipt.get('result'):
            return json.dumps(receipt['result'])
    shutil.copyfile(ROOT / 'controller/lead_gateway.mjs', target / 'lead_gateway.mjs')
    remote = '/sandbox/autonomous-requests/' + request['requestId']
    command([runtime.settings()['openshell'], 'sandbox', 'upload', '--gateway', runtime.settings()['gateway'],
             runtime.settings()['sandbox'], str(target), remote], timeout=max(1, min(60, deadline - time.time())))
    remote += '/' + target.name
    try:
        return command([runtime.settings()['nemoclaw'], runtime.settings()['sandbox'], 'exec', '--', 'node',
                        remote + '/lead_gateway.mjs', remote + '/request.json'],
                       timeout=max(1, deadline - time.time()))
    finally:
        try:
            command([runtime.settings()['openshell'], 'sandbox', 'download', '--gateway', runtime.settings()['gateway'],
                     runtime.settings()['sandbox'], remote + '/gateway-receipt.json', str(receipt_path)], timeout=15)
        except (RuntimeError, subprocess.TimeoutExpired):
            pass  # Pre-acceptance failures have no receipt; the saved request remains.


def lead(prompt, directory, phase, deadline, profile=None):
    if len(prompt.encode()) > 512 * 1024:
        raise ValueError('Lead prompt exceeds bounded context budget')
    deadline = min(deadline, time.time() + 180)
    agent = profile['agent'] if profile else 'autonomous-lead'
    for attempt in range(2):
        remaining = int(deadline - time.time())
        if remaining <= 0:
            raise TimeoutError('Lead deadline expired before structured response')
        suffix = '-json-retry' if attempt else ''
        raw = gateway_request(prompt, directory, phase + suffix, deadline, agent)
        (directory / (phase + suffix + '-raw.json')).write_text(raw + '\n')
        if profile:
            meta = lead_envelope(raw).get('result', {}).get('meta', {}).get('agentMeta', {})
            if (meta.get('provider'), meta.get('model')) != (profile['provider'], profile['model']):
                raise ValueError('Lead provider/model differs from the approved profile; no fallback accepted')
        try:
            return decode_lead(raw)
        except json.JSONDecodeError:
            if attempt:
                raise
            prompt += ('\nYour previous response was invalid JSON. Regenerate the requested JSON only. '
                       'Use short string values, escape embedded quotes, and close every string, array, '
                       'and object. Preserve the requested schema and all constraints. No markdown or tools.')


def lead_envelope(raw):
    # The gateway may prepend a CLI banner; the response itself is JSON.
    decoder = json.JSONDecoder()
    envelope = None
    for match in re.finditer(r'\{', raw):
        try:
            candidate, _ = decoder.raw_decode(raw[match.start():])
            if isinstance(candidate,dict) and ('payloads' in candidate or 'result' in candidate):
                envelope = candidate
                break
        except ValueError:
            continue
    if envelope is None:
        raise ValueError('Lead returned no structured envelope')
    return envelope


def decode_lead(raw):
    envelope = lead_envelope(raw)
    payloads = envelope.get('payloads') or envelope.get('result',{}).get('payloads',[])
    text = '\n'.join(p.get('text','') for p in payloads).strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    result=json.loads(text)
    # Providers can return the assignment array directly. Normalize only its envelope;
    # validate_plan still enforces every assignment field and all authority limits.
    return {'assignments':result} if isinstance(result,list) else result


def worker(task, packet, tree, run_dir, deadline, attempt=0):
    identity = run_dir.name + '-' + task['id'] + '-' + str(attempt)
    path = tree / task['path']
    path.chmod(0o666)  # Only this existing file is mounted writable for uid 1000.
    prompt = ('You are an engineer implementing the lead assignment. Read all declared sources using scoped_read before editing. '
              'Use only scoped_read and scoped_write. Preserve frontmatter schema if present. Never invent observed capabilities. '
              'Return a concise summary with source IDs.\n' + json.dumps({'task':task,'sources':packet['sources'],'acceptance':packet['acceptance']}))
    args = DOCKER + ['run','--rm','--name',identity,'--label','ad.managed=true','--label','ad.run='+run_dir.name,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--pids-limit=128','--cpus=2','--memory=2g','--tmpfs','/tmp:rw,nosuid,size=256m',
            '-e','PI_CODING_AGENT_DIR=/auth','-e','AD_OWNED='+json.dumps([task['path']]),'-e','AD_SOURCES='+json.dumps(SOURCES),
            '-v',str(tree)+':/workspace:ro','-v',str(path)+':/workspace/'+task['path']+':rw',
            '-v',str(STATE/'auth')+':/auth:rw','autonomous-pi:0.87.1',
            '--provider','openai-codex','--model','gpt-6-sol','--mode','json','--print','--no-session',
            '--no-extensions','--extension','/opt/scoped-tools.ts','--no-skills','--no-prompt-templates','--no-context-files',
            '--tools','scoped_read,scoped_write','--offline',prompt]
    log = run_dir / f'{task["id"]}-{attempt}.jsonl'
    started = time.time()
    try:
        with log.open('w') as output:
            proc = subprocess.run(args, stdout=output, stderr=subprocess.STDOUT, timeout=max(1,min(900,deadline-time.time())))
        if proc.returncode:
            raise RuntimeError(f'Pi worker {task["id"]} failed; see {log.name}')
    finally:
        subprocess.run(DOCKER+['rm','-f',identity],capture_output=True)
        path.chmod(0o644)
    events = []
    for line in log.read_text().splitlines():
        try: events.append(json.loads(line))
        except ValueError: pass
    messages = [e['message'] for e in events if e.get('type') == 'message_end' and 'message' in e]
    usage = [m['usage'] for m in messages if 'usage' in m]
    if not usage or any(m.get('stopReason') in ('error','aborted') for m in messages):
        raise RuntimeError('Worker lacks successful inference/usage receipt')
    calls = [c for m in messages for c in m.get('content',[]) if c.get('type') == 'toolCall']
    reads = {c.get('arguments',{}).get('path') for c in calls if c.get('name')=='scoped_read'}
    if not set(SOURCES).issubset(reads):
        raise RuntimeError('Worker did not read required sources')
    changed = git('diff','--name-only',cwd=tree).splitlines()
    if changed != [task['path']]:
        explanation=' '.join(p.get('text','') for m in messages if m.get('role')=='assistant' for p in m.get('content',[]) if p.get('type')=='text')[-1500:]
        raise RuntimeError('Worker produced missing or out-of-scope diff: '+explanation)
    return {'agent':'pi/0.87.1','provider':'openai-codex','model':'gpt-6-sol','assignment':task,
            'sourceSha':packet['sourceSha'],'elapsedSeconds':round(time.time()-started,2),'usage':usage,
            'toolCalls':len(calls),'readPaths':sorted(reads),'log':log.name,'attempt':attempt,
            'billing':'existing subscription; API price estimates are not additional-charge receipts'}


def execute(packet, pilot=False):
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'controller.lock').open('w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return {'status':'busy'}
        recover()
        allowed, seconds = window()
        if not pilot and not allowed: return {'status':'outside-window'}
        validate_packet(packet,current=issue(packet['issueId']))
        run_id = digest(json.dumps(packet,sort_keys=True).encode())[:16]
        directory = STATE/'runs'/run_id
        if directory.exists(): return json.loads((directory/'receipt.json').read_text())
        directory.mkdir(parents=True)
        receipt={'runId':run_id,'status':'running','startedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
                 'packet':packet,'workers':[],'checks':[],'pilot':pilot}
        save(directory/'receipt.json',receipt)
        deadline=time.time()+min(3600,3600 if pilot else seconds)
        try:
            source_text={s['id']:(ROOT/s['path']).read_text() for s in packet['sources']}
            prompt=('Act as the engineering tech lead for this approved copy-only story. Do not use tools. '
                    'Return ONLY JSON: {"assignments":[{"id":"proposition","path":"src/content/products/backintel.md",'
                    '"instructions":"YOUR ORIGINAL FOUR-SENTENCE ASSIGNMENT HERE","sourceIds":["product","claims","architecture","design"]},'
                    '{"id":"narrative","path":"src/content/night-shift.md","instructions":"YOUR ORIGINAL FOUR-SENTENCE ASSIGNMENT HERE",'
                    '"sourceIds":["product","claims","architecture","design"]}]}. '
                    'Replace both instruction placeholders with original actionable assignments of at least 120 characters each. '
                    'Name the exact sections to improve, substantive product facts to explain, facts not to claim, and how to check the result. '
                    'Choose complementary improvements grounded in the references.\n'+json.dumps({'packet':packet,'references':source_text}))
            plan=validate_plan(lead(prompt,directory,'lead-plan',deadline))
            save(directory/'lead-plan.json',plan)
            trees={}
            for task in plan['assignments']:
                tree=STATE/'worktrees'/run_id/task['id'];tree.parent.mkdir(parents=True,exist_ok=True)
                branch=f'autonomous/{run_id}/{task["id"]}'
                git('worktree','add','-b',branch,str(tree),packet['baseSha'])
                trees[task['id']]=tree
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures={pool.submit(worker,t,packet,trees[t['id']],directory,deadline):t for t in plan['assignments']}
                failures=[]
                for future in concurrent.futures.as_completed(futures):
                    try:receipt['workers'].append(future.result())
                    except Exception as error:
                        failures.append(str(error))
                        receipt.setdefault('workerFailures',[]).append({'assignment':futures[future],'reason':str(error)})
                    save(directory/'receipt.json',receipt)
                if failures:raise RuntimeError('Worker blocked: '+'; '.join(failures))
            branch=f'autonomous/{run_id}/integration'
            integrated=STATE/'worktrees'/run_id/'integration'
            git('worktree','add','-b',branch,str(integrated),packet['baseSha'])
            for task in plan['assignments']:
                tree=trees[task['id']]
                git('add','--',task['path'],cwd=tree)
                git('commit','-m',f'Improve {task["id"]} copy through delegated Pi worker',cwd=tree)
                sha=git('rev-parse','HEAD',cwd=tree)
                next(w for w in receipt['workers'] if w['assignment']['id']==task['id']).update(branch=git('branch','--show-current',cwd=tree),commit=sha)
                git('cherry-pick',sha,cwd=integrated)
            # Dependencies are trusted baseline dependencies, installed by the host.
            command(['npm','ci','--ignore-scripts','--no-audit','--no-fund'],cwd=integrated,timeout=max(1,min(240,int(deadline-time.time()))))
            for attempt in range(2):
                failures=[]
                for check in packet['checks']:
                    started=time.time()
                    result=subprocess.run(check,cwd=integrated,capture_output=True,text=True,timeout=max(1,min(240,deadline-time.time())))
                    name=check[-1]+f'-{attempt}.log';(directory/name).write_text(result.stdout+'\n'+result.stderr)
                    receipt['checks'].append({'argv':check,'exitCode':result.returncode,'elapsedSeconds':round(time.time()-started,2),'log':name})
                    if result.returncode: failures.append({'check':check,'error':(result.stdout+result.stderr)[-5000:]})
                if not failures: break
                if attempt: raise RuntimeError('Integration checks failed after one repair')
                repair=validate_plan(lead('Revise both original assignments to fix these integration failures, within the same file ownership. Return only the same assignments JSON schema, substantive instructions at least 120 characters each. '+json.dumps({'plan':plan,'failures':failures}),directory,'lead-repair',deadline))
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    futures={pool.submit(worker,t,packet,trees[t['id']],directory,deadline,1):t for t in repair['assignments']}
                    for future in concurrent.futures.as_completed(futures):receipt['workers'].append(future.result())
                for task in repair['assignments']:
                    tree=trees[task['id']]
                    git('add','--',task['path'],cwd=tree)
                    git('commit','-m',f'Repair {task["id"]} after integration checks',cwd=tree)
                    git('cherry-pick',git('rev-parse','HEAD',cwd=tree),cwd=integrated)
            diff=git('diff',packet['baseSha'],'HEAD','--',*OWNERS.values(),cwd=integrated)
            review=lead('Review this actual integrated copy against references. No tools. Return ONLY JSON {"decision":"accept" or "block","reason":"specific reason"}. '
                        +json.dumps({'references':source_text,'diff':diff,'checks':receipt['checks']}),directory,'lead-review',deadline)
            if set(review) != {'decision','reason'} or review['decision']!='accept':
                raise RuntimeError('Lead blocked review: '+str(review))
            receipt.update(status='awaiting-rendered-validation',branch=branch,headSha=git('rev-parse','HEAD',cwd=integrated),integrationPath=str(integrated),leadReview=review)
            save(directory/'receipt.json',receipt)
            finalize(receipt,directory,integrated,deadline)
        except Exception as error:
            receipt.update(status='blocked',reason=str(error))
        receipt['finishedAt']=dt.datetime.now(dt.timezone.utc).isoformat()
        save(directory/'receipt.json',receipt)
        save(STATE/'morning-handoff.json',receipt)
        return receipt


def render(tree, output, sha, deadline):
    node=shutil.which('node.exe') or '/mnt/c/Program Files/nodejs/node.exe'
    script=command(['wslpath','-w',str(ROOT/'controller/capture.mjs')])
    target=command(['wslpath','-w',str(output)])
    server=subprocess.Popen(['python3','-m','http.server','8088','--bind','127.0.0.1','--directory',str(tree/'dist')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        command([node,script,'http://127.0.0.1:8088/',target,sha],timeout=max(1,min(90,int(deadline-time.time()))))
    finally:
        server.terminate();server.wait(timeout=10)


def finalize(receipt, directory, tree, deadline):
    if time.time()>=deadline: raise RuntimeError('Run deadline reached before rendering')
    render(tree,directory,receipt['headSha'],deadline)
    receipt['rendered']=json.loads((directory/'rendered.json').read_text())
    evidence=tree/'docs/runs'/receipt['runId'];evidence.mkdir(parents=True,exist_ok=True)
    for source in directory.iterdir():
        if source.is_file() and source.suffix in ('.json','.jsonl','.png','.log'):
            shutil.copy2(source,evidence/source.name)
    save(evidence/'receipt.json',receipt)
    git('add','--',str(evidence.relative_to(tree)),cwd=tree)
    git('commit','-m','Record real lead and worker execution evidence',cwd=tree)
    receipt['headSha']=git('rev-parse','HEAD',cwd=tree)
    # Recheck the final commit. The committed screenshots refer to the preceding identical website tree.
    command(['python3','scripts/validate-poc.py'],cwd=tree,timeout=max(1,min(300,int(deadline-time.time()))))
    render(tree,directory/'final',receipt['headSha'],deadline)
    if time.time()>=deadline: raise RuntimeError('Run deadline reached before publication')
    git('push','-u','origin',receipt['branch'],cwd=tree)
    gh=shutil.which('gh.exe') or '/mnt/c/Program Files/GitHub CLI/gh.exe'
    existing=json.loads(command([gh,'pr','list','--repo','IntelIP/autonomous-development','--head',receipt['branch'],'--state','all','--json','url']))
    if existing: receipt['prUrl']=existing[0]['url']
    else:
        body=directory/'pr-body.md'
        body.write_text(f'''## Outcome

Improve the Autonomous Development landing-page proposition and operating narrative through an actual NemoClaw lead and two Pi engineers.

## Execution

- AgentShift: EEF-5, issue {receipt['packet']['issueId']}.
- Source/base SHA: `{receipt['packet']['sourceSha']}`.
- Final candidate: `{receipt['headSha']}`.
- Lead: OpenClaw in NemoClaw, existing Windows PAIR/Ollama model.
- Workers: Pi 0.87.1, openai-codex/gpt-6-sol, separate branches and enforced file ownership.
- Host controller performed integration and generated evidence. Worker edits are limited to the two copy files.

## Validation

Build, typecheck, controller contract checks, lead semantic review, and native Windows Chrome desktop/mobile checks passed. Final rendered receipt is retained on Windows under this run's `final` directory. Committed screenshots show the identical website tree immediately before the evidence-only commit.

Run records, tool traces, token usage and screenshots: [docs/runs/{receipt['runId']}](https://github.com/IntelIP/autonomous-development/tree/{receipt['headSha']}/docs/runs/{receipt['runId']}).

## Review boundary

Draft for human review. No merge or deployment performed. Subscription token usage is recorded; provider API cost estimates are not a billing receipt. Claims remain proof-of-concept claims.
''')
        body_windows=command(['wslpath','-w',str(body)])
        receipt['prUrl']=command([gh,'pr','create','--repo','IntelIP/autonomous-development','--base','main','--head',receipt['branch'],
                                 '--draft','--title','Improve Autonomous Development copy through delegated Pi engineers','--body-file',body_windows],timeout=60)
    receipt['status']='draft-pr-created'


def recover():
    # Called while holding the controller lock, or by the service before a new run.
    for old in (STATE/'runs').glob('*/receipt.json'):
        record=json.loads(old.read_text())
        if record['status'] in ('running','awaiting-rendered-validation'):
            names=command(DOCKER+['ps','-aq','--filter','label=ad.managed=true','--filter','label=ad.run='+record['runId']]).splitlines()
            for name in names:command(DOCKER+['rm','-f',name])
            policy = record.get('packet', {}).get('recoveryPolicy', {})
            can_resume = (record.get('packet', {}).get('schemaVersion') == 2
                and policy == {'infrastructureRetries': 1, 'replayWorkers': False}
                and record.get('checkpoint', {}).get('phase') in {'validate', 'review', 'publish'}
                and record.get('infrastructureRetries', 0) < 1)
            record.update(status='interrupted' if can_resume else 'blocked',
                reason='Controller interrupted; resume saved candidate' if can_resume else
                'Controller interrupted without a recoverable checkpoint; explicit approval required')
            save(old,record)


def scheduled():
    # A native process deadline also covers blocking child processes and a stuck model.
    allowed,seconds=window()
    if not allowed:return
    result=subprocess.run(['timeout','--signal=TERM','--kill-after=10s',str(min(3600,seconds))+'s',
                           'python3',str(ROOT/'controller/control.py'),'tick'])
    if result.returncode not in (0,124):raise RuntimeError('Scheduled controller failed')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['packet','approve','run','tick','status','scheduled','recover'])
    parser.add_argument('--issue');parser.add_argument('--packet',type=Path);parser.add_argument('--pilot',action='store_true')
    args=parser.parse_args()
    if args.action=='packet':
        packet=compile_packet(issue(args.issue));save(args.packet,packet);print(args.packet)
    elif args.action=='approve':
        packet=json.loads(args.packet.read_text())
        if packet['approval'] is not None: raise ValueError('Already approved')
        packet['approval']={'owner':'Hudson Aikins','approvedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'packetDigest':digest(json.dumps(packet,sort_keys=True).encode())}
        save(args.packet,packet);print('Approved exact packet')
    elif args.action=='run':
        result=execute(json.loads(args.packet.read_text()),args.pilot)
        print(json.dumps({k:v for k,v in result.items() if k in ('runId','status','reason','branch','headSha')}))
    elif args.action=='scheduled':scheduled()
    elif args.action=='recover':
        STATE.mkdir(parents=True,exist_ok=True)
        with (STATE/'controller.lock').open('w') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return
            recover()
    elif args.action=='tick':
        if not window()[0]: return
        for path in sorted((STATE/'queue').glob('*.json')):
            packet=json.loads(path.read_text())
            run_id=digest(json.dumps(packet,sort_keys=True).encode())[:16]
            previous = STATE/'runs'/run_id/'receipt.json'
            if previous.exists() and json.loads(previous.read_text()).get('status') not in {'running','interrupted','retryable'}:
                continue
            try:
                if packet.get('schemaVersion') == 2:
                    from engineering import execute as execute_engineering
                    result=execute_engineering(packet)
                else:
                    result=execute(packet)
            except Exception as error:
                result = json.loads(previous.read_text()) if previous.exists() else {'runId':run_id,'issueId':packet.get('issueId')}
                result.update(status='blocked', reason=str(error), stage='admission')
                save(STATE/'runs'/run_id/'receipt.json',result)
                save(STATE/'morning-handoff.json',result)
            if result.get('status') not in ('outside-window','busy'): print(json.dumps({'runId':result.get('runId'),'status':result['status']}))
            break
    else:
        print((STATE/'morning-handoff.json').read_text() if (STATE/'morning-handoff.json').exists() else '{"status":"no-runs"}')


if __name__=='__main__': main()
