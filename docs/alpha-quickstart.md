# Autonomous Development alpha

## Outcome and authority

An approved ticket becomes an isolated code change, independent check results, a lead review, and a draft PR when all gates pass. A human retains merge and deployment authority.

```text
AgentShift or local ticket file
  -> operator-approved execution packet
  -> NemoClaw/OpenClaw tech lead
  -> selected coding agent in a restricted container
  -> controller combines commits and runs independent checks
  -> lead reviews the exact candidate
  -> draft PR or blocked report
```

Select one runtime per ticket. Up to two engineers use that runtime on separate file scopes. Mixed runtimes within one ticket are not implemented. Each engineer gets one repair; failed checks and rejected reviews share this allowance. The run lasts at most 60 minutes. Normal admission is 10 PM–6 AM America/New_York; `--pilot` permits supervised daytime runs.

## Runtime support

| Runtime | Adapter | Live evidence | Remaining validation |
|---|---|---|---|
| Pi | Managed full stack or native minimal | Real supervised product work passed checks and lead review; a draft PR was published | Human product review and unattended reliability |
| Codex | Native CLI | Published alpha.3 source and a generic worker produced a checked, lead-approved synthetic fix and draft PR; earlier product trials were rejected | Accepted product result and unattended reliability |
| Claude Code | Native CLI | Local Ollama generated code; after supervised resumption of the paused repair, all checks passed and lead review rejected a remaining evidence-identity flaw | Accepted product result and draft PR; this trial exhausted its repair allowance |
| OpenCode | Native CLI | Existing Codex subscription; implementation and repair passed independent checks, then lead rejected the final result | Accepted product result and draft PR; this trial exhausted its repair allowance |

All four have protocol tests. These do not prove provider access. A zero process exit without the native completion event fails closed. Native usage is retained when available; missing usage is not reported as zero cost.

OpenCode receives native permission to use `/tmp/*` and `/build/*` inside its container. Docker still enforces repository write scopes. This permits existing build caches and temporary files without granting host paths.

Containerized Claude Code exposes `Read`, `Bash`, `Glob`, and `Grep`. Its normal `Edit`/`Write` tools create temporary sibling files or rename targets, which conflicts with individual writable file mounts. The adapter directs in-place writes through Bash/Python instead. Tools such as `gofmt -w` and `sed -i` have the same limitation: capture their transformed output, then write it directly to the approved file. Host invocations retain Claude's native editors. A real Claude/Ollama fixture verified an approved write and protected neighboring files; local-model instruction following remains inconsistent.

Inside Docker, Codex uses the container's enforced writable mounts and process limits instead of trying to create a second Linux sandbox. Native host invocations keep Codex's workspace sandbox. Other native CLIs use the same outer container restrictions. Validation receives a private Git metadata copy in container memory, so tools can create validation worktrees without changing the controller's Git metadata.

Pi's full profile includes its existing Jev/Warden/extensions. Other agents use their own tool systems. Pi extensions do not automatically transfer. Interchangeability currently means a shared task, authority, and result contract, not identical features or measured quality.

See [native trial evidence](native-agent-trials.md). These supervised runs demonstrate one product workflow; they do not rank agent performance.

## Prerequisites

Use Linux or Windows WSL with Python 3.11+, Git, Docker, OpenSSH client tools (`ssh` and `scp`), and authenticated GitHub CLI. OpenShell uploads require those client tools in the controller environment too. The controller uses Linux ownership and `fcntl`; direct macOS execution is unvalidated. The Mac can remain the planning and review machine.

NemoClaw/OpenClaw and OpenShell must already be installed and healthy. Configure `controller/lead.json` for your existing lead agent/provider/model. The bundle does not install that infrastructure or create accounts. Existing personal logins do not establish enterprise account suitability or redistribution rights.

This is an experimental public source release. Project source uses [Apache License 2.0](../LICENSE). Third-party runtimes retain their own licenses and account terms.

## Build a native image

From the unpacked bundle, or the agent-stack source checkout:

```sh
export AGENT=codex
export AGENT_VERSION=0.155.1
docker build -f agent/Dockerfile.runtime --build-arg AGENT="$AGENT" --build-arg AGENT_VERSION="$AGENT_VERSION" -t "ad-worker:$AGENT-$AGENT_VERSION" .
```

Choose an explicitly reviewed publisher version. Runtime names: `pi`, `codex`, `claude-code`, `opencode`. Windows trial images were built for Codex 0.155.1, Claude Code 2.1.284 and OpenCode 1.18.33 using the existing product toolchain as `BASE_IMAGE`. For repositories requiring Go or other compilers, pass `--build-arg BASE_IMAGE=YOUR_EXISTING_TOOLCHAIN_IMAGE`. The default generic Node image still needs clean-host validation. Existing Pi images may be reused. Approval records the installed image ID.

