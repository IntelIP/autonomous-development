# SPDX-FileCopyrightText: 2026 Hudson Aikins / IntelIP
# SPDX-License-Identifier: Apache-2.0
"""Native CLI adapters. A successful process alone does not prove agent completion."""
import json
from pathlib import Path

AGENTS = ('pi', 'codex', 'claude-code', 'opencode')
AUTH_FILES = {'pi': 'auth.json', 'codex': 'auth.json',
              'claude-code': '.credentials.json', 'opencode': 'opencode/auth.json'}


def authenticated(directory, agent):
    root = Path(directory)
    return (root / AUTH_FILES[agent]).is_file() or (agent == 'claude-code' and (root / 'settings.json').is_file())


def invocation(agent, model=None, profile='full', *, external_sandbox=False):
    """Return an entrypoint and fixed arguments; task text travels separately."""
    if agent not in AGENTS or profile not in ('full', 'minimal'):
        raise ValueError('Unsupported worker runtime or profile')
    if model is not None and (not isinstance(model, str) or not model.strip() or model.startswith('-')):
        raise ValueError('A model must be a nonempty model identifier')
    claude_tools = 'Read,Bash,Glob,Grep' if external_sandbox else 'Read,Write,Edit,Bash,Glob,Grep'
    commands = {
        'pi': ['/opt/agent-stack/bin/pi-stack' if profile == 'full' else 'pi',
               '--mode', 'json', '--print', '--no-session'],
        'codex': ['codex', '--ask-for-approval', 'never', 'exec', '--json', '--ephemeral', '--sandbox', 'danger-full-access' if external_sandbox else 'workspace-write', '-'],
        'claude-code': ['claude', '--print', '--output-format', 'stream-json', '--verbose',
                       '--permission-mode', 'acceptEdits', '--tools', claude_tools, '--allowedTools', claude_tools],
        'opencode': ['opencode', 'run', '--format', 'json'],
    }
    # The Docker runner already enforces writable mounts, UID, capabilities, and limits.
    # Nested Codex namespaces are unavailable there; host invocations keep the native sandbox.
    command = commands[agent]
    if agent == 'claude-code' and external_sandbox:
        command += ['--append-system-prompt', (
            'The repository is read-only except for the approved writable paths. '
            'Edit and Write are unavailable because their temporary sibling files and atomic '
            'renames do not work with individual writable file mounts. Use Bash with Python '
            'Path.write_text or direct open/write calls to update approved files in place. '
            'Do not use rename, replace, sed -i, or temporary sibling files. Use /tmp or /build '
            'for scratch work. Never modify paths outside the approved task scope.'
        )]
    if model:
        # Keep the Codex stdin marker and Pi file argument last.
        index = -1 if agent == 'codex' else len(command)
        command[index:index] = ['--model', model]
    return command


def result(agent, log, exit_code):
    """Normalize native terminal events without inventing usage or success."""
    if agent not in AGENTS:
        raise ValueError('Unsupported worker runtime')
    complete = False
    failed = False
    session = None
    usage = []
    for line in Path(log).read_text(errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get('type')
        if agent == 'pi':
            if kind == 'session': session = event.get('id')
            if kind == 'agent_end': complete = True
            if kind == 'message_end':
                message = event.get('message', {})
                if message.get('usage'): usage.append(message['usage'])
                failed |= message.get('stopReason') in ('error', 'aborted')
        elif agent == 'codex':
            if kind == 'thread.started': session = event.get('thread_id')
            if kind == 'turn.completed':
                complete = True
                if event.get('usage'): usage.append(event['usage'])
            failed |= kind in ('turn.failed', 'error')
        elif agent == 'claude-code':
            session = event.get('session_id', session)
            if kind == 'result':
                complete = event.get('subtype') == 'success' and event.get('is_error') is False
                failed |= not complete
                if event.get('usage'): usage.append(event['usage'])
        else:
            session = event.get('sessionID', session)
            part = event.get('part', {})
            if kind == 'step_finish':
                complete |= part.get('reason') == 'stop'
                if part.get('tokens'): usage.append(part['tokens'])
            failed |= kind == 'error'
    status = 'completed' if complete and not failed and exit_code == 0 else 'failed'
    if exit_code in (124, 130, 137, 143): status = 'interrupted'
    return {'schemaVersion': 1, 'agent': agent, 'status': status,
            'exitCode': exit_code, 'sessionId': session, 'usage': usage,
            'terminalEventObserved': complete, 'log': str(log)}
