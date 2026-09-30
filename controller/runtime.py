"""Operator configuration. Values are bound into each approved packet."""
import os
import shutil
from pathlib import Path


def settings():
    return {
        'trackerUrl': os.environ.get('AD_TRACKER_URL', 'http://127.0.0.1:3000').rstrip('/'),
        'ticketsFile': os.environ.get('AD_TICKETS_FILE', ''),
        'dockerHost': os.environ.get('AD_DOCKER_HOST', 'unix:///run/docker.sock'),
        'githubCli': os.environ.get('AD_GITHUB_CLI', shutil.which('gh') or '/mnt/c/Program Files/GitHub CLI/gh.exe'),
        'graphify': os.environ.get('AGENT_STACK_GRAPHIFY', shutil.which('graphify') or ''),
        'nemoclaw': os.environ.get('AD_NEMOCLAW', shutil.which('nemoclaw') or '/root/.local/bin/nemoclaw'),
        'openshell': os.environ.get('AD_OPENSHELL', shutil.which('openshell') or '/usr/local/bin/openshell'),
        'sandbox': os.environ.get('AD_SANDBOX', 'local-claw'),
        'gateway': os.environ.get('AD_GATEWAY', 'nemoclaw'),
    }


def auth_directory(state, agent):
    return Path(state) / ('auth' if agent == 'pi' else 'auth-' + agent)
