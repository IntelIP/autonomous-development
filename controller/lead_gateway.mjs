// Submit file-backed lead requests through OpenClaw's installed Gateway client.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

export async function runLead(request, previous, makeClient, save, now = Date.now) {
  const remaining = () => Math.max(0, request.deadlineMs - now());
  if (remaining() <= 0) throw new Error('Lead deadline expired');
  if (previous?.result) return previous.result;
  return await new Promise((resolve, reject) => {
    let client, acceptedRunId, started = false, settled = false;
    const timer = setTimeout(() => finish(new Error('Lead deadline expired; inspect saved Gateway run')), remaining());
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      client?.stop();
      if (error) reject(error); else resolve(result);
    };
    const previousRunId = previous?.runId;
    const submitLead = async (hello) => {
      const params = {
        agentId: request.agent, message: request.prompt, sessionId: request.requestId,
        sessionKey: `agent:${request.agent}:autonomous-${request.requestId}`,
        idempotencyKey: request.requestId, thinking: 'off', deliver: false,
        timeout: Math.max(1, Math.floor(remaining() / 1000)),
      };
      const size = Buffer.byteLength(JSON.stringify({ type: 'req', id: request.requestId, method: 'agent', params }));
      if (!(size <= hello.policy?.maxPayload)) throw new Error('Lead request exceeds Gateway payload limit');
      const result = await client.request('agent', params, {
        expectFinal: true, timeoutMs: remaining(),
        onAccepted: (accepted) => {
          if (!accepted?.runId) throw new Error('Gateway accepted a lead request without a run ID');
          acceptedRunId = accepted.runId;
          save({ requestId: request.requestId, status: 'accepted', runId: accepted.runId });
        },
      });
      save({ requestId: request.requestId, runId: acceptedRunId || result.runId, status: 'completed', result });
      finish(null, result);
    };
    client = makeClient({
      onHelloOk: async (hello) => {
        if (started) return;
        started = true;
        try {
          if (previousRunId) {
            // Waiting never submits another agent turn, even if the Gateway lost its cache.
            const outcome = await client.request('agent.wait', { runId: previousRunId, timeoutMs: remaining() }, { timeoutMs: remaining() });
            save({ ...previous, waitOutcome: outcome });
            throw new Error(`Existing lead run ${previousRunId}: ${outcome.status}; final response unavailable, no replay`);
          }
          await submitLead(hello);
        } catch (error) { finish(error); }
      },
      onConnectError: () => finish(new Error('Lead Gateway connection failed')),
      onClose: () => finish(new Error('Lead Gateway disconnected; inspect saved run')),
    });
    client.start();
  });
}

export function gatewayOptions(config) {
  const gateway = config.gateway ?? {};
  const auth = gateway.auth ?? {};
  return { url: `ws://127.0.0.1:${gateway.port || 18789}`, token: auth.token, password: auth.password };
}

async function main() {
  const requestPath = process.argv[2];
  const request = JSON.parse(fs.readFileSync(requestPath, 'utf8'));
  const receiptPath = path.join(path.dirname(requestPath), 'gateway-receipt.json');
  const previous = fs.existsSync(receiptPath) ? JSON.parse(fs.readFileSync(receiptPath, 'utf8')) : null;
  if (previous && previous.requestId !== request.requestId) throw new Error('Lead request identity changed');
  const config = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.openclaw/openclaw.json'), 'utf8'));
  const options = gatewayOptions(config);
  const { GatewayClient } = await import('/usr/local/lib/node_modules/openclaw/dist/plugin-sdk/gateway-runtime.js');
  const result = await runLead(request, previous, (callbacks) => new GatewayClient({
    ...options,
    clientName: 'cli', mode: 'cli', scopes: ['operator.read', 'operator.write'],
    ...callbacks,
  }), (value) => {
    fs.writeFileSync(receiptPath + '.tmp', JSON.stringify(value), { mode: 0o600 });
    fs.renameSync(receiptPath + '.tmp', receiptPath);
  });
  process.stdout.write(JSON.stringify(result) + '\n');
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch((error) => {
    if (process.argv[2]) {
      const message = String(error.message).replace(/(?:Bearer\s+|(?:token|password)[=:]\s*)\S+/gi, '[redacted]');
      fs.writeFileSync(path.join(path.dirname(process.argv[2]), 'gateway-error.json'), JSON.stringify({ name: error.name, message }), { mode: 0o600 });
    }
    // Gateway error strings can contain connection details. Keep credentials out of logs.
    process.stderr.write('Lead Gateway request failed; inspect the private Gateway receipt and logs.\n');
    process.exitCode = 1;
  });
}