## Host configuration

```sh
export AD_STATE=/var/lib/autonomous-development
export AD_DOCKER_HOST=unix:///run/docker.sock
export AD_TRACKER_URL=http://127.0.0.1:3000
export AD_GITHUB_CLI=/usr/bin/gh
export AD_NEMOCLAW=/path/to/nemoclaw
export AD_OPENSHELL=/path/to/openshell
export AD_SANDBOX=local-claw
export AD_GATEWAY=nemoclaw
```

Use actual installed paths. An empty `AD_DOCKER_HOST` uses Docker's context. Optional `AGENT_STACK_GRAPHIFY` selects Graphify. Runtime configuration is bound to approval; configure it before preparing the packet.

Provide only the selected runtime's existing cache in its dedicated directory:

| Runtime | Cache under `AD_STATE` |
|---|---|
| Pi | `auth/auth.json` |
| Codex | `auth-codex/auth.json` |
| Claude Code | `auth-claude-code/.credentials.json` or native `settings.json` |
| OpenCode | `auth-opencode/opencode/auth.json` |

Claude Code may use its native settings file for an existing compatible gateway or local Ollama endpoint. The Windows gateway trials stopped on HTTP 402. The user-approved local trial uses `gpt-oss-pi:latest` through Docker's `http://host.docker.internal:11434` route and Ollama's Anthropic-compatible interface. It does not use an Anthropic model and cannot establish Claude-model quality. Existing cluster network policy remains enforced; do not substitute a plaintext Tailnet endpoint. Keep private settings outside the repository.

The container runs as UID 1000. Its cache must be readable and writable by that user for native token refresh. Keep it outside repositories and images. Do not mount your entire home or GitHub/SSH credentials. Keychain-only credentials require runtime-supported container authentication; copying an empty cache is insufficient. Docker bridge networking permits provider access; outbound allowlisting is not implemented.

## Seed and run

Prepare the lead's upload directory after creating or rebuilding its sandbox:

```sh
"$AD_NEMOCLAW" "$AD_SANDBOX" exec -- mkdir -p /sandbox/autonomous-requests
```

If the controller runs in a container, give it its own writable OpenShell connection configuration. NemoClaw selects the gateway and OpenShell updates configuration permissions; a read-only configuration mount fails. Keep credentials private and outside the source bundle. See [the published-source demo result](published-source-demo.md) for the tested boundary and setup repairs.

```sh
python3 scripts/prepare-demo.py --directory /srv/ad-demo --github-repository YOUR_OWNER/YOUR_DEMO_REPO --stack-root "$PWD" --agent codex --model gpt-6-sol --image ad-worker:codex-0.155.1 --workflow bugfix
```

This creates a new local repository and prints issue/project IDs. It refuses existing directories. `bugfix` seeds an incorrect sum; `docs` seeds an incorrect documented example. Both use synthetic data, committed checks, and one writable file. In separate source checkouts, set `--stack-root` to the agent-stack checkout instead.

Publish seeded `main` to your chosen GitHub repository before testing draft PR creation. The generator does not create a remote repository or publish anything.

```sh
export AD_TICKETS_FILE=/srv/ad-demo/.alpha/tickets.json
python3 controller/engineering.py packet --issue ISSUE_ID --project PROJECT_ID --packet "$AD_STATE/queue/demo.json"
# Review the generated packet before approving:
python3 controller/engineering.py approve --packet "$AD_STATE/queue/demo.json"
python3 controller/engineering.py run --pilot --packet "$AD_STATE/queue/demo.json"
```

For AgentShift, unset `AD_TICKETS_FILE` and use its issue/project IDs. Local revisions hash ticket content; changes invalidate approval. Plane is not required.

Review `AD_STATE/runs/RUN_ID/receipt.json`, native logs, check reports, and lead evidence. A blocked report is not a completed product. Healthy services, fixture tests, local CLI demos, and installed schedules do not establish unattended delivery.

## Package from the source repository

```sh
python3 scripts/package-alpha.py --stack-root /path/to/agent-stack --version 0.1.0-alpha.3 --output /tmp/autonomous-development-0.1.0-alpha.3.tar.gz
```

The archive includes explicitly listed files and a manifest of the version, source revisions, dirty-source flags and file hashes. See [the release guide](releases.md) for preparation and evidence boundaries. Before public release: review third-party redistribution, approve the concrete archive, verify new-host setup, and demonstrate the supported delivery paths through real ticket-to-draft-PR runs. Keep unsupported or rejected runtime results clearly labeled.
