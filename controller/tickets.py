"""Executable AgentShift tickets; narrative history never becomes acceptance."""
import json
import re


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def extract(description, validate_contract, limits):
    blocks = re.findall(r'^```autonomous-ticket\s*\n(.*?)^```\s*$', description, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError('Exactly one autonomous-ticket JSON block is required')
    ticket = json.loads(blocks[0])
    required = {'schemaVersion', 'outcome', 'acceptance', 'exclusions', 'dependencies', 'interfaces', 'execution', 'limits', 'completion'}
    if not isinstance(ticket, dict) or set(ticket) != required or ticket['schemaVersion'] != 1:
        raise ValueError('Unsupported executable ticket schema')
    if not nonempty(ticket['outcome']):
        raise ValueError('A user outcome is required')
    contract = validate_contract(ticket['execution'])
    if ticket['limits'] != limits or ticket['completion'] != {'success': 'draft-pr', 'failure': 'blocked-report', 'merge': 'human'}:
        raise ValueError('Ticket cannot expand limits or publication authority')
    for field in ('acceptance', 'exclusions', 'interfaces'):
        if not isinstance(ticket[field], list) or not ticket[field]:
            raise ValueError(field + ' must be explicit and nonempty')
    if not all(nonempty(x) for x in ticket['exclusions']):
        raise ValueError('Exclusions must be text')
    seen = set()
    for case in ticket['acceptance']:
        if not isinstance(case, dict) or set(case) != {'id', 'scenario', 'expected', 'check'}:
            raise ValueError('Acceptance needs id, scenario, expected, and check index')
        if not all(nonempty(case[k]) for k in ('id', 'scenario', 'expected')) or case['id'] in seen:
            raise ValueError('Acceptance examples must be substantive and unique')
        if type(case['check']) is not int or not 0 <= case['check'] < len(contract['checks']):
            raise ValueError('Acceptance must map to an executable check')
        seen.add(case['id'])
    if not isinstance(ticket['dependencies'], list) or len(set(ticket['dependencies'])) != len(ticket['dependencies']):
        raise ValueError('Dependencies must be an explicit unique issue-ID list')
    for dependency in ticket['dependencies']:
        if not isinstance(dependency, str) or not re.fullmatch(r'[a-f0-9-]{36}', dependency):
            raise ValueError('Invalid dependency issue ID')
    owners = set(contract['scopes'])
    for interface in ticket['interfaces']:
        if not isinstance(interface, dict) or set(interface) != {'owners', 'contract'}:
            raise ValueError('Interface requires owners and exact contract')
        if not isinstance(interface['owners'], list) or set(interface['owners']) != owners or len(interface['owners']) != len(owners):
            raise ValueError('Shared interface must name every assigned engineer')
        if not nonempty(interface['contract']) or len(interface['contract']) < 40:
            raise ValueError('Exact signatures or explicit independence contract required')
    return ticket


def acceptance(ticket):
    return json.dumps({key: ticket[key] for key in ('outcome', 'acceptance', 'exclusions', 'interfaces', 'completion')}, sort_keys=True)
