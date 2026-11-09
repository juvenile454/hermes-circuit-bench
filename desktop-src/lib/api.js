// REST helpers for the bench API: result envelopes, error mapping, query strings. Pure.

export function isEnvelope(x) {
  return Boolean(x) && typeof x === 'object' && typeof x.ok === 'boolean' && 'error' in x && 'result' in x
}

/** Client-side error envelope. Codes outside contracts.ERROR_CODES are UI-only: backend_unavailable, network_error, unauthorized,
 *  backend_error, bad_response, fixture_missing. */
export function errorEnvelope(action, code, message, hint = null, http = null) {
  return {
    ok: false, action: action || 'request', summary: message, result: null, checks: [], warnings: [], assumptions: [],
    sources: [], simulated: false, error: { code, message, hint }, http
  }
}

/** ctx.rest throws `Error("<status>: <body>")` (+ `statusCode`) for HTTP >= 400; anything else is transport. */
export function parseRestError(err, action) {
  const msg = String(err?.message ?? err ?? '')
  // Electron IPC wraps the message on newer hosts: "Error invoking remote method 'hermes:api': Error: 503: {…}"
  const m = /^(\d{3}):\s?([\s\S]*)$/.exec(msg) || /\bError:\s(\d{3}):\s?([\s\S]*)$/.exec(msg)
  const status = Number.isInteger(err?.statusCode) ? err.statusCode : m ? Number(m[1]) : null
  const body = m ? m[2] : ''
  if (status) {
    let parsed = null
    const at = body.indexOf('{')
    if (at >= 0) {
      try { parsed = JSON.parse(body.slice(at)) } catch { parsed = null }
    }
    if (isEnvelope(parsed)) return { ...parsed, http: status }
    if (status === 404) {
      return errorEnvelope(action, 'backend_unavailable', 'The Circuit Bench backend did not answer this route (404).',
        'Enable the Circuit Bench agent plugin (Capabilities → Plugins) and restart the backend.', 404)
    }
    if (status === 401 || status === 403) {
      return errorEnvelope(action, 'unauthorized', `The backend refused the request (${status}).`, 'Reconnect to Hermes and try again.', status)
    }
    const detail = parsed && typeof parsed.detail === 'string' ? parsed.detail : body.slice(0, 160)
    return errorEnvelope(action, 'backend_error', `Backend error ${status}${detail ? `: ${detail}` : ''}`, 'Try again; see the backend log.', status)
  }
  if (/bridge unavailable/i.test(msg)) {
    return errorEnvelope(action, 'network_error', 'Hermes Desktop bridge unavailable.', 'Restart Hermes Desktop.', null)
  }
  return errorEnvelope(action, 'network_error', `Cannot reach the Hermes backend${msg ? ` (${msg.slice(0, 120)})` : ''}.`,
    'Check that the backend is running, then retry.', null)
}

/** A 2xx body that is not an envelope (should not happen with the bench routes). */
export function asEnvelope(body, action) {
  if (isEnvelope(body)) return body
  return errorEnvelope(action, 'bad_response', 'The backend answered with an unexpected shape.', null, 200)
}

/** {a: 1, b: null, c: "x y"} → "?a=1&c=x%20y" (null/undefined skipped, booleans as true/false). */
export function query(params) {
  const parts = []
  for (const [k, v] of Object.entries(params || {})) {
    if (v === null || v === undefined || v === '') continue
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

/** True when an error means "the backend is not there" (empty state instead of a red error). */
export function isOffline(env) {
  return Boolean(env && !env.ok && ['backend_unavailable', 'network_error'].includes(env.error?.code))
}
