// Development fixture backend, only with embedded fixtures (product: CB_FIXTURES = null) and `useFixtures`.
// Answers the bench routes from desktop-src/fixtures/*.json (real answers), projects in memory (PLAN flow end to end);
// uncovered verdicts come from a "pins.map/<chip>/<variant>/<wifi-on|off>" fixture, marked {fixtures: composed}.

const FIXTURE_COMPOSED = { key: 'fixtures', value: 'composed', reason: 'development fixture backend: verdicts from the pin-map fixture (mode in)' }

function fxClone(x) {
  return x === undefined ? undefined : JSON.parse(JSON.stringify(x))
}

function fxError(action, code, message, http, hint = null) {
  return { ok: false, action, summary: message, result: null, checks: [], warnings: [], assumptions: [], sources: [],
    simulated: false, error: { code, message, hint }, http }
}

function fxOk(action, summary, result, extra = {}) {
  return { ok: true, action, summary, result, checks: [], warnings: [], assumptions: [], sources: [], simulated: false,
    error: null, ...extra }
}

// = schematic.blocks() (test_api_fixtures.py)
export const FIXTURE_BLOCKS = ['led', 'npn_low_side', 'button_pullup', 'divider', 'module', 'level_shifter']

function sameAssignments(a, b) {
  const key = x => (x || []).map(p => `${p.role}|${p.pin}|${p.mode}`).sort().join(',')
  return key(a) === key(b)
}

export function mapKey(chip, variant, wifi) {
  return `pins.map/${chip}/${variant || '-'}/${wifi ? 'wifi-on' : 'wifi-off'}`
}

