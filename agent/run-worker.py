#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Hudson Aikins / IntelIP
# SPDX-License-Identifier: Apache-2.0
"""Run one bounded Pi assignment in an existing isolated checkout."""
import argparse
import importlib.util
import ipaddress
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import threading
import uuid
import time
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bin"))
from runtime_env import credential_env
from worker_protocol import AGENTS, authenticated, invocation, result as worker_result


def proxy_address(engine_os, gateway, interfaces):
    if engine_os == "Docker Desktop":
        address = next((a["local"] for interface in interfaces for a in interface["addr_info"] if a["family"] == "inet"), None)
        if not address:
            raise ValueError("Docker Desktop requires a reachable WSL private interface")
    else:
        address = gateway
    ip = ipaddress.ip_address(address)
    if not ip.is_private or ip.is_unspecified or ip.is_loopback:
        raise ValueError("Worker proxy requires an explicit private interface address")
    return address


def writable_mounts(workspace, files, directories):
    workspace = workspace.resolve()
    mounts = []
    entries = [(p, False) for p in files] + [(p, True) for p in directories]
    for name, is_directory in entries:
        relative = Path(name)
        if relative.is_absolute() or not relative.parts or any(p in (".", "..", ".git") for p in relative.parts) or name == ".":
            raise ValueError("Writable paths must stay inside the repository and exclude .git")
        path = workspace / relative
        if path.is_symlink() or not path.resolve().is_relative_to(workspace):
            raise ValueError("Writable symlinks or paths outside the checkout are forbidden")
        if path.exists() and path.is_dir() != is_directory:
            raise ValueError("Writable path kind does not match the checkout")
    for name, is_directory in entries:
        path = workspace / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.mkdir() if is_directory else path.touch()
            if os.geteuid() == 0:
                os.chown(path, 1000, 1000)
        mounts += ["--mount", f"type=bind,src={path},dst=/workspace/{name}"]
    return mounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--auth-dir", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--check", choices=["stack", "tools"])
    parser.add_argument("--image", default="agent-stack:0.1.0")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--agent", choices=AGENTS, default="pi")
    parser.add_argument("--model")
    parser.add_argument("--profile", choices=["full", "minimal"], default="full")
    parser.add_argument("--run-id", help="Controller run identifier, used by interrupted-run recovery")
    parser.add_argument("--assignment", help="Controller assignment identifier, used for scoped cleanup")
    parser.add_argument("--write-file", action="append", default=[])
    parser.add_argument("--write-dir", action="append", default=[])
    args = parser.parse_args()
    if not 1 <= args.timeout <= 3600:
        parser.error("Timeout must be between 1 and 3600 seconds")
    if bool(args.prompt_file) == bool(args.check):
        parser.error("Supply one of --prompt-file or --check")
    if args.run_id and not re.fullmatch(r"[a-f0-9]{16}", args.run_id):
        parser.error("Run ID must be a 16-character hexadecimal identifier")
    if args.assignment and (not args.run_id or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", args.assignment)):
        parser.error("Assignment requires a valid run ID and a lowercase identifier")
    if args.prompt_file and not (args.write_file or args.write_dir):
        parser.error('Assignments require an explicit writable file or directory scope')
    workspace = args.workspace.resolve()
    auth = args.auth_dir.resolve()
    if not workspace.is_dir() or not authenticated(auth, args.agent):
        parser.error("Workspace and existing auth cache are required")
    docker = ["docker"]
    if os.environ.get('AD_DOCKER_HOST', 'unix:///run/docker.sock'):
        docker += ['-H', os.environ.get('AD_DOCKER_HOST', 'unix:///run/docker.sock')]
    server = None
    bridge = None
    if args.agent == 'pi' and args.profile == 'full':
        engine = json.loads(subprocess.check_output(docker + ["info", "--format", "{{json .}}"], text=True))
        gateway = json.loads(subprocess.check_output(docker + ["network", "inspect", "bridge"], text=True))[0]["IPAM"]["Config"][0]["Gateway"]
        interfaces = json.loads(subprocess.check_output(["ip", "-j", "address", "show", "eth0"], text=True)) if engine["OperatingSystem"] == "Docker Desktop" else []
        bridge = proxy_address(engine["OperatingSystem"], gateway, interfaces)
        spec = importlib.util.spec_from_file_location("readonly_http", ROOT / "bin/agentshift-readonly-http.py")
        proxy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(proxy)
        server = ThreadingHTTPServer((bridge, 0), proxy.handler("http://127.0.0.1:3000"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
    name = "agent-stack-" + uuid.uuid4().hex[:12]
    env = credential_env(auth / "auth.json") if args.agent == "pi" and args.profile == "full" else os.environ.copy()
    command = docker + ["run", "--rm", "--name", name, "--label", "agent-stack.managed=true", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=256", "--cpus=2", "--memory=3g", "--network=bridge", "--tmpfs=/tmp:rw,nosuid,size=512m", "--shm-size=256m", "--mount", f"type=bind,src={workspace},dst=/workspace" + (",readonly" if args.write_file or args.write_dir else ""), "--mount", f"type=bind,src={auth},dst=/run/credentials"]
    # Keep data scratch non-executable; build tools need an explicit executable temp directory.
    command += ['--user=1000:1000', '--tmpfs=/build:rw,exec,nosuid,nodev,mode=1777,size=512m',
                '--env=TMPDIR=/build', '--env=GOTMPDIR=/build']
    command += writable_mounts(workspace, args.write_file, args.write_dir)
    if args.run_id:
        command += ["--label", "ad.managed=true", "--label", "ad.run=" + args.run_id]
    if args.assignment:
        command += ["--label", "ad.assignment=" + args.assignment]
    command += ['--interactive', '--env', 'HOME=/build/home']
    for key in ('OPENROUTER_API_KEY', 'EXA_API_KEY'):
        if args.agent == 'pi' and args.profile == 'full' and env.get(key):
            command += ['--env', key]
    if server:
        command += ['--env', f'AGENTSHIFT_BACKEND_URL=http://{bridge}:{server.server_port}']
    native_env = {'pi': 'PI_CODING_AGENT_DIR=/run/credentials', 'codex': 'CODEX_HOME=/run/credentials',
                  'claude-code': 'CLAUDE_CONFIG_DIR=/run/credentials', 'opencode': 'XDG_DATA_HOME=/run/credentials'}
    if args.agent != 'pi' or args.profile == 'minimal':
        command += ['--env', native_env[args.agent]]
    if args.agent == 'opencode':
        # Native noninteractive runs must be able to use the container's existing scratch mounts.
        # Repository writes remain constrained by the Docker bind mounts above.
        command += ['--env', 'OPENCODE_PERMISSION=' + json.dumps({
            'external_directory': {'/tmp/*': 'allow', '/build/*': 'allow'},
        })]
    if not args.check:
        native = invocation(args.agent, args.model, args.profile, external_sandbox=True)
        command += ['--entrypoint', native[0]]
    elif args.agent != 'pi':
        parser.error('Stack checks apply only to Pi')
    command.append(args.image)
    if args.check:
        command += ["--stack-check" if args.check == "stack" else "--tool-check"]
    else:
        command += native[1:]
    args.log.parent.mkdir(parents=True, exist_ok=True)
    code = 1
    started = time.monotonic()
    try:
        with args.log.open("w") as log:
            prompt = args.prompt_file.read_text() if args.prompt_file else ''
            code = subprocess.run(command, input=prompt, text=True, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout).returncode
    except subprocess.TimeoutExpired:
        code = 124
    finally:
        subprocess.run(docker + ["rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if server:
            server.shutdown()
            server.server_close()
    if args.check:
        receipt = {'schemaVersion': 1, 'agent': args.agent, 'status': 'completed' if code == 0 else 'failed', 'exitCode': code}
    else:
        receipt = worker_result(args.agent, args.log, code)
    receipt.update(container=name, image=args.image, elapsedSeconds=round(time.monotonic() - started, 2))
    target = args.log.with_suffix('.result.json')
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(target)
    print(json.dumps(receipt))
    if receipt['status'] != 'completed' and code == 0: code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
