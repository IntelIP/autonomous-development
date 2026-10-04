import test from 'node:test';
import assert from 'node:assert/strict';
import { runLead, gatewayOptions } from '../controller/lead_gateway.mjs';

test('large prompt stays intact and acceptance is saved before completion', async () => {
  const request = { requestId: 'request-1', agent: 'lead', prompt: '💡'.repeat(40000), deadlineMs: Date.now() + 5000 };
  const saved = [], calls = [];
  const result = { result: { payloads: [{ text: '{"approved":true}' }] } };
  const actual = await runLead(request, null, (callbacks) => ({
    start: () => callbacks.onHelloOk({ policy: { maxPayload: 512 * 1024 } }),
    stop: () => callbacks.onClose(),
    request: async (method, params, opts) => {
      calls.push(method);
      assert.equal(params.message, request.prompt);
      opts.onAccepted({ runId: 'native-run-1' });
      assert.equal(saved[0].runId, 'native-run-1');
      return result;
    },
  }), (value) => saved.push(value));
  assert.deepEqual(actual, result);
  assert.deepEqual(calls, ['agent']);
  assert.equal(saved[1].status, 'completed');
});

test('reconnect waits for the accepted run without submitting another turn', async () => {
  const calls = [], saved = [];
  await assert.rejects(runLead({ requestId: 'r', deadlineMs: Date.now() + 5000 }, { runId: 'existing' }, (callbacks) => ({
    start: () => callbacks.onHelloOk({}), stop() {},
    request: async (method, params) => { calls.push(method); assert.equal(params.runId, 'existing'); return { status: 'ok' }; },
  }), (value) => saved.push(value)), /no replay/);
  assert.deepEqual(calls, ['agent.wait']);
  assert.equal(saved[0].waitOutcome.status, 'ok');
});

test('gateway payload limit blocks dispatch before any agent starts', async () => {
  let calls = 0;
  await assert.rejects(runLead({ requestId: 'r', agent: 'lead', prompt: 'x'.repeat(200), deadlineMs: Date.now() + 5000 }, null, (callbacks) => ({
    start: () => callbacks.onHelloOk({ policy: { maxPayload: 100 } }), stop() {}, request: async () => { calls++; },
  }), () => {}), /payload limit/);
  assert.equal(calls, 0);
});


test('gateway defaults and authentication preserve local runtime settings', () => {
  for (const config of [{}, { gateway: null }, { gateway: { auth: null } }]) {
    assert.deepEqual(gatewayOptions(config), { url: 'ws://127.0.0.1:18789', token: undefined, password: undefined });
  }
  assert.deepEqual(gatewayOptions({ gateway: { port: 12345, auth: { token: 'fixture-token', password: 'fixture-password' } } }), {
    url: 'ws://127.0.0.1:12345', token: 'fixture-token', password: 'fixture-password',
  });
});
