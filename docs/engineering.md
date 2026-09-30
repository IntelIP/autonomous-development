# Full-stack engineering packets

## Latest supervised result — 28 September 2026

The live Pi runs reached passing product checks, but the lead did not approve the candidate. The latest candidate was preserved; no product PR was created. The final rejection quoted a real source line with an incorrect line number, so strict validation blocked publication.

The alpha now numbers review source lines, routes an actionable rejected review through the existing repair budget, and uses a fresh review identity for each round. These controller changes have regression tests; a successful live lead-repair-to-PR run remains unproven. See [alpha support and setup](alpha-quickstart.md) for agent-specific evidence.

Schema 1 retains the original two-file website pilot. Schema 2 connects approved
product stories to the shared [agent-stack](https://github.com/IntelIP/autonomous-development/tree/main/agent)
runtime. The existing timer dispatches both formats through one lock, run ledger,
Eastern admission window, and interrupted-run recovery.

## Contract and approval

Every engineering story now needs an [executable AgentShift ticket](executable-tickets.md).
The fenced ticket supplies user outcomes, examples mapped to checks, exclusions,
live dependencies, exact shared interfaces and the execution contract below.
Historical notes remain outside acceptance. Both engineers receive the same
interface contract directly from the controller.

An operator writes a JSON contract containing:

- `repositoryPath`: absolute Windows WSL path to the committed product checkout.
- `githubRepository`: the corresponding owner/repository for draft publication.
- `baseBranch`: the existing branch containing the approved source commit and targeted by the PR.
- `projectId`: the AgentShift project containing the approved issue.
- `sources`: tracked product/context files, relative to that checkout.
- `scopes`: one or two named engineers; each has `files` and `directories` arrays.
  Ownership cannot overlap or include `.git`, parent paths, or the repository root.
- `setup` and `checks`: operator-defined argument arrays executed in order in a
  validation container. At least one product acceptance check is required.
- `requiredArtifacts`: files the checks must produce, such as rendered screenshots.
- `stackRoot`: absolute path to the deployed agent-stack source.
- `workerImage`: installed image reference, resolved to an immutable image ID.

```sh
python3 controller/engineering.py packet --contract /path/to/contract.json \
  --issue ISSUE_UUID --packet /var/lib/autonomous-development/queue/ISSUE_UUID.json
# Only after the owner authorizes this exact ticket and implementation scope:
python3 controller/engineering.py approve \
  --packet /var/lib/autonomous-development/queue/ISSUE_UUID.json
# A supervised run uses the same packet and execution path:
python3 controller/engineering.py run --pilot \
  --packet /var/lib/autonomous-development/queue/ISSUE_UUID.json
```

Approval binds the story revision, repository commit, source hashes, driver
sources, controller sources, image ID, ownership, checks, and limits. Changes invalidate admission.
An installed timer or an arbitrary backlog item does not authorize a new task.

## Execution

NemoClaw receives the approved context and returns substantive instructions for
each named scope. It cannot change ownership, commands, model accounts, or limits.
Up to two selected engineers run in separate full Git clones. The repository is mounted
read-only, with only approved files/directories writable. The shared runtime
provides Jev, Warden, skills, documentation, search, Graphify, browser, and read-only
AgentShift access. Provider authentication stays outside repositories and images.

The controller retains commits, branch publication, and draft PR creation. Workers
receive no GitHub/SSH credentials or host control socket. Integration checks run
in a separate container without provider credentials. Failed assignments and
integration failures return to the lead for at most one repair per engineer.
Successful siblings are retained. Missing evidence, exhausted repairs, or deadlines
produce a blocked report. No fallback model or automatic merge/deployment exists.

Each run retains worker logs, branch commits, token-usage receipts, check logs,
required-artifact hashes, lead review, and the final PR or blocker. After validation
and lead review pass, worker branches and the integration branch are published.
The PR remains a draft for human review.

The controller keeps the 22:00–06:00 America/New_York window, two-worker maximum,
one repair per engineer, and 60-minute combined deadline. Worker and validation
containers carry run-specific recovery labels. A killed process is never treated
as a successful run or automatically replayed.

## Supervised recovery after an integration setup failure

If both initial engineers completed but an infrastructure failure prevented
acceptance checks or dispatch of a repair, retain their commits. After fixing the
controller, compile and approve a new packet with the same product authority,
then pass `--resume ORIGINAL_RUN_ID` to the supervised `run` command. The original
receipt must be blocked, contain both completed initial assignments, and contain
no acceptance rounds or repair records. The original 60-minute deadline remains
in force. Product source, issue revision, ownership, image, and checks cannot
change through this recovery path.

Controller-created clones use UID 1000 for worker writes. Their exact `.git`
paths are explicitly trusted for root-controlled local Git transfers; no wildcard
trust is granted. Repair assignments receive completed peer source as reference
data, so a worker can assemble a combined scratch checkout without waiting for
files to appear in its isolated clone. Lead requests are uploaded as JSON files
and submitted by OpenClaw's installed Gateway client. Prompt text never appears
in command arguments. The client checks the Gateway payload limit and the
controller bounds lead context to 512 KiB. Requests, acceptance run IDs and final
responses are retained. A reconnect with an accepted run ID only waits for that
run; it never submits another turn when the final response is unavailable.

## Standard supervised repairs

Normal scheduled runs and supervised runs explicitly set the service user,
login environment, working directory and executable path. Both use the same
controller lock, admission rules, worker isolation, checks and publication path.
The supervised template permits an owner-approved daytime pilot; the scheduled
service retains the Eastern overnight admission window.

After the owner approves one supplemental repair, compile a fresh packet from
the current executable ticket and bind the preserved blocked candidate and one
engineer scope when approving it:

```sh
python3 controller/engineering.py packet --project PROJECT_UUID --issue ISSUE_UUID \
  --packet /var/lib/autonomous-development/queue/pilot.json
python3 controller/engineering.py approve \
  --packet /var/lib/autonomous-development/queue/pilot.json \
  --repair-from BLOCKED_RUN_ID --scope ENGINEER_SCOPE
systemctl start autonomous-development-pilot@pilot.service
```

The repair gets one Pi invocation of at most 900 seconds and a fresh combined
60-minute deadline. It must retain the original repository, base and ownership.
The source candidate stays unchanged. Failed coding, checks or review yield a
blocked report without another coding invocation. No experimental per-ticket
script is needed. Draft publication still requires passing checks and lead
review, and never grants merge or deployment authority.

## Workspace and recovery contract

The controller restores UID/GID 1000 ownership when a worker hands back a commit
and before validation. This includes Git objects created by controller commits
or integration cherry-picks. Ownership changes are confined to isolated run
workspaces and never dereference symlinks.

Workers and checks run as UID/GID 1000. `/tmp` remains non-executable data scratch;
`/build` is a bounded, executable temporary filesystem. `TMPDIR` and `GOTMPDIR`
point to `/build`, so Go tests that spawn executables use the same convention in
both environments. The full workspace remains read-only to workers except for
their approved paths.

Schema 2 approvals now also bind `recoveryPolicy`: one infrastructure retry and
no automatic worker replay. This allowance is separate from the existing one
code repair per engineer. It never extends the original 60-minute deadline or
the 22:00–06:00 Eastern admission window.

After integration, the controller atomically checkpoints the committed candidate
before validation, after passing checks, and after lead approval. On interruption,
the next queue tick can resume validation, read-only review, or publication using
the same packet, commit and workspace. Source changes, missing evidence, stale
tickets/dependencies, failed product checks, rejected reviews, exhausted retries,
or expired deadlines stop delivery. A worker with an uncertain outcome is
preserved for operator review rather than invoked again as a code repair.

Before creating a PR, publication looks for an existing PR on the exact branch.
An open PR with the expected commit and base is recorded without another push
or creation. A conflicting or closed PR blocks delivery. This handles a process
interruption after GitHub accepted creation but before the receipt was saved.

Morning receipts distinguish `retryable`, `interrupted`, `blocked`, and
`draft-pr-created`. They retain checks, worker attempts, infrastructure retry
count, current phase, candidate commit, and the next action when blocked.

### Research basis and limits

- [Stripe Minions](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2): predictable delivery steps around bounded agent work.
- [Symphony specification](https://github.com/openai/symphony/blob/main/SPEC.md): isolated workspaces, explicit run state, and reconciliation after interruption.
- [Development Containers](https://devcontainers.github.io/implementors/json_reference/): explicit user identity and ownership at container boundaries.
- [Pi RPC](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/rpc.md): structured session events; adoption requires matching the installed Pi version.

These changes retain NemoClaw as lead, Pi as engineers, and AgentShift as the
tracker. They do not migrate to another orchestrator. The fixed-address model
bridge still needs a separate Windows/WSL restart test. Recovery of an interrupted
coding worker remains intentionally manual. No merge or deployment authority is added.
