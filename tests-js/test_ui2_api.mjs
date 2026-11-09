// Error envelopes survive the host's IPC wrapping (Hermes Desktop: "Error invoking remote method
// 'hermes:api': Error: 503: {…}"), so a dependency_missing answer is shown as such and not as "cannot reach".
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseRestError } from '../desktop-src/lib/api.js'

const env = { ok: false, action: 'schematic.render', summary: 'schemdraw is not installed; cannot draw the schematic', result: null, checks: [], warnings: [],
  assumptions: [], sources: [], simulated: false, error: { code: 'dependency_missing', message: 'schemdraw is not installed; cannot draw the schematic', hint: 'install the plugin dependencies' } }

test('plain "<status>: <body>" (v0.22.5) and the IPC-wrapped form (current main) give the same envelope', () => {
  for (const msg of [`503: ${JSON.stringify(env)}`, `Error invoking remote method 'hermes:api': Error: 503: ${JSON.stringify(env)}`]) {
    const out = parseRestError(new Error(msg), 'schematic.render')
    assert.equal(out.ok, false)
    assert.equal(out.error.code, 'dependency_missing', msg.slice(0, 40))
    assert.equal(out.http, 503)
  }
})

test('wrapped non-envelope bodies keep their status; transport errors stay network_error', () => {
  assert.equal(parseRestError(new Error("Error invoking remote method 'hermes:api': Error: 404: Not Found"), 'x').error.code, 'backend_unavailable')
  assert.equal(parseRestError(new Error("Error invoking remote method 'hermes:api': Error: 500: boom"), 'x').error.code, 'backend_error')
  assert.equal(parseRestError(new Error('fetch failed: ECONNREFUSED'), 'x').error.code, 'network_error')
  assert.equal(parseRestError(new Error('Error: connection reset'), 'x').error.code, 'network_error')
})
