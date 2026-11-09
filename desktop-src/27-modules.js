// Module store: $modCatalog {status, key, env, cats}, $modInfo {[id|variant]: {status, env}}, $calcMeta;
// loaders, hooks, actions

const $modCatalog = sdk.atom({ status: 'idle', key: null, env: null, cats: [] })
const $modInfo = sdk.atom({})
const $calcMeta = sdk.atom({ status: 'idle', env: null, list: [] })
let MOD_CATALOG_SEQ = 0

const modFilterKey = (f = {}) => JSON.stringify([f.q || '', f.category || '', f.interface || ''])

async function loadModuleCatalog(filter = {}, { force = false, more = false } = {}) {
  const key = modFilterKey(filter)
  const cur = $modCatalog.get()
  if (!force && !more && cur.key === key && (cur.status === 'ready' || cur.status === 'loading')) return cur.env
  const seq = ++MOD_CATALOG_SEQ
  const have = more && cur.key === key && cur.env?.ok ? cur.env.result?.items || [] : null // load more: append
  $modCatalog.set({ ...cur, status: 'loading', key })
  const env = await CB.api.modules(filter.q || null, filter.category || null, filter.interface || null, { limit: 200, offset: have?.length || undefined })
  const out = have && env.ok ? { ...env, result: { ...env.result, items: [...have, ...(env.result?.items || [])] } } : have ? cur.env : env
  if (seq === MOD_CATALOG_SEQ) $modCatalog.set({ status: out.ok ? 'ready' : 'error', key, env: out, cats: out.ok ? modCategories(out.result, ...(cur.cats || [])) : cur.cats })
  return env
}

async function loadModuleInfo(id, variant = null) {
  if (!id) return null
  const k = variant ? `${id}|${variant}` : id
  const have = $modInfo.get()[k]
  if (have && have.status !== 'error') return have.env
  $modInfo.set({ ...$modInfo.get(), [k]: { status: 'loading', env: null } })
  const env = await CB.api.module(id, variant)
  $modInfo.set({ ...$modInfo.get(), [k]: { status: env.ok ? 'ready' : 'error', env } })
  return env
}

async function loadCalcMeta() {
  const cur = $calcMeta.get()
  if (cur.status === 'ready' || cur.status === 'loading') return cur.env
  $calcMeta.set({ status: 'loading', env: null, list: [] })
  const env = await CB.api.calcMeta()
  $calcMeta.set({ status: env.ok ? 'ready' : 'error', env, list: calcMetaOf(env) })
  return env
}

function useModuleCatalog(filter = {}) {
  const key = modFilterKey(filter)
  useEffect(() => { loadModuleCatalog(filter) }, [key])
  return sdk.useValue($modCatalog)
}

function useModuleInfo(id, variant = null) {
  useEffect(() => { loadModuleInfo(id, variant) }, [id, variant])
  const all = sdk.useValue($modInfo)
  return all[variant ? `${id}|${variant}` : id] || { status: id ? 'loading' : 'idle', env: null }
}

function useCalcMeta() {
  useEffect(() => { loadCalcMeta() }, [])
  return sdk.useValue($calcMeta)
}

function useProjectModules(project) {
  return useMemo(() => moduleInstances(project), [project])
}

function useModuleCheck() {
  const check = sdk.useValue($check)
  return useMemo(() => ({ modules: modulesResult(check.env), rails: modRails(check.env),
    findings: { ...modFindings(check.env), sources: check.env?.ok ? check.env.sources || [] : [] } }), [check.env])
}

function useModuleInfos(ids) {
  const key = [...new Set(ids)].sort().join(',')
  useEffect(() => { for (const id of key.split(',')) if (id) loadModuleInfo(id) }, [key])
  const all = sdk.useValue($modInfo)
  return useMemo(() => Object.fromEntries(key.split(',').filter(Boolean).map(id => {
    const e = all[id]?.env
    return [id, e?.ok ? e.result?.module ?? e.result : null]
  })), [all, key])
}

// CALC with card calc-<kind> (in the root of `from`) in view
function openCalc(kind, from = null) {
  const root = from ? ownRoot(from) : null
  goStation('calc')
  if (!root || typeof requestAnimationFrame !== 'function') return
  let n = 0
  const look = () => {
    const card = root.querySelector(`[data-cb="calc-${kind}"]`)
    if (card) { card.scrollIntoView?.({ block: 'nearest' }); card.querySelector('input')?.focus?.({ preventScroll: true }) } else if (++n < 20) requestAnimationFrame(look)
  }
  requestAnimationFrame(look)
}

function addModule(payload) {
  const op = addModuleOp(payload)
  return patchOps([op], { okText: `${op.ref || 'Module'} ${op.module} added.` })
}

function connectModule(ref, conn) {
  return patchOps([connectOp(ref, conn)], { okText: `${String(ref).toUpperCase()} connections saved.` })
}

function openModules(init = null) {
  patchAtom($ui, { modal: { type: 'modules', init } })
}
