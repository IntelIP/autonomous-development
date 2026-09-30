# Executable AgentShift tickets

Put exactly one fenced `autonomous-ticket` JSON block in an AgentShift description. Narrative history remains outside acceptance. The quickstart generates a synthetic ticket with committed checks.

Required fields:

| Field | Required content |
| --- | --- |
| `schemaVersion` | `1` |
| `outcome` | User, desired behavior, and value |
| `acceptance` | Unique `id`, concrete `scenario`, observable `expected`, zero-based `check` index into execution checks |
| `exclusions` | Explicit forbidden product and operational behavior |
| `dependencies` | Same-project AgentShift issue IDs; empty means independent. Every dependency must be complete live. |
| `interfaces` | Both engineer IDs and exact shared signatures, JSON shapes, units and error semantics; an explicit independence contract if there is no shared API |
| `execution` | Existing engineering contract: repository, base branch, source paths, two nonoverlapping writable scopes, toolchain, setup, checks and evidence artifacts |
| `limits` | Exact controller limits: two workers, one repair each, 3600 seconds |
| `completion` | `success: draft-pr`, `failure: blocked-report`, `merge: human` |

The controller injects identical interfaces into both worker prompts. Lead instructions cannot grant paths, commands, retries or publication authority. Each acceptance example names an executable check; operator review must confirm the check actually exercises the stated behavior.

## Admit and run

```sh
python3 controller/engineering.py packet --issue ISSUE_UUID --project PROJECT_UUID --packet /var/lib/autonomous-development/queue/ISSUE_UUID.json
python3 controller/engineering.py approve --packet /var/lib/autonomous-development/queue/ISSUE_UUID.json
python3 controller/engineering.py run --pilot --packet /var/lib/autonomous-development/queue/ISSUE_UUID.json
```

Ticket compilation reads execution configuration directly from AgentShift. An optional `--contract` must exactly match the ticket. Missing information blocks admission with a concrete error; the lead never fills authority gaps. Approval pins the ticket revision, dependency completion revisions, source/driver/controller hashes, image and base SHA. A changed or reopened dependency invalidates admission. Existing schema-2 packets without this ticket contract must be regenerated and approved.

## Review

Review consumes immutable acceptance, current source, repository declarations and the current successful check receipt. Historical failure prose and old deleted lines are excluded. The result must name the exact head SHA. A rejection requires a current file, one-based line, exact source quote, incorrect behavior and severity. Unanchored or malformed reviews block; they never become approval automatically.

The user owns merge and deployment decisions. A successful ticket ends at a draft PR with evidence for human review.
