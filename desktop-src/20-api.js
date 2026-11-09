// Data access: wraps ctx.rest for the bench routes. Every call resolves to a result envelope, never throws.
// Fixture mode (development builds only): CB_FIXTURES is embedded AND the ctx.storage switch `useFixtures` is not
// false. The product build has CB_FIXTURES = null and always talks to the backend.

function fixtureModeOn(ctx) {
  if (CB_FIXTURES === null || typeof CB_FIXTURES !== 'object') return false
  try {
    return ctx?.storage?.get?.('useFixtures', true) !== false
  } catch {
    return true
  }
}

function createApi(ctx) {
  const fixtures = fixtureModeOn(ctx) ? createFixtureBackend(CB_FIXTURES) : null

  async function call(method, path, body, action) {
    if (fixtures) {
      const env = await fixtures.handle(method, path, body)
      return isEnvelope(env) ? env : errorEnvelope(action, 'fixture_missing', `No fixture for ${method} ${path}.`, null, 404)
    }
    try {
      const opts = body === undefined || body === null ? { method } : { method, body }
      return asEnvelope(await ctx.rest(path, opts), action)
    } catch (e) {
      return parseRestError(e, action)
    }
  }

  const enc = encodeURIComponent
  return {
    mode: fixtures ? 'fixtures' : 'live',
    fixtures,
    health: () => call('GET', '/health', null, 'health'),
    doctor: () => call('GET', '/doctor', null, 'doctor.run'),
    projects: () => call('GET', '/projects', null, 'project.list'),
    project: id => call('GET', `/projects/${enc(id)}`, null, 'project.get'),
    patchProject: (id, expectedRev, ops) => call('PATCH', `/projects/${enc(id)}`, { expected_rev: expectedRev, ops }, 'project.update'),
    deleteProject: id => call('DELETE', `/projects/${enc(id)}`, null, 'project.delete'),
    demo: () => call('POST', '/projects/demo', {}, 'sim.demo'),
    board: id => call('GET', `/boards/${enc(id)}`, null, 'board.layout'),
    pinsCheck: body => call('POST', '/pins/check', body, 'pins.check'),
    pinsSuggest: body => call('POST', '/pins/suggest', body, 'pins.suggest'),
    pinsInfo: params => call('GET', `/pins/info${query(params)}`, null, 'pins.info'),
    ports: () => call('GET', '/ports', null, 'board.ports'),
    serialTail: (port, after) => call('GET', `/serial/tail${query({ port, after })}`, null, 'serial.tail'),
    crashDecode: body => call('POST', '/crash/decode', body, 'crash.decode'),
    job: id => call('GET', `/jobs/${enc(id)}`, null, 'job.get'),
    // Workshop, board operation (jobs), serial control. Detect/flash/open only ever run from a click.
    createProject: body => call('POST', '/projects', body, 'project.create'),
    calc: (type, body) => call('POST', `/calc/${enc(type)}`, body, `calc.${type}`),
    schematic: body => call('POST', '/schematic', body, 'schematic.render'),
    solderPlan: body => call('POST', '/solder/plan', body, 'solder.plan'),
    solderStep: (id, stepId, done) => call('POST', `/projects/${enc(id)}/solder/${enc(stepId)}`, { done: Boolean(done) }, 'project.update'),
    firmwareExample: (id, overwrite = false) => call('POST', `/projects/${enc(id)}/firmware/example`, { example: 'laser-trigger', ...(overwrite ? { overwrite: true } : {}) }, 'project.update'),
    detect: body => call('POST', '/board/detect', body, 'board.detect'),
    build: body => call('POST', '/board/build', body, 'board.build'),
    flash: body => call('POST', '/board/flash', body, 'board.flash'),
    // would the flash be refused? (no port opened, no tool started)
    flashCheck: (project, port) => call('GET', `/board/flash/check${query({ project, port })}`, null, 'board.flash_check'),
    serialOpen: body => call('POST', '/serial/open', body, 'serial.open'),
    serialClose: port => call('POST', '/serial/close', { port }, 'serial.close'),
    // module catalog: catalog, one module, calculator metadata. `calc(kind, body)`
    // above is already generic (POST /calc/{kind}); the project ops add_module/connect/set_rails go through
    // patchProject (lib/modules.js addModuleOp/connectOp/setRailsOp build them).
    modules: (q, category, iface, { limit, offset } = {}) =>
      call('GET', `/modules${query({ q, category, interface: iface, limit, offset })}`, null, 'modules.list'),
    module: (id, variant) => call('GET', `/modules/${enc(id)}${query({ variant })}`, null, 'modules.info'),
    calcMeta: () => call('GET', '/calc', null, 'calc.list')
  }
}