export function createFixtureBackend(fixtures, { delayMs = 60 } = {}) {
  const fx = fixtures || {}
  const projects = new Map()
  const seedProjects = () => {
    projects.clear()
    for (const [name, env] of Object.entries(fx)) {
      if (name.startsWith('project.') && env?.result?.project) projects.set(env.result.project.id, fxClone(env.result.project))
    }
  }
  seedProjects()

  const mapPins = (chip, variant, wifi) => {
    const env = fx[mapKey(chip, variant, wifi)]
    const m = new Map()
    for (const p of env?.result?.pins || []) m.set(p.pin, p)
    return env ? m : null
  }

  const composeCheck = body => {
    const { chip, variant, wifi, devkit } = body || {}
    const m = mapPins(chip, variant, wifi)
    if (!m) return fxError('pins.check', 'fixture_missing', `No pin-map fixture for ${mapKey(chip, variant, wifi)}.`, 404)
    const pins = (body.assignments || []).map(a => {
      const e = m.get(a.pin)
      return e
        ? { role: a.role, mode: a.mode, pin: a.pin, name: e.name, verdict: e.verdict, rule_ids: e.rule_ids || [],
          reasons: e.reasons || [], functions: e.functions || [], header: e.header ?? null,
          alternatives: e.verdict === 'blocked' ? [...m.values()].filter(x => x.verdict === 'ok' && !(x.rule_ids || []).length
            && !(body.assignments || []).some(y => y.pin === x.pin)).map(x => x.pin).slice(0, 3) : [] }
        : { role: a.role, mode: a.mode, pin: a.pin, name: `GPIO${a.pin}`, verdict: null, rule_ids: [], reasons: [],
          functions: [], header: null, alternatives: [] }
    })
    const counts = { ok: 0, caution: 0, blocked: 0 }
    for (const p of pins) if (counts[p.verdict] !== undefined) counts[p.verdict]++
    return fxOk('pins.check', `Fixture check: ${counts.ok} ok, ${counts.caution} caution, ${counts.blocked} blocked.`,
      { chip, title: chip, variant: variant ?? null, wifi: Boolean(wifi), devkit: devkit ?? null, counts, pins },
      { assumptions: [FIXTURE_COMPOSED], sources: fxClone(fx[mapKey(chip, variant, wifi)]?.sources || []) })
  }

  const pinsCheck = body => {
    // modules: pins.check.<project>, or the recorded answer with the same assignments
    const pid = body?.project
    const recorded = Object.keys(fx).filter(k => k.startsWith('pins.check.')).map(k => fx[k])
    if (pid && /^modules-/.test(pid)) return fxClone(fx[`pins.check.${pid}`] || fxError('pins.check', 'fixture_missing', `No fixture pins.check.${pid}.json.`, 404))
    const hit = (body?.parts || []).some(x => x && x.module)
      && recorded.find(e => e?.result?.modules && e.result.chip === body.chip && sameAssignments(e.result.pins, body.assignments))
    if (hit) return fxClone(hit)
    const base = fx['pins.check']
    const r = base?.result
    if (r && body && r.chip === body.chip && (r.variant ?? null) === (body.variant ?? null) && Boolean(r.wifi) === Boolean(body.wifi)
      && sameAssignments(r.pins, body.assignments)) return fxClone(base)
    return composeCheck(body)
  }

  const pinsSuggest = body => {
    const base = fx['pins.suggest']
    const r = base?.result
    const req = (body?.requests || [])[0]
    if (r && req && r.chip === body.chip && (r.variant ?? null) === (body.variant ?? null)
      && (body.requests || []).length === 1 && r.requests?.[0]?.role === req.role && r.requests?.[0]?.mode === req.mode) {
      return fxClone(base)
    }
    const m = mapPins(body?.chip, body?.variant, body?.wifi)
    if (!m) return fxError('pins.suggest', 'fixture_missing', 'No pin-map fixture for this board.', 404)
    const taken = new Set(body?.taken || [])
    const requests = (body?.requests || []).map(q => ({
      role: q.role, mode: q.mode, requested: q.requested ?? null,
      suggestions: [...m.values()].filter(x => x.verdict === 'ok' && !(x.rule_ids || []).length && !taken.has(x.pin) && x.pin !== q.requested)
        .sort((a, b) => a.pin - b.pin).slice(0, 3).map(x => ({ gpio: x.pin, header: x.header ?? null })),
      excluded: []
    }))
    return fxOk('pins.suggest', 'Fixture suggestions from the pin map.', { chip: body.chip, variant: body.variant ?? null,
      wifi: Boolean(body.wifi), devkit: body.devkit ?? null, taken: [...taken], requests }, { assumptions: [FIXTURE_COMPOSED] })
  }

  const pinsInfo = params => {
    const gpio = Number(params.get('pin'))
    const base = fx['pins.info']
    if (base?.result?.gpio === gpio && base.result.chip === params.get('chip')) return fxClone(base)
    const project = [...projects.values()][0]
    const m = mapPins(params.get('chip'), params.get('variant'), project?.options?.wifi)
    const e = m?.get(gpio)
    if (!e) return fxError('pins.info', 'fixture_missing', `No fixture for GPIO${gpio}.`, 404)
    return fxOk('pins.info', `GPIO${gpio} (fixture, from the pin map).`, {
      chip: params.get('chip'), variant: params.get('variant'), gpio, name: e.name, header: e.header ?? null, broken_out: Boolean(e.header),
      functions: e.functions || [], rules: (e.reasons || []).map(x => ({ ...x, applies: true })), modes: null
    }, { assumptions: [FIXTURE_COMPOSED] })
  }

  // module catalog: catalog routes and module ops from modules.list, modules.info.<id>, calc.meta,
  // pins.check.modules-*, project.modules-*; no fixture → fixture_missing, id outside the list → invalid_args.
  const modItems = () => (Array.isArray(fx['modules.list']?.result?.items) ? fx['modules.list'].result.items : [])
  const modInfoOf = id => {
    const r = fx[`modules.info.${id}`]?.result
    return r ? r.module ?? r : null
  }
  const modFind = idOrAlias => {
    const key = String(idOrAlias || '').trim().toLowerCase()
    const hit = modItems().find(m => m.id === key || (m.aliases || []).includes(key))
    const info = modInfoOf(hit?.id || key)
    return hit || info ? { ...(hit || {}), ...(info || {}), id: hit?.id || info.id || key, info } : null
  }
  const modUnknown = (where, id) => fxError('project.update', 'invalid_args', `${where}: unknown module ${JSON.stringify(id)}`, 400,
    'list the catalog with bench_pins action=modules')
  const modIfaceOf = m => (m.interfaces || []).map(x => (typeof x === 'string' ? x : x?.type))
  const modList = params => {
    const env = fx['modules.list']
    if (!env) return null
    const q = (params.get('q') || '').trim().toLowerCase()
    const cat = params.get('category') || ''
    const iface = params.get('interface') || ''
    const hits = modItems().filter(m => (!q || [m.id, m.title, m.category, ...(m.aliases || [])].some(s => String(s || '').toLowerCase().includes(q)))
      && (!cat || m.category === cat || String(m.category || '').startsWith(`${cat}.`)) && (!iface || modIfaceOf(m).includes(iface)))
    const offset = Math.max(0, Number(params.get('offset')) || 0)
    const limit = Math.max(1, Number(params.get('limit')) || 40)
    const out = fxClone(env)
    out.result = { ...out.result, total: hits.length, items: fxClone(hits.slice(offset, offset + limit)) }
    if (q || cat || iface) out.summary = `${hits.length} module(s) match (fixture filter).`
    return out
  }
  const modInfo = (id, params) => {
    const variant = params.get('variant')
    const env = (variant && fx[`modules.info.${id}.${variant}`]) || fx[`modules.info.${id}`]
    if (env) return env
    const hit = modItems().find(m => m.id === id || (m.aliases || []).includes(id))
    if (hit && fx[`modules.info.${hit.id}`]) return fx[`modules.info.${hit.id}`]
    return hit ? fxError('modules.info', 'fixture_missing', `No fixture modules.info.${hit.id}.json.`, 404)
      : fxError('modules.info', 'invalid_args', `unknown module ${JSON.stringify(id)}`, 400, 'list the catalog with bench_pins action=modules')
  }
  const NET_RE = /^[A-Za-z0-9_+.-]{1,32}$/
  const connProblem = (where, conn, mod) => {
    if (!conn || typeof conn !== 'object' || Array.isArray(conn)) return `${where}: conn must be an object {pin: net}`
    if (Object.keys(conn).length > 48) return `${where}: at most 48 pins per part`
    const pins = Array.isArray(mod?.info?.pins) ? mod.info.pins.map(x => x.name) : null
    for (const [pin, net] of Object.entries(conn)) {
      if (pins && !pins.includes(pin)) return `${where}: ${mod.id} has no pin ${pin}`
      if (net !== null && !NET_RE.test(String(net))) return `${where}: net ${JSON.stringify(net)} for ${pin} is not a net name`
    }
    return null
  }
  const FX_MODULE_OPS = {
    add_module: (p, op) => {
      const mod = modFind(op.module)
      if (!mod) return modUnknown('add_module', op.module)
      const parts = p.parts || []
      const used = new Set(parts.map(x => x.ref))
      let ref = op.ref ? String(op.ref).trim().toUpperCase() : null
      if (ref && used.has(ref)) return fxError('project.update', 'invalid_args', `add_module: part ${ref} exists`, 400)
      for (let n = 1; !ref; n++) if (!used.has(`U${n}`)) ref = `U${n}`
      const bad = op.conn ? connProblem('add_module', op.conn, mod) : null
      if (bad) return fxError('project.update', 'invalid_args', bad, 400)
      const addrs = (mod.addresses || mod.info?.interfaces?.flatMap(i => i.addresses?.value || i.addresses || []) || []).map(String)
      if (op.address && addrs.length && !addrs.includes(String(op.address))) {
        return fxError('project.update', 'invalid_args', `add_module: ${mod.id} has no address ${op.address} (${addrs.join(', ')})`, 400)
      }
      const conn = op.conn ? Object.fromEntries(Object.entries(op.conn).filter(([, v]) => v !== null)) : null
      p.parts = [...parts, { ref, kind: mod.kind || 'module', value: String(mod.title || mod.id).split(/\s+/)[0], module: mod.id,
        ...(op.variant ? { variant: op.variant } : {}), ...(conn && Object.keys(conn).length ? { conn } : {}),
        ...(op.address ? { address: String(op.address) } : {}), ...(op.facts ? { facts: fxClone(op.facts) } : {}),
        ...(op.qty ? { qty: Number(op.qty) } : {}) }]
      return null
    },
    connect: (p, op) => {
      const part = (p.parts || []).find(x => x.ref === String(op.ref || '').trim().toUpperCase())
      if (!part) return fxError('project.update', 'invalid_args', `connect: no part ${op.ref} in this project`, 400)
      const bad = connProblem('connect', op.conn, part.module ? modFind(part.module) : null)
      if (bad) return fxError('project.update', 'invalid_args', bad, 400)
      const conn = { ...(part.conn || {}), ...op.conn }
      for (const [k, v] of Object.entries(conn)) if (v === null) delete conn[k]
      if (Object.keys(conn).length > 48) return fxError('project.update', 'invalid_args', `connect: at most 48 pins per part`, 400)
      if (Object.keys(conn).length) part.conn = conn
      else delete part.conn
      return null
    },
    set_rails: (p, op) => {
      if (!op.rails && !op.rail_limits) return fxError('project.update', 'invalid_args', 'set_rails: give rails or rail_limits', 400)
      for (const [net, v] of Object.entries(op.rails || {})) {
        if (['GND', '3V3', '5V'].includes(net)) return fxError('project.update', 'invalid_args', `set_rails: ${net} is a fixed rail`, 400)
        if (!NET_RE.test(net) || (v !== null && !(typeof v === 'number' && v >= 0 && v <= 60))) {
          return fxError('project.update', 'invalid_args', `set_rails: ${net} must be a net name with 0–60 V (low voltage only)`, 400)
        }
      }
      for (const [net, a] of Object.entries(op.rail_limits || {})) {
        if (!NET_RE.test(net) || (a !== null && !(typeof a === 'number' && a > 0))) return fxError('project.update', 'invalid_args', `set_rails: limit of ${net} must be > 0 A`, 400)
      }
      const merge = (base, patch) => {
        const out = { ...(base || {}), ...(patch || {}) }
        for (const [k, v] of Object.entries(out)) if (v === null) delete out[k]
        return out
      }
      p.options = { ...p.options, ...(op.rails ? { rails: merge(p.options?.rails, op.rails) } : {}),
        ...(op.rail_limits ? { rail_limits: merge(p.options?.rail_limits, op.rail_limits) } : {}) }
      return null
    }
  }

  const patchProject = (id, body) => {
    const p = projects.get(id)
    if (!p) return fxError('project.update', 'project_not_found', `No project ${id}.`, 404)
    if (body?.expected_rev !== p.rev) {
      return { ...fxError('project.update', 'project_conflict', `Project ${id} is at rev ${p.rev}, not ${body?.expected_rev}.`, 409,
        'Reload the project and try again.'), result: { rev: p.rev } }
    }
    const changed = new Set()
    const by = body?.by === 'agent' ? 'agent' : 'ui'
    for (const op of body?.ops || []) {
      if (op.op === 'assign') {
        const m = mapPins(p.board.chip, p.board.variant, p.options?.wifi)
        const e = m?.get(op.pin)
        const row = { role: op.role, mode: op.mode, pin: op.pin, net: op.net ?? null, verdict: e ? e.verdict : null,
          rule_ids: e ? e.rule_ids || [] : [], updated_by: by }
        const i = p.assignments.findIndex(a => a.role === op.role)
        if (i >= 0) p.assignments[i] = row
        else p.assignments.push(row)
        changed.add('assignments')
      } else if (op.op === 'unassign') {
        p.assignments = p.assignments.filter(a => a.role !== op.role)
        changed.add('assignments')
      } else if (op.op === 'set_board') {
        p.board = { ...p.board, chip: op.chip ?? p.board.chip, variant: op.variant ?? null, devkit: op.devkit ?? null }
        p.options = { ...p.options, wifi: Boolean(op.wifi) }
        changed.add('board'); changed.add('options')
      } else if (op.op === 'solder_done') {
        const done = new Set(p.solder.done)
        if (op.done) done.add(op.step_id)
        else done.delete(op.step_id)
        p.solder.done = [...done]
        changed.add('solder')
      } else if (op.op === 'remove_parts') {
        const refs = new Set((op.refs || []).map(r => String(r).trim().toUpperCase()))
        const missing = [...refs].filter(r => !(p.parts || []).some(x => x.ref === r))
        if (missing.length) return fxError('project.update', 'invalid_args', `remove_parts: no part ${missing.join(', ')} in this project`, 400)
        p.parts = (p.parts || []).filter(x => !refs.has(x.ref))
        changed.add('parts')
      } else if (op.op === 'add_calc') {
        if ((p.calcs || []).some(c => c.id === op.calc?.id)) return fxError('project.update', 'invalid_args', `add_calc: calc ${op.calc?.id} exists`, 400)
        p.calcs = [...(p.calcs || []), fxClone(op.calc)]
        changed.add('calcs')
      } else if (op.op === 'add_parts') {
        p.parts = [...(p.parts || []), ...fxClone(op.parts || [])]
        changed.add('parts')
      } else if (op.op === 'add_circuit') {
        if ((p.circuits || []).some(c => c.id === op.circuit?.id)) return fxError('project.update', 'invalid_args', `add_circuit: circuit ${op.circuit?.id} exists`, 400)
        p.circuits = [...(p.circuits || []), fxClone(op.circuit)]
        changed.add('circuits')
      } else if (op.op === 'note') {
        p.notes = [...(p.notes || []), { text: String(op.text || ''), by }]
        changed.add('notes')
      } else if (FX_MODULE_OPS[op.op]) {
        const err = FX_MODULE_OPS[op.op](p, op)
        if (err) return err
        changed.add(op.op === 'set_rails' ? 'options' : 'parts')
      } else {
        return fxError('project.update', 'invalid_args', `Fixture backend does not support op ${op.op}.`, 400)
      }
    }
    p.rev += 1
    p.updated = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
    return fxOk('project.update', `${p.title}: rev ${p.rev}, changed ${[...changed].join(', ')}.`,
      { rev: p.rev, project: fxClone(p), changed: [...changed] }, { simulated: Boolean(p.simulated) })
  }

  // board operation in fixture mode (development only): jobs finish at once, nothing touches hardware
  const jobs = new Map()
  let jobN = 0
  const startJob = (kind, result) => {
    jobN += 1
    const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
    const j = { job_id: `j-dev${jobN}-fixture`, kind, state: 'done', progress: 1, started: now, finished: now, log_tail: result?.result?.log_tail || [], result }
    jobs.set(j.job_id, j)
    return { ...fxOk('job.get', `${kind} done (fixture).`, fxClone(j), { simulated: true }), http: 202 }
  }
  const detectJob = body => {
    const p = [...projects.values()][0]
    const det = p?.board?.detected
    if (!det || det.port !== body?.port) return fxError('board.detect', 'port_not_found', `No fixture board on ${body?.port}.`, 404)
    return startJob('detect', fxOk('board.detect', `Detected ${det.chip} on ${det.port} (fixture).`, { ...fxClone(det), variant_suggestion: det.variant_suggestion }, { simulated: true }))
  }
  const fixtureJob = kind => {
    const base = fx[`job.${kind}.done`]?.result
    return base ? startJob(kind, fxClone(base.result)) : fxError(`board.${kind}`, 'fixture_missing', `No ${kind} fixture.`, 404)
  }

  const job = id => {
    if (jobs.has(id)) return fxOk('job.get', 'fixture job', fxClone(jobs.get(id)), { simulated: true })
    const all = Object.entries(fx).filter(([k]) => k.startsWith('job.')).map(([, v]) => v)
    const hits = all.filter(v => v?.result?.job_id === id)
    const best = hits.find(v => v.result.state === 'done') || hits[0]
    return best ? fxClone(best) : fxError('job.get', 'job_not_found', `No job ${id}.`, 404)
  }

  // flash.check.{ok,flash_disabled,chip_mismatch} in the guard's order: real port refused (allow_flash
  // off), then a project chip not the detected one (S2-DevKitC-1 after "Apply to project"), else the sim board.
  const flashCheck = params => {
    const p = projects.get(params.get('project') || '')
    if (!p) return fxError('board.flash_check', 'project_not_found', `No project ${params.get('project')}.`, 404)
    const det = p.board?.detected
    const port = params.get('port') || det?.port || ''
    if (!port.startsWith('sim://')) return fx['flash.check.flash_disabled']
    const got = String(det?.chip || '').match(/^esp32(-[a-z0-9]+)?/i)?.[0].toLowerCase().replace('-', '')
    if (got && got !== p.board?.chip) {
      const env = fx['flash.check.chip_mismatch']
      return env?.result?.refusal?.message?.includes(` set to ${p.board.chip}:`) ? env
        : fxError('board.flash_check', 'fixture_missing', `No chip_mismatch fixture for ${p.board.chip}.`, 404)
    }
    return det?.port === port ? fx['flash.check.ok'] : fxError('board.flash_check', 'fixture_missing', `No flash check fixture for ${port}.`, 404)
  }

  const serialTail = params => {
    const base = fx['serial.lines']
    const after = Number(params.get('after') || 0)
    if (!base) return fxError('serial.tail', 'fixture_missing', 'No serial fixture.', 404)
    const r = fxClone(base)
    if (r.result.port !== params.get('port')) {
      return fxOk('serial.tail', 'Port not open.', { port: params.get('port'), state: 'closed', lines: [], panic: null, next_seq: 1 })
    }
    r.result.lines = r.result.lines.filter(l => l.seq > after)
    return r
  }

  // like workshop.schematic: no block → hint "blocks: …"; unrecorded block/part → fixture_missing
  const schematic = body => {
    const b = typeof body?.block === 'string' ? body.block : typeof body?.part === 'string' ? 'module' : null
    if (!b) return fxError('schematic.render', 'invalid_args', 'block is required', 400, `blocks: ${FIXTURE_BLOCKS.join(', ')}`)
    const env = fx[`schematic.${b === 'npn_low_side' ? 'npn' : b}`]
    const part = body?.params?.part ?? body?.part
    return env && (b !== 'module' || env.summary.includes(`${part} `)) ? env
      : fxError('schematic.render', 'fixture_missing', `No fixture schematic.${b}${b === 'module' ? ` for ${part}` : ''}.json.`, 404)
  }

  const routes = [
    ['GET', /^\/health$/, () => fx.health],
    ['GET', /^\/doctor$/, () => fx.doctor],
    ['GET', /^\/projects$/, () => {
      const env = fxClone(fx['projects.list'])
      if (env?.result) env.result.projects = env.result.projects.filter(x => projects.has(x.id)).map(x => ({ ...x, rev: projects.get(x.id).rev }))
      // seeded projects the list fixture does not name (project.modules-demo): listed after the recorded ones
      if (env?.result) {
        for (const p of projects.values()) {
          if (env.result.projects.some(x => x.id === p.id)) continue
          env.result.projects.push({ id: p.id, title: p.title, chip: p.board?.chip, variant: p.board?.variant ?? null, devkit: p.board?.devkit ?? null,
            rev: p.rev, updated: p.updated, simulated: Boolean(p.simulated) })
        }
      }
      return env
    }],
    ['DELETE', /^\/projects\/([a-z0-9-]{1,48})$/, (m) => {
      const p = projects.get(m[1])
      if (!p) return fxError('project.delete', 'project_not_found', `No project ${m[1]}.`, 404)
      projects.delete(m[1])
      return fxOk('project.delete', `Moved bench project '${m[1]}' (${p.title}) to the trash (fixture).`, { id: m[1], title: p.title, trash: `trash/${m[1]}` })
    }],
    ['POST', /^\/projects\/demo$/, () => {
      seedProjects()
      const p = projects.get('laser-trigger')
      if (!p) return null
      if (fx['sim.demo']) {
        const env = fxClone(fx['sim.demo'])
        env.result = { ...env.result, rev: p.rev, created: false }
        return env
      }
      return fxOk('sim.demo', 'Demo project laser-trigger ready (simulated).', { id: p.id, title: p.title, rev: p.rev, created: false }, { simulated: true })
    }],
    ['GET', /^\/projects\/([a-z0-9-]{1,48})$/, (m) => {
      const p = projects.get(m[1])
      if (!p) return fxError('project.get', 'project_not_found', `No project ${m[1]}.`, 404)
      const env = fxClone(fx[`project.${m[1]}`])
      env.result = { project: fxClone(p), rev: p.rev }
      return env
    }],
    ['PATCH', /^\/projects\/([a-z0-9-]{1,48})$/, (m, body) => patchProject(m[1], body)],
    ['GET', /^\/boards\/([a-z0-9-]+)$/, (m) => fx[`board.${m[1]}`] || fxError('board.layout', 'unknown_board', `No board ${m[1]}.`, 400)],
    ['POST', /^\/pins\/check$/, (m, body) => pinsCheck(body)],
    ['POST', /^\/pins\/suggest$/, (m, body) => pinsSuggest(body)],
    ['GET', /^\/pins\/info$/, (m, body, params) => pinsInfo(params)],
    ['GET', /^\/ports$/, () => fx.ports],
    ['GET', /^\/serial\/tail$/, (m, body, params) => serialTail(params)],
    ['POST', /^\/crash\/decode$/, () => fx['crash.decode']],
    ['GET', /^\/jobs\/([A-Za-z0-9-]+)$/, (m) => job(m[1])],
    ['GET', /^\/modules$/, (m, body, params) => modList(params)],
    ['GET', /^\/modules\/([a-z0-9_-]{1,40})$/, (m, body, params) => modInfo(m[1], params)],
    ['GET', /^\/calc$/, () => fx['calc.meta'] || fxError('calc.list', 'fixture_missing', 'No fixture calc.meta.json.', 404)],
    ['POST', /^\/calc\/([a-z0-9_]+)$/, (m) => (m[1] !== 'meta' && fx[`calc.${m[1]}`])
      || fxError(`calc.${m[1]}`, 'fixture_missing', `No fixture calc.${m[1]}.json (development fixtures: recorded calculators only).`, 404)],
    ['POST', /^\/schematic$/, (m, body) => schematic(body)],
    // the plan fixture is the project parts' plan; a pasted BOM has no recorded answer
    ['POST', /^\/solder\/plan$/, (m, body) => body?.bom ? fxError('solder.plan', 'fixture_missing', 'No solder plan fixture for a pasted BOM (development fixtures: project parts only).', 404) : fx['solder.plan']],
    ['POST', /^\/projects\/([a-z0-9-]{1,48})\/solder\/([a-f0-9]{1,40})$/, (m, body) => {
      const p = projects.get(m[1])
      return p ? patchProject(m[1], { expected_rev: p.rev, ops: [{ op: 'solder_done', step_id: m[2], done: body?.done !== false }] }) : null
    }],
    ['POST', /^\/board\/detect$/, (m, body) => detectJob(body)],
    ['POST', /^\/board\/build$/, () => fixtureJob('build')],
    ['POST', /^\/board\/flash$/, () => fixtureJob('flash')],
    ['GET', /^\/board\/flash\/check$/, (m, body, params) => flashCheck(params)],
    ['POST', /^\/serial\/open$/, (m, body) => fxOk('serial.open', `${body?.port} is open (fixture).`, { port: body?.port, state: 'open', baud: 115200, epoch: fx['serial.lines']?.result?.epoch ?? null, simulated: true }, { simulated: true })],
    ['POST', /^\/serial\/close$/, (m, body) => fxOk('serial.close', `${body?.port} is closed (fixture).`, { port: body?.port, state: 'closed' })],
    ['POST', /^\/projects\/([a-z0-9-]{1,48})\/firmware\/example$/, (m) => {
      const p = projects.get(m[1])
      return p ? { ...fxError('project.update', 'project_conflict', `project ${m[1]} already has a firmware folder`, 409, 'pass overwrite: true'), result: { rev: p.rev } } : null
    }]
  ]

  async function handle(method, path, body) {
    if (delayMs) await new Promise(resolve => setTimeout(resolve, delayMs))
    const [p, qs] = String(path).split('?')
    const params = new URLSearchParams(qs || '')
    for (const [verb, re, fn] of routes) {
      const m = verb === method ? re.exec(p) : null
      if (!m) continue
      const env = fn(m, body, params)
      return env ? fxClone(env) : fxError('fixtures', 'fixture_missing', `No fixture for ${method} ${p}.`, 404)
    }
    return fxError('fixtures', 'fixture_missing', `No fixture for ${method} ${p}.`, 404)
  }

  return { handle, projects, reset: seedProjects }
}
