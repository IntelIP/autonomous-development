#!/usr/bin/env python3
"""OpenAI-compatible model transport to an existing Pi Codex subscription.

This bridge supplies inference only. OpenClaw remains the lead harness. No tools,
repository mounts, host socket mounts or provider fallback reach the model.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import subprocess
import sys
import threading
import uuid

MODEL = 'gpt-6-sol'
DOCKER = ['docker', '-H', 'unix:///run/docker.sock']


def completion(output):
    messages = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'message_end' and event.get('message', {}).get('role') == 'assistant':
            messages.append(event['message'])
    if not messages or messages[-1].get('stopReason') in ('error', 'aborted', 'toolUse'):
        raise ValueError('Pi did not produce a completed assistant response')
    text = '\n'.join(x['text'] for x in messages[-1].get('content', []) if x.get('type') == 'text')
    if not text.strip():
        raise ValueError('Pi response is empty')
    usage = messages[-1].get('usage', {})
    return text, {'prompt_tokens': usage.get('input', 0) + usage.get('cacheRead', 0),
                  'completion_tokens': usage.get('output', 0), 'total_tokens': usage.get('totalTokens', 0)}


def infer(messages, auth, image):
    if not isinstance(messages, list) or not messages:
        raise ValueError('Messages are required')
    for message in messages:
        if isinstance(message.get('content'), list):
            parts = message['content']
            if not all(isinstance(x, dict) and x.get('type') == 'text' and isinstance(x.get('text'), str) for x in parts):
                raise ValueError('Only text content parts are supported')
            message = dict(message, content='\n'.join(x['text'] for x in parts))
        if message.get('role') not in ('system', 'developer', 'user', 'assistant') or not isinstance(message.get('content'), str):
            raise ValueError('Only text messages are supported')
    prompt = 'Produce the next assistant response for this conversation. Do not call tools.\n' + json.dumps(messages)
    if len(prompt.encode()) > 500000:
        raise ValueError('Inference context exceeds bridge limit')
    name = 'ad-lead-inference-' + uuid.uuid4().hex[:12]
    argv = DOCKER + ['run', '--rm', '-i', '--name', name, '--label', 'ad.inference=true', '--read-only',
                    '--cap-drop=ALL', '--security-opt=no-new-privileges', '--cpus=1', '--memory=1g', '--pids-limit=64',
                    '--tmpfs=/tmp:rw,nosuid,size=64m', '-e', 'PI_CODING_AGENT_DIR=/run/credentials',
                    '--mount', f'type=bind,src={auth},dst=/run/credentials', '--entrypoint', 'pi', image,
                    '--provider', 'openai-codex', '--model', MODEL, '--mode', 'json', '--print', '--no-session',
                    '--no-tools', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-context-files', '--offline']
    try:
        result = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=170)
        if result.returncode:
            raise RuntimeError('Pi inference process failed')
        return completion(result.stdout)
    finally:
        subprocess.run(DOCKER + ['rm', '-f', name], capture_output=True, timeout=15)


def handler(token, auth, image):
    capacity = threading.BoundedSemaphore(1)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Never log conversation content or authorization headers.

        def send_json(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

        def authorized(self):
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def do_GET(self):
            if not self.authorized():
                return self.send_json(401, {'error': 'Unauthorized'})
            if self.path != '/v1/models':
                return self.send_json(404, {'error': 'Not found'})
            self.send_json(200, {'object': 'list', 'data': [{'id': MODEL, 'object': 'model', 'owned_by': 'existing-codex-subscription'}]})

        def do_POST(self):
            if not self.authorized():
                return self.send_json(401, {'error': 'Unauthorized'})
            if self.path != '/v1/chat/completions':
                return self.send_json(404, {'error': 'Not found'})
            request = {}
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 600000:
                    raise ValueError('Invalid request size')
                request = json.loads(self.rfile.read(size))
                # OpenClaw exposes harness metadata even on text-only turns.
                # Never forward these descriptors to Pi or emit tool calls.
                offered = request.get('tools', [])
                harness_names = {'session_status', 'tool_call', 'tool_describe', 'tool_search'}
                if request.get('model') != MODEL or any(t.get('function', {}).get('name') not in harness_names for t in offered) or request.get('tool_choice') == 'required':
                    raise ValueError('Only the configured text-only model is supported')
            except (ValueError, TypeError):
                print(json.dumps({'event': 'request-schema-rejected', 'model': request.get('model'),
                                  'tools': [t.get('function', {}).get('name') for t in request.get('tools', [])],
                                  'toolChoice': request.get('tool_choice')}), file=sys.stderr, flush=True)
                return self.send_json(400, {'error': 'Invalid inference request'})
            if not capacity.acquire(blocking=False):
                return self.send_json(429, {'error': 'Lead inference is busy'})
            try:
                text, usage = infer(request.get('messages'), auth, image)
                identity = 'chatcmpl-' + uuid.uuid4().hex
                if request.get('stream'):
                    self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                    chunks = [{'id': identity, 'object': 'chat.completion.chunk', 'model': MODEL,
                               'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': text}, 'finish_reason': None}]},
                              {'id': identity, 'object': 'chat.completion.chunk', 'model': MODEL, 'usage': usage,
                               'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}]
                    for chunk in chunks:
                        self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                    self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
                else:
                    self.send_json(200, {'id': identity, 'object': 'chat.completion', 'model': MODEL, 'usage': usage,
                                        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}]})
            except (ValueError, RuntimeError, subprocess.TimeoutExpired):
                self.send_json(502, {'error': 'Subscription inference failed; no fallback used'})
            finally:
                capacity.release()
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1'); parser.add_argument('--port', type=int, default=19110)
    parser.add_argument('--token-file', type=Path, required=True); parser.add_argument('--auth-dir', type=Path, required=True)
    parser.add_argument('--image', default='agent-stack:profitctl-0.1.0')
    args = parser.parse_args()
    address = ipaddress.ip_address(args.bind)
    if not address.is_private or address.is_unspecified:
        parser.error('Bind to loopback or one explicit private interface')
    if args.token_file.stat().st_mode & 0o077 or not (args.auth_dir / 'auth.json').is_file():
        parser.error('Private token file and existing Pi auth cache required')
    token = args.token_file.read_text().strip()
    if len(token) < 32:
        parser.error('Bridge token must have at least 32 characters')
    ThreadingHTTPServer((args.bind, args.port), handler(token, args.auth_dir.resolve(), args.image)).serve_forever()


if __name__ == '__main__':
    main()
