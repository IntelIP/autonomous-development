# SPDX-FileCopyrightText: 2026 Hudson Aikins / IntelIP
# SPDX-License-Identifier: Apache-2.0
"""Reuse existing provider credentials in process memory only."""
import json
import os
from pathlib import Path
import subprocess


def credential_env(auth_file=None):
    env = os.environ.copy()
    powershell = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if powershell.exists():
        for name in ("OPENROUTER_API_KEY", "EXA_API_KEY"):
            if not env.get(name):
                command = f"[Environment]::GetEnvironmentVariable('{name}','User')"
                result = subprocess.run([str(powershell), "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=15)
                if result.returncode == 0 and result.stdout.strip():
                    env[name] = result.stdout.strip()
    if not env.get("OPENROUTER_API_KEY") and auth_file and Path(auth_file).exists():
        auth = json.loads(Path(auth_file).read_text()).get("openrouter", {})
        if auth.get("type") == "api_key" and auth.get("key"):
            env["OPENROUTER_API_KEY"] = auth["key"]
    return env
